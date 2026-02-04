"""Utility functions for IEMBot"""

import copy
import glob
import os
import pickle
import pwd
import re
import socket
import traceback
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from io import BytesIO
from zoneinfo import ZoneInfo

from pyiem.util import utc
from twisted.internet import reactor
from twisted.mail import smtp
from twisted.python import log
from twisted.words.xish import domish

import iembot
from iembot.types import JabberClient


def build_channel_subs(txn, auth_table: str) -> dict[int : list[str]]:
    """Build the subscriptions based on the given auth table."""
    # First find explicit subscriptions
    txn.execute(
        f"""
        select o.iembot_account_id, channel_name
        from {auth_table} o, iembot_subscriptions s, iembot_channels c
        WHERE o.iembot_account_id = s.iembot_account_id and s.channel_id = c.id
        """
    )
    subs = {}
    count_subs = 0
    for row in txn.fetchall():
        subs.setdefault(row["channel_name"], []).append(
            row["iembot_account_id"]
        )
        count_subs += 1
    # Find subscriptions based on groups
    txn.execute(
        """
        select o.iembot_account_id, channel_name from
        iembot_mastodon_oauth o, iembot_subscriptions s,
        iembot_channel_group_membership m, iembot_channels c
        WHERE o.iembot_account_id = s.iembot_account_id and
        s.group_id = m.group_id and m.channel_id = c.id
        """
    )
    for row in txn.fetchall():
        subs.setdefault(row["channel_name"], []).append(
            row["iembot_account_id"]
        )
        count_subs += 1
    log.msg(f"Built {count_subs} subscriptions from {auth_table}")
    return subs


def channels_room_list(bot: JabberClient, room: str):
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


def channels_room_add(txn, bot: JabberClient, room: str, channel: str):
    """Add a channel subscription to a chatroom

    Args:
        txn (cursor): database transaction
        bot (JabberClient): bot instance
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
            "SELECT id from iembot_channels WHERE channel_name = %s",
            (ch,),
        )
        if txn.rowcount == 0:
            txn.execute(
                "INSERT into iembot_channels(channel_name, description) "
                "VALUES (%s, %s) returning id",
                (ch, ch),
            )
        channel_id = txn.fetchone()["id"]

        # Add to routing table
        bot.routingtable[ch].append(room)
        # Add to database
        txn.execute(
            """
    INSERT into iembot_subscriptions (iembot_account_id, channel_id)
    values (
        (select iembot_account_id from iembot_rooms where roomname = %s),
        %s
    )
    """,
            (room, channel_id),
        )
        bot.send_groupchat(room, f"Subscribed {room} to channel '{ch}'")
    # Send room a listing of channels!
    channels_room_list(bot, room)


def channels_room_del(txn, bot: JabberClient, room: str, channel: str):
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
            """
    DELETE from iembot_subscriptions WHERE
    iembot_account_id = (
    select iembot_account_id from iembot_rooms where roomname = %s) and
    channel_id = (
    select id from iembot_channels where channel_name = %s)
    """,
            (room, ch),
        )
        bot.send_groupchat(room, f"Unsubscribed {room} to channel '{ch}'")
    channels_room_list(bot, room)


def purge_logs(bot: JabberClient):
    """Remove chat logs on a 24 HR basis"""
    log.msg("purge_logs() called...")
    basets = utc() - timedelta(
        days=int(bot.config.get("bot.purge_xmllog_days", 7))
    )
    for fn in glob.glob("logs/xmllog.*"):
        ts = datetime.strptime(fn, "logs/xmllog.%Y_%m_%d")
        ts = ts.replace(tzinfo=ZoneInfo("UTC"))
        if ts < basets:
            log.msg(f"Purging logfile {fn}")
            os.remove(fn)


def email_error(exp, bot: JabberClient, message=""):
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
        if delta < timedelta(hours=1):
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


def load_chatrooms_from_db(txn, bot: JabberClient, always_join: bool = False):
    """Load database configuration and do work

    Args:
      txn (dbtransaction): database cursor
      bot (JabberClient): the running bot instance
      always_join (boolean): do we force joining each room, regardless
    """
    # Load up a list of chatrooms
    txn.execute(
        "SELECT iembot_account_id, roomname from iembot_rooms "
        "WHERE roomname is not null ORDER by roomname ASC"
    )
    oldrooms = list(bot.rooms.keys())
    joined = 0
    xref = {}
    if always_join or "botstalk" not in oldrooms:
        # botstalk is special and should be joined immediately
        presence = domish.Element(("jabber:client", "presence"))
        presence["to"] = f"botstalk@{bot.conference}/{bot.myjid.user}"
        bot.xmlstream.send(presence)

    for i, row in enumerate(txn.fetchall()):
        rm = row["roomname"]
        xref[row["iembot_account_id"]] = rm
        # Setup Room Config Dictionary
        if rm not in bot.rooms:
            bot.rooms[rm] = {
                "occupants": {},
                "joined": False,
            }

        if always_join or rm not in oldrooms:
            presence = domish.Element(("jabber:client", "presence"))
            presence["to"] = f"{rm}@{bot.conference}/{bot.myjid.user}"
            # Some jitter to prevent overloading
            reactor.callLater(i % 30, bot.xmlstream.send, presence)
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

    # Doing an ugly pivot with this
    rt_using_account_ids = build_channel_subs(
        txn,
        "iembot_rooms",
    )
    rt = {}
    for channel, accounts in rt_using_account_ids.items():
        rt[channel] = [xref[account] for account in accounts]
    bot.routingtable = rt


def load_webhooks_from_db(txn, bot: JabberClient):
    """Load twitter config from database"""
    txn.execute(
        "SELECT channel, url from iembot_webhooks "
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


def load_chatlog(bot: JabberClient):
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
      entry(CHAT_LOG_ENTRY): entry

    Returns:
      PyRSSGen.RSSItem
    """
    ts = datetime.strptime(entry.timestamp, "%Y%m%d%H%M%S")
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


def daily_timestamp(bot: JabberClient):
    """Send a timestamp to each room we are in.

    Args:
      bot (JabberClient) instance
    """
    # Make sure we are a bit into the future!
    utc0z = utc() + timedelta(hours=1)
    utc0z = utc0z.replace(hour=0, minute=0, second=0, microsecond=0)
    mess = f"------ {utc0z:%b %-d, %Y} [UTC] ------"
    for rm in bot.rooms:
        bot.send_groupchat(rm, mess)

    tnext = utc0z + timedelta(hours=24)
    delta = (tnext - utc()).total_seconds()
    log.msg(f"Calling daily_timestamp in {delta:.2f} seconds")
    return reactor.callLater(delta, daily_timestamp, bot)
