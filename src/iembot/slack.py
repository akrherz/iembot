"""Slack integration work."""

import json
import urllib

import requests
from twisted.internet import threads
from twisted.python import log
from twisted.web import resource
from twisted.web.server import NOT_DONE_YET
from twisted.words.xish.domish import Element

from iembot.types import JabberClient
from iembot.util import build_channel_subs


def send_to_slack(access_token: str, channel_id: str, elem: Element):
    """Send a message to Slack, called from thread."""
    payload = {
        "text": elem.x["twitter"],
        "mrkdwn": False,
        "channel": channel_id,
        "unfurl_links": False,
        "unfurl_media": False,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
    }
    log.msg("Posting to slack")
    resp = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers=headers,
        data=json.dumps(payload),
    )
    log.msg(f"Got response {resp} {resp.content}")
    resp.raise_for_status()


def load_slack_from_db(txn, bot: JabberClient):
    """Load the Slack integration."""
    bot.slack_routingtable = build_channel_subs(
        txn,
        "iembot_slack_team_channels",
    )

    txn.execute(
        """
    select iembot_account_id, c.channel_id, t.access_token from
    iembot_slack_teams t JOIN iembot_slack_team_channels c on
    (t.team_id = c.team_id)
        """
    )
    teams = {}
    xref = {}
    for row in txn.fetchall():
        teams[row["iembot_account_id"]] = {
            "access_token": row["access_token"],
            "channel_id": row["channel_id"],
        }
        xref[row["iembot_account_id"]] = row["channel_id"]

    bot.slack_teams = teams
    log.msg(f"Loaded {len(teams)} Slack teams")


def route(bot: JabberClient, channels: list, elem: Element):
    """Do Slack message routing."""
    alerted = []
    for channel in channels:
        for iembot_account_id in bot.slack_routingtable.get(channel, []):
            if iembot_account_id in alerted:
                continue
            alerted.append(iembot_account_id)
            log.msg("Attempting slack send...")
            meta = bot.slack_teams[iembot_account_id]
            d = threads.deferToThread(
                send_to_slack, meta["access_token"], meta["channel_id"], elem
            )
            d.addErrback(log.msg)


class SlackSubscribeChannel(resource.Resource):
    """respond to /subscribe requests"""

    def __init__(self, iembot: JabberClient):
        """Constructor"""
        resource.Resource.__init__(self)
        self.iembot = iembot

    def store_slack_subscription(
        self,
        txn,
        team_id: str,
        channel_id: str,
        subkey: str,
    ):
        """write to database."""
        log.msg(
            f"Handing slack subscription for T:`{team_id}` TC:`{channel_id}` "
            f"C:`{subkey}`"
        )
        # Step 1, ensure that the slack channel exists
        txn.execute(
            """
    select iembot_account_id from iembot_slack_team_channels
    where team_id = %s and channel_id = %s
            """,
            (team_id, channel_id),
        )
        res = txn.fetchall()
        if not res:
            log.msg(
                f"Slack Team: {team_id} Channel: {channel_id} does not exist "
                "creating..."
            )
            txn.execute(
                """
                insert into iembot_slack_team_channels
                (iembot_account_id, team_id, channel_id)
                values (
                    (select create_iembot_account('slack')), %s, %s)
                returning iembot_account_id
                """,
                (team_id, channel_id),
            )
            res = txn.fetchall()
        iembot_account_id = res[0]["iembot_account_id"]
        txn.execute(
            """
            insert into iembot_subscriptions(iembot_account_id, channel_id)
            values (
                %s,
                (select get_or_create_iembot_channel_id(%s))
            )
            on conflict do nothing
            """,
            (iembot_account_id, subkey),
        )

    def render(self, request):
        """Answer the call."""
        team_id = request.args.get(b"team_id", [b""])[0].decode("ascii")
        channel_id = request.args.get(b"channel_id", [b""])[0].decode("ascii")
        subkey = request.args.get(b"text", [b""])[0].decode("ascii")
        defer = self.iembot.dbpool.runInteraction(
            self.store_slack_subscription,
            team_id,
            channel_id,
            subkey,
        )
        defer.addErrback(
            lambda _: request.write("Error processing subscription")
        )
        defer.addCallback(
            lambda _: request.write(f"Subscribed to {subkey}".encode("ascii"))
        )
        defer.addBoth(lambda _: request.finish())
        defer.addCallback(self.iembot.load_slack)

        return NOT_DONE_YET


