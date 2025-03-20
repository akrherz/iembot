"""Utility functions for IEMBot"""

# pylint: disable=protected-access
import copy
import datetime
import glob
import json
import os
import pickle
import pwd
import re
import socket
import time
import traceback
from email.mime.text import MIMEText
from html import unescape
from io import BytesIO
from typing import Optional
from zoneinfo import ZoneInfo

import mastodon
import requests
import twitter
from mastodon.errors import MastodonUnauthorizedError
from pyiem.reference import TWEET_CHARS
from pyiem.util import utc
from requests_oauthlib import OAuth1, OAuth1Session
from twisted.internet import reactor
from twisted.mail import smtp
from twisted.python import log
from twisted.words.xish import domish
from twitter.error import TwitterError

import iembot

TWEET_API = "https://api.twitter.com/2/tweets"
# 89: Expired token, so we shall revoke for now
# 185: User is over quota
# 226: Twitter thinks this tweeting user is spammy, le sigh
# 326: User is temporarily locked out
# 64: User is suspended
DISABLE_TWITTER_CODES = [89, 185, 226, 326, 64]


def at_send_message(bot, user_id, msg: str, **kwargs):
    """Send a message to the ATmosphere."""
    at_handle = bot.tw_users.get(user_id, {}).get("at_handle")
    if at_handle is None:
        return
    message = {"msg": msg}
    message.update(kwargs)
    bot.at_manager.submit(at_handle, message)


def _upload_media_to_twitter(oauth: OAuth1Session, url: str) -> Optional[str]:
    """Upload Media to Twitter and return its ID"""
    resp = requests.get(url, timeout=30)
    if resp.status_code != 200:
        log.msg(f"Fetching `{url}` got status_code: {resp.status_code}")
        return None
    payload = resp.content
    resp = oauth.post(
        "https://api.x.com/2/media/upload",
        files={"media": (url, payload, "image/png")},
    )
    if resp.status_code != 200:
        log.msg(f"Twitter API got status_code: {resp.status_code}")
        return None
    # string required
    return str(resp.json()["id"])


def tweet(bot, user_id, twttxt, **kwargs):
    """Blocking tweet method."""
    if user_id not in bot.tw_users:
        log.msg(f"tweet() called with unknown user_id: {user_id}")
        return None
    if bot.tw_users[user_id]["access_token"] is None:
        log.msg(f"tweet() called with no access token for {user_id}")
        return None
    api = twitter.Api(
        consumer_key=bot.config["bot.twitter.consumerkey"],
        consumer_secret=bot.config["bot.twitter.consumersecret"],
        access_token_key=bot.tw_users[user_id]["access_token"],
        access_token_secret=bot.tw_users[user_id]["access_token_secret"],
    )
    # Le Sigh, api.__auth is private
    auth = OAuth1(
        bot.config["bot.twitter.consumerkey"],
        bot.config["bot.twitter.consumersecret"],
        bot.tw_users[user_id]["access_token"],
        bot.tw_users[user_id]["access_token_secret"],
    )
    oauth = OAuth1Session(
        bot.config["bot.twitter.consumerkey"],
        bot.config["bot.twitter.consumersecret"],
        bot.tw_users[user_id]["access_token"],
        bot.tw_users[user_id]["access_token_secret"],
    )
    log.msg(
        f"Tweeting {bot.tw_users[user_id]['screen_name']}({user_id}) "
        f"'{twttxt}' media:{kwargs.get('twitter_media')}"
    )
    media = kwargs.get("twitter_media")

    def _helper(params):
        """Wrap common stuff"""
        resp = api._session.post(TWEET_API, auth=auth, json=params)
        hh = "x-app-limit-24hour-remaining"
        log.msg(
            f"x-rate-limit-limit {resp.headers.get('x-rate-limit-limit')} + "
            f"{hh} {resp.headers.get(hh)}"
        )
        return api._ParseAndCheckTwitter(resp.content.decode("utf-8"))

    res = None
    try:
        params = {
            "text": twttxt,
        }
        # If we have media, we have some work to do!
        if media is not None:
            media_id = _upload_media_to_twitter(oauth, media)
            if media_id is not None:
                params["media"] = {"media_ids": [media_id]}
        res = _helper(params)
    except TwitterError as exp:
        errcode = twittererror_exp_to_code(exp)
        if errcode in [185, 187]:
            # 185: Over quota
            # 187: duplicate tweet
            return None
        if errcode in DISABLE_TWITTER_CODES:
            disable_twitter_user(bot, user_id, errcode)
            return None

        # Something bad happened with submitting this to twitter
        if str(exp).startswith("media type unrecognized"):
            # The media content hit some error, just send it without it
            log.msg(f"Sending '{kwargs.get('twitter_media')}' fail, stripping")
            params.pop("media", None)
        else:
            log.err(exp)
            # Since this called from a thread, sleeping should not jam us up
            time.sleep(10)
        res = _helper(params)
    except Exception as exp:
        log.err(exp)
        # Since this called from a thread, sleeping should not jam us up
        time.sleep(10)
        params.pop("media", None)
        res = _helper(params)
    return res


