"""Slack integration work."""

import json
import urllib

import requests
from twisted.python import log
from twisted.web import resource
from twisted.web.server import NOT_DONE_YET
from twisted.words.xish.domish import Element


def send_to_slack(bot, team_id: str, channel_id: str, elem: Element):
    """Send a message to Slack, called from thread."""
    access_token = bot.slack_teams[team_id]
    payload = {
        "text": elem.x["twitter"],
        "mrkdwn": False,
        "channel": channel_id,
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


def load_slack_from_db(txn, bot):
    """Load the Slack integration."""
    txn.execute(
        """
    select t.team_id, s.channel_id, s.subkey, t.access_token from
    iembot_slack_teams t JOIN iembot_slack_subscriptions s
    on (t.team_id = s.team_id)
        """
    )
    teams = {}
    rt = {}
    for row in txn.fetchall():
        # meh, redundant
        teams[row["team_id"]] = row["access_token"]
        d = rt.setdefault(row["subkey"], [])
        # sigh
        d.append(f"{row['team_id']}|{row['channel_id']}")

    bot.slack_teams = teams
    bot.slack_routingtable = rt
    log.msg(f"Loaded {len(teams)} Slack teams")
    log.msg(f"Loaded {len(rt)} Slack subscriptions")


class SlackSubscribeChannel(resource.Resource):
    """respond to /subscribe requests"""

    def __init__(self, iembot):
        """Constructor"""
        resource.Resource.__init__(self)
        self.iembot = iembot

    def store_slack_subscription(
        self,
        txn,
        team_id,
        channel_id,
        subkey,
    ):
        """write to database."""
        txn.execute(
            """
            insert into iembot_slack_subscriptions(team_id, channel_id, subkey)
            values (%s, %s, %s)
            on conflict do nothing
            """,
            (team_id, channel_id, subkey),
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
        defer.addCallback(
            lambda _: request.write(f"Subscribed to {subkey}".encode("ascii"))
        )
        defer.addCallback(lambda _: request.finish())

        return NOT_DONE_YET


class SlackUnsubscribeChannel(resource.Resource):
    """respond to /unsubscribe requests"""

    def __init__(self, iembot):
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
            delete from iembot_slack_subscriptions
            where team_id = %s and channel_id = %s and subkey = %s
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

        return NOT_DONE_YET


class SlackOauthChannel(resource.Resource):
    """respond to /oauth requests"""

    def __init__(self, iembot):
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
        defer.addErrback(self._eb_oauth, request)
        return NOT_DONE_YET


class SlackInstallChannel(resource.Resource):
    """respond to /oauth requests"""

    def __init__(self, iembot):
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
