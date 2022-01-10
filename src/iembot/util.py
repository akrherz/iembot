"""Utility functions for IEMBot"""
import datetime
from html import unescape
import re
import os
import socket
import json
import glob
import pickle
from email.mime.text import MIMEText
import time
import traceback
import pwd
from io import BytesIO

# Third Party
import pytz
import twitter
from twisted.internet import reactor
from twisted.mail import smtp
from twisted.python import log
from twisted.words.xish import domish
from twitter.error import TwitterError
from pyiem.util import utc
from pyiem.reference import TWEET_CHARS

# local
import iembot


def tweet(bot, user_id, twttxt, **kwargs):
    """Blocking tweet method."""
    api = twitter.Api(
        consumer_key=bot.config["bot.twitter.consumerkey"],
        consumer_secret=bot.config["bot.twitter.consumersecret"],
        access_token_key=bot.tw_users[user_id]["access_token"],
        access_token_secret=bot.tw_users[user_id]["access_token_secret"],
    )
    log.msg(
        f"Tweeting {bot.tw_users[user_id]['screen_name']}({user_id}) "
        f"'{twttxt}' media:{kwargs.get('twitter_media')}"
    )
    try:
        res = api.PostUpdate(
            twttxt,
            latitude=kwargs.get("latitude", None),
            longitude=kwargs.get("longitude", None),
            media=kwargs.get("twitter_media"),
        )
    except twitter.error.TwitterError as exp:
        # Something bad happened with submitting this to twitter
        if str(exp).startswith("media type unrecognized"):
            # The media content hit some error, just send it without it
            log.msg(f"Sending '{kwargs.get('twitter_media')}' fail, stripping")
            res = api.PostUpdate(twttxt)
        else:
            log.err(exp)
            # Since this called from a thread, sleeping should not jam us up
            time.sleep(10)
            res = api.PostUpdate(
                twttxt,
                latitude=kwargs.get("latitude", None),
                longitude=kwargs.get("longitude", None),
                media=kwargs.get("twitter_media"),
            )
    except Exception as exp:
        log.err(exp)
        # Since this called from a thread, sleeping should not jam us up
        time.sleep(10)
        res = api.PostUpdate(
            twttxt,
            latitude=kwargs.get("latitude", None),
            longitude=kwargs.get("longitude", None),
        )
    return res


def channels_room_list(bot, room):
    """
    Send a listing of channels that the room is subscribed to...
    @param room to list
    """
    channels = []
    for channel in bot.routingtable.keys():
        if room in bot.routingtable[channel]:
            channels.append(channel)

    # Need to add a space in the channels listing so that the string does
    # not get so long that it causes chat clients to bail
    msg = (
        f"This room is subscribed to {len(channels)} channels "
        f"({'', ''.join(channels)})"
    )
    bot.send_groupchat(room, msg)


def channels_room_add(txn, bot, room, channel):
    """Add a channel subscription to a chatroom

    Args:
        txn (psycopg2.transaction): database transaction
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
        txn (psycopg2.transaction): database cursor
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
        ts = ts.replace(tzinfo=pytz.UTC)
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

    le = ' '.join([f'{_:.2f}' for _ in os.getloadavg()])
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
    if screen_name.startswith("iembot_"):
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


def tweet_cb(response, bot, twttxt, room, myjid, user_id):
    """
    Called after success going to twitter
    """
    if response is None:
        return
    twuser = bot.tw_users.get(user_id)
    if twuser is None:
        return response
    screen_name = twuser["screen_name"]
    url = f"https://twitter.com/{screen_name}"
    if isinstance(response, twitter.Status):
        url = f"{url}/status/{response.id}"
    else:
        url = f"{url}/status/{response}"

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
    if isinstance(exp, TwitterError):
        errmsg = str(exp)
        errmsg = errmsg[errmsg.find("["):].replace("'", '"')
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
    if errcode in [89, 185, 326, 64]:
        # 89: Expired token, so we shall revoke for now
        # 185: User is over quota
        # 326: User is temporarily locked out
        # 64: User is suspended
        disable_twitter_user(bot, user_id, errcode)
    sn = bot.tw_users.get(user_id, {}).get("screen_name", "")
    msg = (
        f"User: {user_id} ({sn})\n"
        f"Failed to tweet: {tweettext}"
    )
    email_error(err, bot, msg)


def load_chatrooms_from_db(txn, bot, always_join):
    """Load database configuration and do work

    Args:
      txn (dbtransaction): database cursor
      bot (basicbot): the running bot instance
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

    # Now we need to load up the syndication
    synd = {}
    txn.execute(
        f"SELECT roomname, endpoint from {bot.name}_room_syndications "
        "WHERE roomname is not null and endpoint is not null"
    )
    for row in txn.fetchall():
        rm = row["roomname"]
        endpoint = row["endpoint"]
        if rm not in synd:
            synd[rm] = []
        synd[rm].append(endpoint)
    bot.syndication = synd
    log.msg(
        f"... loaded {txn.rowcount} room syndications for {len(synd)} rooms"
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
    # Don't waste time by loading up subs from unauthed users
    txn.execute(
        f"select s.user_id, channel from {bot.name}_twitter_subs s "
        "JOIN iembot_twitter_oauth o on (s.user_id = o.user_id) "
        "WHERE s.user_id is not null and s.channel is not null "
        "and o.access_token is not null"
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
        "SELECT user_id, access_token, access_token_secret, screen_name from "
        f"{bot.name}_twitter_oauth WHERE access_token is not null and "
        "access_token_secret is not null and user_id is not null and "
        "screen_name is not null"
    )
    for row in txn.fetchall():
        user_id = row["user_id"]
        twusers[user_id] = {
            "screen_name": row["screen_name"],
            "access_token": row["access_token"],
            "access_token_secret": row["access_token_secret"],
        }
    bot.tw_users = twusers
    log.msg(f"load_twitter_from_db(): {txn.rowcount} oauth tokens found")


def load_chatlog(bot):
    """load up our pickled chatlog"""
    if not os.path.isfile(bot.PICKLEFILE):
        return
    try:
        oldlog = pickle.load(open(bot.PICKLEFILE, "rb"))
        for rm in oldlog:
            bot.chatlog[rm] = oldlog[rm]
            seq = bot.chatlog[rm][-1].seqnum
            if seq is not None and int(seq) > bot.seqnum:
                bot.seqnum = int(seq)
        log.msg(
            f"Loaded CHATLOG pickle: {bot.PICKLEFILE}, seqnum: {bot.seqnum}"
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
    fe.link(link=dict(href=ltxt))
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