class SlackUnsubscribeChannel(resource.Resource):
    """respond to /unsubscribe requests"""

    def __init__(self, iembot: JabberClient):
        """Constructor"""
        resource.Resource.__init__(self)
        self.iembot = iembot

    def remove_slack_subscription(
        self,
        txn,
        team_id,
        channel_id,
        subkey,
    ):
        """write to database."""
        txn.execute(
            """
            delete from iembot_subscriptions
            where iembot_account_id = (
            select iembot_account_id from iembot_slack_team_channels where
            team_id = %s and channel_id = %s) and
            channel_id = get_or_create_iembot_channel_id(%s)
            """,
            (team_id, channel_id, subkey),
        )

    def render(self, request):
        """Answer the call."""
        team_id = request.args.get(b"team_id", [b""])[0].decode("ascii")
        channel_id = request.args.get(b"channel_id", [b""])[0].decode("ascii")
        subkey = request.args.get(b"text", [b""])[0].decode("ascii")
        defer = self.iembot.dbpool.runInteraction(
            self.remove_slack_subscription,
            team_id,
            channel_id,
            subkey,
        )
        defer.addCallback(
            lambda _: request.write(
                f"Unsubscribed from {subkey}".encode("ascii")
            )
        )
        defer.addCallback(lambda _: request.finish())
        defer.addCallback(self.iembot.load_slack)

        return NOT_DONE_YET


class SlackOauthChannel(resource.Resource):
    """respond to /oauth requests"""

    def __init__(self, iembot: JabberClient):
        """Constructor"""
        resource.Resource.__init__(self)
        self.iembot = iembot

    def store_slack_team(self, txn, data):
        """Save."""

    def _eb_oauth(self, failure, request):
        """Errback on oauth call failure."""
        log.msg(f"OAuth error: {failure}")
        request.setResponseCode(500)
        request.write(b"OAuth error")
        request.finish()

    def _cb_oauth(self, message, request):
        """Errback on oauth call success."""
        log.msg(f"OAuth success: {message}")
        request.setResponseCode(200)
        request.write(b"OAuth success")
        request.finish()

    def do_request_in_thread(self, txn, data):
        """Run a request from a dbthread, sigh."""
        token_url = "https://slack.com/api/oauth.v2.access"
        resp = requests.post(
            token_url,
            data,
        )
        jdata = resp.json()
        if jdata.get("ok"):
            txn.execute(
                """
        insert into iembot_slack_teams
            (team_id, team_name, access_token, bot_user_id)
        values (%s, %s, %s, %s)
        on conflict (team_id) do update set
        access_token = excluded.access_token,
        bot_user_id = excluded.bot_user_id,
        team_name = excluded.team_name
        """,
                (
                    jdata["team"]["id"],
                    jdata["team"]["name"],
                    jdata["access_token"],
                    jdata["bot_user_id"],
                ),
            )
        return jdata

    def render(self, request):
        """Answer the call."""
        # Get the posted code parameter
        code = request.args.get(b"code")[0]
        if not code:
            request.setResponseCode(400)
            return b"Missing code parameter"
        # Exchange code for token
        data = {
            "client_id": self.iembot.config["bot.slack.client_id"],
            "client_secret": self.iembot.config["bot.slack.client_secret"],
            "code": code.decode("ascii"),
            "redirect_uri": self.iembot.config["bot.slack.redirect_uri"],
        }
        defer = self.iembot.dbpool.runInteraction(
            self.do_request_in_thread, data
        )
        defer.addCallback(self._cb_oauth, request)
        defer.addCallback(self.iembot.load_slack)
        defer.addErrback(self._eb_oauth, request)
        return NOT_DONE_YET


class SlackInstallChannel(resource.Resource):
    """respond to /oauth requests"""

    def __init__(self, iembot: JabberClient):
        """Constructor"""
        resource.Resource.__init__(self)
        self.iembot = iembot

    def render(self, request):
        """Answer the call."""
        params = {
            "client_id": self.iembot.config["bot.slack.client_id"],
            "scope": (
                "chat:write,channels:read,groups:read,"
                "im:read,mpim:read,commands"
            ),
            "user_scope": "",
            "redirect_uri": self.iembot.config["bot.slack.redirect_uri"],
        }
        url = (
            "https://slack.com/oauth/v2/authorize?"
            f"{urllib.parse.urlencode(params)}"
        )
        # Send 302 header
        request.setResponseCode(302)
        request.setHeader("Location", url)
        return b"Redirecting to Slack"
