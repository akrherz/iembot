"""Mastodon stuff."""

import time

import mastodon as Mastodon
import requests
from mastodon.errors import MastodonError
from twisted.internet import threads
from twisted.python import log
from twisted.words.xish.domish import Element

from iembot.types import JabberClient
from iembot.util import build_channel_subs, email_error, safe_twitter_text


def load_mastodon_from_db(txn, bot: JabberClient):
    """Load Mastodon config from database"""
    bot.md_routingtable = build_channel_subs(
        txn,
        "iembot_mastodon_oauth",
    )

    mdusers = {}
    txn.execute(
        """
        select server, o.iembot_account_id,
        o.access_token, o.screen_name, o.iem_owned
        from iembot_mastodon_apps a JOIN iembot_mastodon_oauth o
            on (a.id = o.appid) WHERE o.access_token is not null and
        not o.disabled
        """
    )
    for row in txn.fetchall():
        mdusers[row["iembot_account_id"]] = {
            "screen_name": row["screen_name"],
            "access_token": row["access_token"],
            "api_base_url": row["server"],
            "iem_owned": row["iem_owned"],
        }
    bot.md_users = mdusers
    log.msg(f"load_mastodon_from_db(): {txn.rowcount} access tokens found")


def disable_user_by_mastodon_exp(
    bot: JabberClient, iembot_account_id: int, exp: MastodonError
) -> bool:
    """Review the exception to see what we want to do with it.

    Returns ``True`` if the user got disabled due to the exp
    """
    mduser = bot.md_users.get(iembot_account_id)
    # Test 1. Can't disable an unknown user (likely disabled before)
    if mduser is None:
        log.msg(f"Fail disable unknown Mastodon user_id {iembot_account_id}")
        return True
    # Test 2. Don't disable iem owned accounts
    screen_name = mduser["screen_name"]
    if mduser["iem_owned"]:
        log.msg(
            f"Skip disable Mastodon for {iembot_account_id} ({screen_name})"
        )
        return False
    if len(exp.args) < 2:
        log.msg(
            f"Unexpected MastodonError format for user: {iembot_account_id} "
            f"({screen_name}) exp: {exp} exp.args: {exp.args}"
        )
        return False
    status_code = exp.args[1]
    if status_code >= 500 or status_code == 404:
        log.msg(
            f"Not disabling user: {iembot_account_id} ({screen_name}) "
            f"due to Mastodon server error: {exp.args}"
        )
        return False

    bot.md_users.pop(iembot_account_id)
    log.msg(
        f"Removing Mastodon access token for user: {iembot_account_id} "
        f"({screen_name}) due to {exp.args}"
    )
    df = bot.dbpool.runOperation(
        "UPDATE iembot_mastodon_oauth SET updated = now(), "
        "access_token = null WHERE iembot_account_id = %s",
        (iembot_account_id,),
    )
    df.addErrback(log.err)
    return True


def toot_cb(response, bot: JabberClient, twttxt, iembot_account_id):
    """
    Called after success going to Mastodon
    """
    if response is None:
        return None
    mduser = bot.md_users.get(iembot_account_id)
    if mduser is not None:
        url = response["url"]

        response.pop(
            "account", None
        )  # Remove extra junk, there's still a lot more though...

        # Log
        df = bot.dbpool.runOperation(
            "INSERT into iembot_social_log(medium, source, resource_uri, "
            "message, response, response_code, iembot_account_id) "
            "values (%s,%s,%s,%s,%s,%s,%s)",
            (
                "mastodon",
                "",
                url,
                twttxt,
                repr(response),
                200,
                iembot_account_id,
            ),
        )
        df.addErrback(log.err)
    return response


def toot(self, iembot_account_id: int, twttxt: str, **kwargs):
    """
    Send a message to Mastodon
    """
    df = threads.deferToThread(
        really_toot,
        self,
        iembot_account_id,
        twttxt,
        **kwargs,
    )
    df.addCallback(toot_cb, self, twttxt, iembot_account_id)
    df.addErrback(
        email_error,
        self,
        f"Mastodon User: {iembot_account_id}, Text: {twttxt} Hit exception",
    )
    return df


def really_toot(
    bot: JabberClient, iembot_account_id: int, twttxt: str, **kwargs
) -> dict | None:
    """Called from a thread, so we can block here."""
    meta = bot.md_users.get(iembot_account_id)
    if meta is None:
        log.msg(f"toot() called with unknown user: {iembot_account_id}")
        return None
    api = Mastodon.Mastodon(
        access_token=meta["access_token"],
        api_base_url=meta["api_base_url"],
    )
    media = kwargs.get("twitter_media")
    media_id = None

    params = {
        "status": twttxt,
    }
    for attempt in range(2):
        try:
            # If we have media, we have some work to do!
            if media is not None:
                resp = requests.get(media, timeout=30, stream=True)
                media = None  # One shot
                resp.raise_for_status()
                # TODO: Is this always image/png?
                media_id = api.media_post(resp.raw, mime_type="image/png")
                params["media_ids"] = [media_id]
            return api.status_post(**params)
        except Exception as exp:  # This is the base Exception in mastodon
            log.msg(
                "Error sending to Mastodon "
                f"{meta['screen_name']}({iembot_account_id}) "
                f"'{twttxt}' media:{media}"
            )
            if isinstance(exp, MastodonError) and disable_user_by_mastodon_exp(
                bot, iembot_account_id, exp
            ):
                return None
            # Something else bad happened when submitting this to the Mastodon
            log.err(exp)
            params.pop("media_ids", None)  # Try again without media
            if attempt == 0:
                # Since this called from a thread, sleeping should not jam
                time.sleep(kwargs.get("sleep", 10))
    return None


def route(bot: JabberClient, channels: list, elem: Element):
    """Do Maston stuff."""
    # Require the x.twitter attribute to be set to prevent
    # confusion with some ingestors still sending tweets themselfs
    if not elem.x or not elem.x.hasAttribute("twitter"):
        return

    txt = safe_twitter_text(elem.x["twitter"])
    twitter_media = elem.x.getAttribute("twitter_media")

    alerted = []
    for channel in channels:
        for iembot_account_id in bot.md_routingtable.get(channel, []):
            if iembot_account_id in alerted:
                continue
            alerted.append(iembot_account_id)
            toot(
                bot,
                iembot_account_id,
                txt,
                twitter_media=twitter_media,
            )