def toot(bot, user_id, twttxt, **kwargs):
    """Blocking Mastodon toot method."""
    if user_id not in bot.md_users:
        log.msg(f"toot() called with unknown Mastodon user_id: {user_id}")
        return None
    api = mastodon.Mastodon(
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
    except mastodon.errors.MastodonRatelimitError as exp:
        # Submitted too quickly
        log.err(exp)
        # Since this called from a thread, sleeping should not jam us up
        time.sleep(kwargs.get("sleep", 10))
        res = api.status_post(**params)
    except mastodon.errors.MastodonError as exp:
        # Something else bad happened when submitting this to the Mastodon
        log.err(exp)
        params.pop("media_ids", None)  # Try again without media
        # Since this called from a thread, sleeping should not jam us up
        time.sleep(kwargs.get("sleep", 10))
        try:
            res = api.status_post(**params)
        except mastodon.errors.MastodonError as exp2:
            log.err(exp2)
    except Exception as exp:
        # Something beyond Mastodon went wrong
        log.err(exp)
        params.pop("media_ids", None)  # Try again without media
        # Since this called from a thread, sleeping should not jam us up
        time.sleep(kwargs.get("sleep", 10))
        res = api.status_post(**params)
    return res


def channels_room_list(bot, room):
    """
    Send a listing of channels that the room is subscribed to...
    @param room to list
    """
    channels = [
        channel
        for channel in bot.routingtable.keys()
        if room in bot.routingtable[channel]
    ]

    # Need to add a space in the channels listing so that the string does
    # not get so long that it causes chat clients to bail
    msg = f"This room is subscribed to {len(channels)} channels ({channels})"
    bot.send_groupchat(room, msg)


def channels_room_add(txn, bot, room, channel):
    """Add a channel subscription to a chatroom

    Args:
        txn (cursor): database transaction
        bot (iembot.Basicbot): bot instance
        room (str): the chatroom to add the subscription to
        channel (str): the channel to subscribe to for the room
    """
    # Remove extraneous fluff, all channels are uppercase
    channel = channel.upper().strip().replace(" ", "")
    if channel == "":
        bot.send_groupchat(
            room,
            "Failed to add channel to room subscription, you supplied a "
            "blank channel?",
        )
        return
    # Allow channels to be comma delimited
    for ch in channel.split(","):
        if ch not in bot.routingtable:
            bot.routingtable[ch] = []
        # If we are already subscribed, let em know!
        if room in bot.routingtable[ch]:
            bot.send_groupchat(
                room,
                "Error adding subscription, your room is already subscribed "
                f"to the '{ch}' channel",
            )
            continue
        # Add a channels entry for this channel, if one currently does
        # not exist
        txn.execute(
            f"SELECT * from {bot.name}_channels WHERE id = %s",
            (ch,),
        )
        if txn.rowcount == 0:
            txn.execute(
                f"INSERT into {bot.name}_channels(id, name) VALUES (%s, %s)",
                (ch, ch),
            )

        # Add to routing table
        bot.routingtable[ch].append(room)
        # Add to database
        txn.execute(
            f"INSERT into {bot.name}_room_subscriptions "
            "(roomname, channel) VALUES (%s, %s)",
            (room, ch),
        )
        bot.send_groupchat(room, f"Subscribed {room} to channel '{ch}'")
    # Send room a listing of channels!
    channels_room_list(bot, room)


def channels_room_del(txn, bot, room, channel):
    """Removes a channel subscription for a given room

    Args:
        txn (cursor): database cursor
        room (str): room to unsubscribe
        channel (str): channel to unsubscribe from
    """
    channel = channel.upper().strip().replace(" ", "")
    if channel == "":
        bot.send_groupchat(room, "Blank or missing channel")
        return

    for ch in channel.split(","):
        if ch not in bot.routingtable:
            bot.send_groupchat(room, f"Unknown channel: '{ch}'")
            continue

        if room not in bot.routingtable[ch]:
            bot.send_groupchat(room, f"Room not subscribed to channel: '{ch}'")
            continue

        # Remove from routing table
        bot.routingtable[ch].remove(room)
        # Remove from database
        txn.execute(
            f"DELETE from {bot.name}_room_subscriptions WHERE "
            "roomname = %s and channel = %s",
            (room, ch),
        )
        bot.send_groupchat(room, f"Unscribed {room} to channel '{ch}'")
    channels_room_list(bot, room)


def purge_logs(bot):
    """Remove chat logs on a 24 HR basis"""
    log.msg("purge_logs() called...")
    basets = utc() - datetime.timedelta(
        days=int(bot.config.get("bot.purge_xmllog_days", 7))
    )
    for fn in glob.glob("logs/xmllog.*"):
        ts = datetime.datetime.strptime(fn, "logs/xmllog.%Y_%m_%d")
        ts = ts.replace(tzinfo=ZoneInfo("UTC"))
        if ts < basets:
            log.msg(f"Purging logfile {fn}")
            os.remove(fn)


def email_error(exp, bot, message=""):
    """
    Something to email errors when something fails
    """
    # Always log a message about our fun
    cstr = BytesIO()
    if isinstance(exp, Exception):
        traceback.print_exc(file=cstr)
        cstr.seek(0)
        if isinstance(exp, Exception):
            log.err(exp)
        else:
            log.msg(exp)
    log.msg(message)

    def should_email():
        """Should we send an email?"""
        # bot.email_timestamps contains timestamps of emails we *sent*
        utcnow = utc()
        # If we don't have any entries, we should email!
        if len(bot.email_timestamps) < 10:
            bot.email_timestamps.insert(0, utcnow)
            return True
        delta = utcnow - bot.email_timestamps[-1]
        # Effectively limits to 10 per hour
        if delta < datetime.timedelta(hours=1):
            return False
        # We are going to email!
        bot.email_timestamps.insert(0, utcnow)
        # trim listing to 10 entries
        while len(bot.email_timestamps) > 10:
            bot.email_timestamps.pop()
        return True

    # Logic to prevent email bombs
    if not should_email():
        log.msg("Email threshold exceeded, so no email sent!")
        return False

    le = " ".join([f"{_:.2f}" for _ in os.getloadavg()])
    tb = cstr.getvalue().decode("utf-8")
    if tb != "":
        tb = f"Exception       : {tb}\n"
    expmsg = ""
    if exp is not None:
        expmsg = f"Exception       : {exp}\n"
    msg = MIMEText(
        f"System          : {pwd.getpwuid(os.getuid())[0]}@"
        f"{socket.gethostname()} [CWD: {os.getcwd()}]\n"
        f"System UTC date : {utc()}\n"
        f"process id      : {os.getpid()}\n"
        f"iembot.version  : {iembot.__version__}\n"
        f"system load     : {le}\n"
        f"{tb}"
        f"{expmsg}"
        f"Message: {message}\n"
    )
    msg["subject"] = f"[bot] Traceback -- {socket.gethostname()}"

    msg["From"] = bot.config.get("bot.email_errors_from", "root@localhost")
    msg["To"] = bot.config.get("bot.email_errors_to", "root@localhost")

    df = smtp.sendmail(
        bot.config.get("bot.smtp_server", "localhost"),
        msg["From"],
        msg["To"],
        msg,
    )
    df.addErrback(log.err)
    return True


def disable_twitter_user(bot, user_id, errcode=0):
    """Disable the twitter subs for this user_id

    Args:
        user_id (big_id): The twitter user to disable
        errcode (int): The twitter errorcode
    """
    twuser = bot.tw_users.get(user_id)
    if twuser is None:
        log.msg(f"Failed to disable unknown twitter user_id {user_id}")
        return False
    screen_name = twuser["screen_name"]
    if twuser["iem_owned"]:
        log.msg(f"Skipping disabling of twitter for {user_id} ({screen_name})")
        return False
    bot.tw_users.pop(user_id, None)
    log.msg(
        f"Removing twitter access token for user: {user_id} ({screen_name}) "
        f"errcode: {errcode}"
    )
    df = bot.dbpool.runOperation(
        f"UPDATE {bot.name}_twitter_oauth SET updated = now(), "
        "access_token = null, access_token_secret = null "
        "WHERE user_id = %s",
        (user_id,),
    )
    df.addErrback(log.err)
    return True


def tweet_cb(response, bot, twttxt, _room, myjid, user_id):
    """
    Called after success going to twitter
    """
    if response is None:
        return
    twuser = bot.tw_users.get(user_id)
    if twuser is None:
        return response
    if "data" not in response:
        log.msg(f"Got response without data {response}")
        return
    screen_name = twuser["screen_name"]
    url = f"https://twitter.com/{screen_name}/status/{response['data']['id']}"

    # Log
    df = bot.dbpool.runOperation(
        f"INSERT into {bot.name}_social_log(medium, source, resource_uri, "
        "message, response, response_code) values (%s,%s,%s,%s,%s,%s)",
        ("twitter", myjid, url, twttxt, repr(response), 200),
    )
    df.addErrback(log.err)
    return response


def twittererror_exp_to_code(exp) -> int:
    """Convert a TwitterError Exception into a code.

    Args:
      exp (TwitterError): The exception to convert
    """
    errcode = None
    errmsg = str(exp)
    # brittle :(
    errmsg = errmsg[errmsg.find("[{") : errmsg.find("}]") + 2].replace(
        "'", '"'
    )
    try:
        errobj = json.loads(errmsg)
        errcode = errobj[0].get("code", 0)
    except Exception as exp2:
        log.msg(f"Failed to parse code TwitterError: {exp2}")
    return errcode


def twitter_errback(err, bot, user_id, tweettext):
    """Error callback when simple twitter workflow fails."""
    # Always log it
    log.err(err)
    errcode = twittererror_exp_to_code(err)
    if errcode in DISABLE_TWITTER_CODES:
        disable_twitter_user(bot, user_id, errcode)
    else:
        sn = bot.tw_users.get(user_id, {}).get("screen_name", "")
        msg = f"User: {user_id} ({sn})\nFailed to tweet: {tweettext}"
        email_error(err, bot, msg)


def disable_mastodon_user(bot, user_id, errcode=0):
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


def toot_cb(response, bot, twttxt, _room, myjid, user_id):
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


def mastodon_errback(err, bot, user_id, tweettext):
    """Error callback when simple Mastodon workflow fails."""
    # Always log it
    log.err(err)
    errcode = None
    if isinstance(err, mastodon.errors.MastodonNotFoundError):
        errcode = 404
        disable_mastodon_user(bot, user_id, errcode)
    elif isinstance(err, mastodon.errors.MastodonUnauthorizedError):
        errcode = 401
        disable_mastodon_user(bot, user_id, errcode)
    else:
        sn = bot.md_users.get(user_id, {}).get("screen_name", "")
        msg = f"User: {user_id} ({sn})\nFailed to toot: {tweettext}"
        email_error(err, bot, msg)


def load_chatrooms_from_db(txn, bot, always_join):
    """Load database configuration and do work

    Args:
      txn (dbtransaction): database cursor
      bot (BasicBot): the running bot instance
      always_join (boolean): do we force joining each room, regardless
    """
    # Load up the routingtable for bot products
    rt = {}
    txn.execute(
        f"SELECT roomname, channel from {bot.name}_room_subscriptions "
        "WHERE roomname is not null and channel is not null"
    )
    rooms = []
    for row in txn.fetchall():
        rm = row["roomname"]
        channel = row["channel"]
        if channel not in rt:
            rt[channel] = []
        rt[channel].append(rm)
        if rm not in rooms:
            rooms.append(rm)
    bot.routingtable = rt
    log.msg(
        f"... loaded {txn.rowcount} channel subscriptions for "
        f"{len(rooms)} rooms"
    )

    # Load up a list of chatrooms
    txn.execute(
        f"SELECT roomname, twitter from {bot.name}_rooms "
        "WHERE roomname is not null ORDER by roomname ASC"
    )
    oldrooms = list(bot.rooms.keys())
    joined = 0
    for i, row in enumerate(txn.fetchall()):
        rm = row["roomname"]
        # Setup Room Config Dictionary
        if rm not in bot.rooms:
            bot.rooms[rm] = {
                "twitter": None,
                "occupants": {},
                "joined": False,
            }
        bot.rooms[rm]["twitter"] = row["twitter"]

        if always_join or rm not in oldrooms:
            presence = domish.Element(("jabber:client", "presence"))
            presence["to"] = f"{rm}@{bot.conference}/{bot.myjid.user}"
            # Some jitter to prevent overloading
            jitter = (
                0
                if rm
                in [
                    "botstalk",
                ]
                else i % 30
            )
            reactor.callLater(jitter, bot.xmlstream.send, presence)
            joined += 1
        if rm in oldrooms:
            oldrooms.remove(rm)

    # Check old rooms for any rooms we need to vacate!
    for rm in oldrooms:
        presence = domish.Element(("jabber:client", "presence"))
        presence["to"] = f"{rm}@{bot.conference}/{bot.myjid.user}"
        presence["type"] = "unavailable"
        bot.xmlstream.send(presence)

        del bot.rooms[rm]
    log.msg(
        f"... loaded {txn.rowcount} chatrooms, joined {joined} of them, "
        f"left {len(oldrooms)} of them"
    )


def load_webhooks_from_db(txn, bot):
    """Load twitter config from database"""
    txn.execute(
        f"SELECT channel, url from {bot.name}_webhooks "
        "WHERE channel is not null and url is not null"
    )
    table = {}
    for row in txn.fetchall():
        url = row["url"]
        channel = row["channel"]
        if url == "" or channel == "":
            continue
        res = table.setdefault(channel, [])
        res.append(url)
    bot.webhooks_routingtable = table
    log.msg(f"load_webhooks_from_db(): {txn.rowcount} subs found")


def load_twitter_from_db(txn, bot):
    """Load twitter config from database"""
    # Don't waste time by loading up subs from unauthed users, but we could
    # have iem_owned accounts with bluesky only creds
    txn.execute(
        f"""
    select s.user_id, channel from {bot.name}_twitter_subs s
    JOIN iembot_twitter_oauth o on (s.user_id = o.user_id)
    WHERE s.user_id is not null and s.channel is not null
    and (o.iem_owned or (o.access_token is not null and not o.disabled))
    """
    )
    twrt = {}
    for row in txn.fetchall():
        user_id = row["user_id"]
        channel = row["channel"]
        d = twrt.setdefault(channel, [])
        d.append(user_id)
    bot.tw_routingtable = twrt
    log.msg(f"load_twitter_from_db(): {txn.rowcount} subs found")

    twusers = {}
    txn.execute(
        """
    SELECT user_id, access_token, access_token_secret, screen_name,
    iem_owned, at_handle, at_app_pass from
    iembot_twitter_oauth WHERE (iem_owned or (access_token is not null and
    access_token_secret is not null)) and user_id is not null and
    screen_name is not null and not disabled
    """
    )
    for row in txn.fetchall():
        user_id = row["user_id"]
        twusers[user_id] = {
            "screen_name": row["screen_name"],
            "access_token": row["access_token"],
            "access_token_secret": row["access_token_secret"],
            "iem_owned": row["iem_owned"],
            "at_handle": row["at_handle"],
        }
        if row["at_handle"]:
            bot.at_manager.add_client(row["at_handle"], row["at_app_pass"])
    bot.tw_users = twusers
    log.msg(f"load_twitter_from_db(): {txn.rowcount} oauth tokens found")


def load_mastodon_from_db(txn, bot):
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


def load_chatlog(bot):
    """load up our pickled chatlog"""
    if not os.path.isfile(bot.picklefile):
        log.msg(f"pickfile not found: {bot.picklefile}")
        return
    try:
        with open(bot.picklefile, "rb") as fh:
            oldlog = pickle.load(fh)
        for rm in oldlog:
            rmlog = oldlog[rm]
            bot.chatlog[rm] = copy.deepcopy(rmlog)
            if not rmlog:
                continue
            # First message in list is the newest :/
            seq = rmlog[0].seqnum
            if seq is not None and int(seq) > bot.seqnum:
                bot.seqnum = int(seq)
        log.msg(
            f"Loaded CHATLOG pickle: {bot.picklefile}, seqnum: {bot.seqnum}"
        )
    except Exception as exp:
        log.err(exp)


def safe_twitter_text(text):
    """Attempt to rip apart a message that is too long!
    To be safe, the URL is counted as 24 chars
    """
    # XMPP payload will have entities, unescape those before tweeting
    text = unescape(text)
    # Convert two or more spaces into one
    text = " ".join(text.split())
    # If we are already below TWEET_CHARS, we don't have any more work to do...
    if len(text) < TWEET_CHARS and text.find("http") == -1:
        return text
    chars = 0
    words = text.split()
    # URLs only count as 25 chars, so implement better accounting
    for word in words:
        if word.startswith("http"):
            chars += 25
        else:
            chars += len(word) + 1
    if chars < TWEET_CHARS:
        return text
    urls = re.findall(r"https?://[^\s]+", text)
    if len(urls) == 1:
        text2 = text.replace(urls[0], "")
        sections = re.findall("(.*) for (.*)( till [0-9A-Z].*)", text2)
        if len(sections) == 1:
            text = f"{sections[0][0]}{sections[0][2]}{urls[0]}"
            if len(text) > TWEET_CHARS:
                sz = TWEET_CHARS - 26 - len(sections[0][2])
                text = f"{sections[0][0][:sz]}{sections[0][2]}{urls[0]}"
            return text
        if len(text) > TWEET_CHARS:
            # 25 for URL, three dots and space for 29
            return f"{text2[: (TWEET_CHARS - 29)]}... {urls[0]}"
    if chars > TWEET_CHARS:
        if words[-1].startswith("http"):
            i = -2
            while len(" ".join(words[:i])) > (TWEET_CHARS - 3 - 25):
                i -= 1
            return f"{' '.join(words[:i])}... {words[-1]}"
    return text[:TWEET_CHARS]


def html_encode(s):
    """Convert stuff in nws text to entities"""
    htmlCodes = (
        ("'", "&#39;"),
        ('"', "&quot;"),
        (">", "&gt;"),
        ("<", "&lt;"),
        ("&", "&amp;"),
    )
    for code in htmlCodes:
        s = s.replace(code[0], code[1])
    return s


def htmlentities(text):
    """Escape chars in the text for HTML presentation

    Args:
      text (str): subject to replace

    Returns:
      str : result of replacement
    """
    for lookfor, replacewith in [
        ("&", "&amp;"),
        (">", "&gt;"),
        ("<", "&lt;"),
        ("'", "&#39;"),
        ('"', "&quot;"),
    ]:
        text = text.replace(lookfor, replacewith)
    return text


def remove_control_characters(html):
    """Get rid of cruft?"""
    # https://github.com/html5lib/html5lib-python/issues/96
    html = re.sub("[\x00-\x08\x0b\x0e-\x1f\x7f]", "", html)
    return html


def add_entry_to_rss(entry, rss):
    """Convert a txt Jabber room message to a RSS feed entry

    Args:
      entry(iembot.basicbot.CHAT_LOG_ENTRY): entry

    Returns:
      PyRSSGen.RSSItem
    """
    ts = datetime.datetime.strptime(entry.timestamp, "%Y%m%d%H%M%S")
    txt = entry.txtlog
    m = re.search(r"https?://", txt)
    urlpos = -1
    if m:
        urlpos = m.start()
    else:
        txt += "  "
    ltxt = txt[urlpos:].replace("&amp;", "&").strip()
    if ltxt == "":
        ltxt = "https://mesonet.agron.iastate.edu/projects/iembot/"
    fe = rss.add_entry(order="append")
    fe.title(txt[:urlpos].strip())
    fe.link(link={"href": ltxt})
    txt = remove_control_characters(entry.product_text)
    fe.content(f"<pre>{htmlentities(txt)}</pre>", type="CDATA")
    fe.pubDate(ts.strftime("%a, %d %b %Y %H:%M:%S GMT"))


def daily_timestamp(bot):
    """Send a timestamp to each room we are in.

    Args:
      bot (iembot.basicbot) instance
    """
    # Make sure we are a bit into the future!
    utc0z = utc() + datetime.timedelta(hours=1)
    utc0z = utc0z.replace(hour=0, minute=0, second=0, microsecond=0)
    mess = f"------ {utc0z:%b %-d, %Y} [UTC] ------"
    for rm in bot.rooms:
        bot.send_groupchat(rm, mess)

    tnext = utc0z + datetime.timedelta(hours=24)
    delta = (tnext - utc()).total_seconds()
    log.msg(f"Calling daily_timestamp in {delta:.2f} seconds")
    return reactor.callLater(delta, daily_timestamp, bot)
