"""Mastodon stuff."""

import time

import mastodon as Mastodon
import requests
from mastodon.errors import MastodonUnauthorizedError
from twisted.python import log
from twisted.words.xish.domish import Element

from iembot.types import JabberClient
from iembot.util import email_error


def load_mastodon_from_db(txn, bot: JabberClient):
    """Load Mastodon config from database"""
    txn.execute("select channel, user_id from iembot_mastodon_subs")
    mdrt = {}
    for row in txn.fetchall():
        mdrt.setdefault(row["channel"], []).append(row["user_id"])
    bot.md_routingtable = mdrt
    log.msg(f"load_mastodon_from_db(): {txn.rowcount} subs found")

    mdusers = {}
    txn.execute(
        """
        select server, o.id, o.access_token, o.screen_name, o.iem_owned
        from iembot_mastodon_apps a JOIN iembot_mastodon_oauth o
            on (a.id = o.appid) WHERE o.access_token is not null and
        not o.disabled
        """
    )
    for row in txn.fetchall():
        mdusers[row["id"]] = {
            "screen_name": row["screen_name"],
            "access_token": row["access_token"],
            "api_base_url": row["server"],
            "iem_owned": row["iem_owned"],
        }
    bot.md_users = mdusers
    log.msg(f"load_mastodon_from_db(): {txn.rowcount} access tokens found")


def disable_mastodon_user(bot: JabberClient, user_id, errcode=0):
    """Disable the Mastodon subs for this user_id

    Args:
        user_id (big_id): The Mastodon user to disable
        errcode (int): The HTTP-like errorcode
    """
    mduser = bot.md_users.get(user_id)
    if mduser is None:
        log.msg(f"Failed to disable unknown Mastodon user_id {user_id}")
        return False
    screen_name = mduser["screen_name"]
    if mduser["iem_owned"]:
        log.msg(
            f"Skipping disabling of Mastodon for {user_id} ({screen_name})"
        )
        return False
    bot.md_users.pop(user_id, None)
    log.msg(
        f"Removing Mastodon access token for user: {user_id} ({screen_name}) "
        f"errcode: {errcode}"
    )
    df = bot.dbpool.runOperation(
        f"UPDATE {bot.name}_mastodon_oauth SET updated = now(), "
        "access_token = null, api_base_url = null "
        "WHERE user_id = %s",
        (user_id,),
    )
    df.addErrback(log.err)
    return True


def toot_cb(response, bot: JabberClient, twttxt, _room, myjid, user_id):
    """
    Called after success going to Mastodon
    """
    if response is None:
        return
    mduser = bot.md_users.get(user_id)
    if mduser is None:
        return response
    if "content" not in response:
        log.msg(f"Got response without content {response}")
        return
    mduser["screen_name"]
    url = response["url"]

    response.pop(
        "account", None
    )  # Remove extra junk, there's still a lot more though...

    # Log
    df = bot.dbpool.runOperation(
        f"INSERT into {bot.name}_social_log(medium, source, resource_uri, "
        "message, response, response_code) values (%s,%s,%s,%s,%s,%s)",
        ("mastodon", myjid, url, twttxt, repr(response), 200),
    )
    df.addErrback(log.err)
    return response


def mastodon_errback(err, bot: JabberClient, user_id, tweettext):
    """Error callback when simple Mastodon workflow fails."""
    # Always log it
    log.err(err)
    errcode = None
    if isinstance(err, Mastodon.errors.MastodonNotFoundError):
        errcode = 404
        disable_mastodon_user(bot, user_id, errcode)
    elif isinstance(err, Mastodon.errors.MastodonUnauthorizedError):
        errcode = 401
        disable_mastodon_user(bot, user_id, errcode)
    else:
        sn = bot.md_users.get(user_id, {}).get("screen_name", "")
        msg = f"User: {user_id} ({sn})\nFailed to toot: {tweettext}"
        email_error(err, bot, msg)


def toot(bot: JabberClient, user_id, twttxt, **kwargs):
    """Blocking Mastodon toot method."""
    if user_id not in bot.md_users:
        log.msg(f"toot() called with unknown Mastodon user_id: {user_id}")
        return None
    api = Mastodon.Mastodon(
        access_token=bot.md_users[user_id]["access_token"],
        api_base_url=bot.md_users[user_id]["api_base_url"],
    )
    log.msg(
        "Sending to Mastodon "
        f"{bot.md_users[user_id]['screen_name']}({user_id}) "
        f"'{twttxt}' media:{kwargs.get('twitter_media')}"
    )
    media = kwargs.get("twitter_media")
    media_id = None

    res = None
    try:
        params = {
            "status": twttxt,
        }
        # If we have media, we have some work to do!
        if media is not None:
            resp = requests.get(media, timeout=30, stream=True)
            resp.raise_for_status()
            # TODO: Is this always image/png?
            media_id = api.media_post(resp.raw, mime_type="image/png")
            params["media_ids"] = [media_id]
        res = api.status_post(**params)
    except MastodonUnauthorizedError:
        # Access token is no longer valid
        disable_mastodon_user(bot, user_id)
        return None
    except Mastodon.errors.MastodonRatelimitError as exp:
        # Submitted too quickly
        log.err(exp)
        # Since this called from a thread, sleeping should not jam us up
        time.sleep(kwargs.get("sleep", 10))
        res = api.status_post(**params)
    except Mastodon.errors.MastodonError as exp:
        # Something else bad happened when submitting this to the Mastodon
        log.err(exp)
        params.pop("media_ids", None)  # Try again without media
        # Since this called from a thread, sleeping should not jam us up
        time.sleep(kwargs.get("sleep", 10))
        try:
            res = api.status_post(**params)
        except Mastodon.errors.MastodonError as exp2:
            log.err(exp2)
    except Exception as exp:
        # Something beyond Mastodon went wrong
        log.err(exp)
        params.pop("media_ids", None)  # Try again without media
        # Since this called from a thread, sleeping should not jam us up
        time.sleep(kwargs.get("sleep", 10))
        res = api.status_post(**params)
    return res


def route(bot: JabberClient, channels: list, elem: Element):
    """Do Maston stuff."""
    alertedPages = []
    for channel in channels:
        for user_id in bot.md_routingtable.get(channel, []):
            if user_id not in bot.md_users:
                log.msg(
                    "Failed to send to Mastodon due to no "
                    f"access_tokens {user_id}"
                )
                continue
            # Require the x.twitter attribute to be set to prevent
            # confusion with some ingestors still sending tweets themselfs
            if not elem.x.hasAttribute("twitter"):
                continue
            if user_id in alertedPages:
                continue
            alertedPages.append(user_id)
            lat = long = None
            if (
                elem.x
                and elem.x.hasAttribute("lat")
                and elem.x.hasAttribute("long")
            ):
                lat = elem.x["lat"]
                long = elem.x["long"]
            # Finally, actually post to Mastodon, this is in basicbot
            bot.toot(
                user_id,
                elem.x["twitter"],
                twitter_media=elem.x.getAttribute("twitter_media"),
                latitude=lat,  # TODO: unused
                longitude=long,  # TODO: unused
            )
