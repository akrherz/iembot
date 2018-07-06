"""Utility functions for IEMBot"""
import datetime
import re
import os
import socket
import json
import glob
import pickle
from email.mime.text import MIMEText
import traceback
import pwd
from io import BytesIO

import pytz
from oauth import oauth
from twisted.internet import reactor
from twisted.mail import smtp
from twisted.python import log
import twisted.web.error as weberror
from twisted.words.xish import domish
import PyRSS2Gen
from pyiem.reference import TWEET_CHARS


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
    msg = "This room is subscribed to %s channels (%s)" % (
            len(channels), ", ".join(channels))
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
    if channel == '':
        bot.send_groupchat(room, ("Failed to add channel to room "
                                  "subscription, you supplied a "
                                  "blank channel?"))
        return
    # Allow channels to be comma delimited
    for ch in channel.split(","):
        if ch not in bot.routingtable:
            bot.routingtable[ch] = []
        # If we are already subscribed, let em know!
        if room in bot.routingtable[ch]:
            bot.send_groupchat(room, ("Error adding subscription, your "
                                      "room is already subscribed to the"
                                      "'%s' channel") % (ch,))
            continue
        # Add a channels entry for this channel, if one currently does
        # not exist
        txn.execute("""
            SELECT * from """ + bot.name + """_channels
            WHERE id = %s
            """, (ch,))
        if txn.rowcount == 0:
            txn.execute("""
                INSERT into """ + bot.name + """_channels(id, name)
                VALUES (%s, %s)
                """, (ch, ch))

        # Add to routing table
        bot.routingtable[ch].append(room)
        # Add to database
        txn.execute("""
            INSERT into """ + bot.name + """_room_subscriptions
            (roomname, channel) VALUES (%s, %s)
            """, (room, ch))
        bot.send_groupchat(room, ("Subscribed %s to channel '%s'"
                                  ) % (room, ch))
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
    if channel == '':
        bot.send_groupchat(room, "Blank or missing channel")
        return

    for ch in channel.split(","):
        if ch not in bot.routingtable:
            bot.send_groupchat(room, "Unknown channel: '%s'" % (ch,))
            continue

        if room not in bot.routingtable[ch]:
            bot.send_groupchat(room, ("Room not subscribed to channel: '%s'"
                                      ) % (ch,))
            continue

        # Remove from routing table
        bot.routingtable[ch].remove(room)
        # Remove from database
        txn.execute("""
            DELETE from """+bot.name+"""_room_subscriptions WHERE
            roomname = %s and channel = %s
        """, (room, ch))
        bot.send_groupchat(room, ("Unscribed %s to channel '%s'") % (room, ch))
    channels_room_list(bot, room)


def purge_logs(bot):
    """ Remove chat logs on a 24 HR basis """
    log.msg("purge_logs() called...")
    basets = datetime.datetime.utcnow() - datetime.timedelta(
            days=int(bot.config.get('bot.purge_xmllog_days', 7)))
    basets = basets.replace(tzinfo=pytz.utc)
    for fn in glob.glob("logs/xmllog.*"):
        ts = datetime.datetime.strptime(fn, 'logs/xmllog.%Y_%m_%d')
        ts = ts.replace(tzinfo=pytz.utc)
        if ts < basets:
            log.msg("Purging logfile %s" % (fn,))
            os.remove(fn)


def email_error(exp, bot, message=''):
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
        utcnow = datetime.datetime.utcnow()
        bot.email_timestamps.insert(0, utcnow)
        delta = bot.email_timestamps[0] - bot.email_timestamps[-1]
        if len(bot.email_timestamps) < 10:
            return True
        while len(bot.email_timestamps) > 10:
            bot.email_timestamps.pop()

        return delta > datetime.timedelta(hours=1)

    # Logic to prevent email bombs
    if not should_email():
        log.msg("Email threshold exceeded, so no email sent!")
        return False

    msg = MIMEText("""
System          : %s@%s [CWD: %s]
System UTC date : %s
process id      : %s
system load     : %s
Exception       :
%s
%s

Message:
%s""" % (pwd.getpwuid(os.getuid())[0], socket.gethostname(), os.getcwd(),
         datetime.datetime.utcnow(),
         os.getpid(), ' '.join(['%.2f' % (_,) for _ in os.getloadavg()]),
         cstr.read(), exp, message))

    msg['subject'] = '[bot] Traceback -- %s' % (socket.gethostname(),)

    msg['From'] = bot.config.get('bot.email_errors_from', 'root@localhost')
    msg['To'] = bot.config.get('bot.email_errors_to', 'root@localhost')

    df = smtp.sendmail(bot.config.get('bot.smtp_server', 'localhost'),
                       msg["From"], msg["To"], msg)
    df.addErrback(log.err)
    return True


def disable_twitter_user(bot, twituser, errcode=0):
    """Disable the twitter subs for this twituser

    Args:
        twituser (str): The twitter user to disable
        errcode (int): The twitter errorcode
    """
    if twituser.startswith("iembot_"):
        log.msg("Skipping disabling of twitter auth for %s" % (twituser, ))
        return
    bot.tw_access_tokens.pop(twituser, None)
    # Remove entry from the database
    if errcode in [89, ]:
        log.msg(("Removing twitter access token for user: '%s'"
                 ) % (twituser, ))
        df = bot.dbpool.runOperation("""
            DELETE from """ + bot.name + """_twitter_oauth
            WHERE screen_name = %s
            """, (twituser,))
        df.addErrback(log.err)


def tweet_cb(response, bot, twttxt, room, myjid, twituser):
    """
    Called after success going to twitter
    """
    log.msg("tweet_cb() called...")
    if response is None:
        return
    url = "https://twitter.com/%s/status/%s" % (twituser, response)
    html = "Posted twitter message! View it <a href=\"%s\">here</a>." % (
                                            url,)
    plain = "Posted twitter message! %s" % (url,)
    if room is not None:
        bot.send_groupchat(room, plain, html)

    # Log
    df = bot.dbpool.runOperation("""
        INSERT into """ + bot.name + """_social_log(medium, source,
        resource_uri, message, response, response_code)
        values (%s,%s,%s,%s,%s,%s)
        """, ('twitter', myjid, url, twttxt, response, 200))
    df.addErrback(log.err)
    return response


def tweet_eb(err, bot, twttxt, access_token, room, myjid, twituser,
             twtextra, trip):
    """
    Called after error going to twitter
    """
    log.msg("--> tweet_eb called")

    # Make sure we only are trapping API errors
    err.trap(weberror.Error)
    # Don't email duplication errors
    j = {}
    try:
        j = json.loads(err.value.response.decode('utf-8', 'ignore'))
    except Exception as _:
        log.msg("Unable to parse response |%s| as JSON" % (
                                                    err.value.response,))
    if j.get('errors', []):
        errcode = j['errors'][0].get('code', 0)
        if errcode in [130, ]:
            # 130: over capacity
            reactor.callLater(15,  # @UndefinedVariable
                              bot.tweet, twttxt, access_token, room,
                              myjid, twituser, twtextra, trip + 1)
            return
        if errcode in [89, 185, 326]:
            # 89: Expired token, so we shall revoke for now
            # 185: User is over quota
            # 326: User is temporarily locked out
            disable_twitter_user(bot, twituser, errcode)
        if errcode not in [187, ]:
            # 187 duplicate message
            email_error(err, bot, ("Room: %s\nmyjid: %s\ntwituser: %s\n"
                                   "tweet: %s\nError:%s\n"
                                   ) % (room, myjid, twituser, twttxt,
                                        err.value.response))

    log.msg(err.getErrorMessage())
    log.msg(err.value.response)

    msg = "Sorry, an error was encountered with the tweet."
    htmlmsg = "Sorry, an error was encountered with the tweet."
    if err.value.status == b"401":
        msg = "Post to twitter failed. Access token for %s " % (twituser,)
        msg += "is no longer valid."
        htmlmsg = msg + " Please refresh access tokens "
        htmlmsg += ('<a href="https://nwschat.weather.gov/'
                    'nws/twitter.php">here</a>.')
    if room is not None:
        bot.send_groupchat(room, msg, htmlmsg)

    # Log this
    deffered = bot.dbpool.runOperation("""
        INSERT into """ + bot.name + """_social_log(medium, source, message,
        response, response_code, resource_uri) values (%s,%s,%s,%s,%s,%s)
    """, ('twitter', myjid, twttxt, err.value.response,
          int(err.value.status), "https://twitter.com/%s" % (twituser,)))
    deffered.addErrback(log.err)

    # return err.value.response


def fbfail(err, bot, room, myjid, message, fbpage):
    """ We got a failure from facebook API!"""
    log.msg("=== Facebook API Failure ===")
    log.err(err)
    err.trap(weberror.Error)
    j = None
    try:
        j = json.loads(err.value.response)
    except Exception as exp:
        log.err(exp)
    log.msg(err.getErrorMessage())
    log.msg(err.value.response)
    bot.email_error(err, ("FBError room: %s\nmyjid: %s\nmessage: %s\n"
                          "Error:%s"
                          ) % (room, myjid, message, err.value.response))

    msg = 'Posting to facebook failed! Got this message: %s' % (
                        err.getErrorMessage(),)
    if j is not None:
        msg = 'Posting to facebook failed with this message: %s' % (
                        j.get('error', {}).get('message', 'Missing'),)

    if room is not None:
        bot.send_groupchat(room, msg)

    # Log this
    df = bot.dbpool.runOperation("""
        INSERT into nwsbot_social_log(medium, source, message,
        response, response_code, resource_uri) values (%s,%s,%s,%s,%s,%s)
        """, ('facebook', myjid, message, err.value.response,
              err.value.status, fbpage))
    df.addErrback(log.err)


def fbsuccess(response, bot, room, myjid, message):
    """ Got a response from facebook! """
    d = json.loads(response)
    (pageid, postid) = d["id"].split("_")
    url = "http://www.facebook.com/permalink.php?story_fbid=%s&id=%s" % (
                                                        postid, pageid)
    html = "Posted Facebook Message! View <a href=\"%s\">here</a>" % (
                                            url.replace("&", "&amp;"),)
    plain = "Posted Facebook Message! %s" % (url,)
    if room is not None:
        bot.send_groupchat(room, plain, html)

    # Log this
    df = bot.dbpool.runOperation("""
        INSERT into nwsbot_social_log(medium, source, resource_uri,
        message, response, response_code) values (%s,%s,%s,%s,%s,%s)
        """, ('facebook', myjid, url, message, response, 200))
    df.addErrback(log.err)


def load_chatrooms_from_db(txn, bot, always_join):
    """ Load database configuration and do work

    Args:
      txn (dbtransaction): database cursor
      bot (basicbot): the running bot instance
      always_join (boolean): do we force joining each room, regardless
    """
    # Load up the channel keys
    txn.execute("SELECT id, channel_key from %s_channels" % (bot.name,))
    for row in txn.fetchall():
        bot.channelkeys[row['channel_key']] = row['id']

    # Load up the routingtable for bot products
    rt = {}
    txn.execute("""
        SELECT roomname, channel from %s_room_subscriptions
    """ % (bot.name,))
    rooms = []
    for row in txn.fetchall():
        rm = row['roomname']
        channel = row['channel']
        if channel not in rt:
            rt[channel] = []
        rt[channel].append(rm)
        if rm not in rooms:
            rooms.append(rm)
    bot.routingtable = rt
    log.msg(("... loaded %s channel subscriptions for %s rooms"
             ) % (txn.rowcount, len(rooms)))

    # Now we need to load up the syndication
    synd = {}
    txn.execute("""
        SELECT roomname, endpoint from %s_room_syndications
    """ % (bot.name,))
    for row in txn.fetchall():
        rm = row['roomname']
        endpoint = row['endpoint']
        if rm not in synd:
            synd[rm] = []
        synd[rm].append(endpoint)
    bot.syndication = synd
    log.msg(("... loaded %s room syndications for %s rooms"
             ) % (txn.rowcount, len(synd)))

    # Load up a list of chatrooms
    txn.execute("""
        SELECT roomname, fbpage, twitter from %s_rooms ORDER by roomname ASC
    """ % (bot.name,))
    oldrooms = list(bot.rooms.keys())
    joined = 0
    for i, row in enumerate(txn.fetchall()):
        rm = row['roomname']
        # Setup Room Config Dictionary
        if rm not in bot.rooms:
            bot.rooms[rm] = {'fbpage': None, 'twitter': None,
                             'occupants': {}, 'joined': False}
        bot.rooms[rm]['fbpage'] = row['fbpage']
        bot.rooms[rm]['twitter'] = row['twitter']

        if always_join or rm not in oldrooms:
            presence = domish.Element(('jabber:client', 'presence'))
            presence['to'] = "%s@%s/%s" % (rm, bot.conference,
                                           bot.myjid.user)
            reactor.callLater(i % 30, bot.xmlstream.send, presence)
            joined += 1
        if rm in oldrooms:
            oldrooms.remove(rm)

    # Check old rooms for any rooms we need to vacate!
    for rm in oldrooms:
        presence = domish.Element(('jabber:client', 'presence'))
        presence['to'] = "%s@%s/%s" % (rm, bot.conference, bot.myjid.user)
        presence['type'] = 'unavailable'
        bot.xmlstream.send(presence)

        del bot.rooms[rm]
    log.msg(("... loaded %s chatrooms, joined %s of them, left %s of them"
             ) % (txn.rowcount, joined, len(oldrooms)))


def load_twitter_from_db(txn, bot):
    """ Load twitter config from database """
    txn.execute("""
        SELECT screen_name, channel from """+bot.name+"""_twitter_subs
        """)
    twrt = {}
    for row in txn.fetchall():
        sn = row['screen_name']
        channel = row['channel']
        if sn == '' or channel == '':
            continue
        if channel not in twrt:
            twrt[channel] = []
        twrt[channel].append(sn)
    bot.tw_routingtable = twrt
    log.msg("load_twitter_from_db(): %s subs found" % (txn.rowcount,))

    twtokens = {}
    txn.execute("""
        SELECT screen_name, access_token, access_token_secret
        from """+bot.name+"""_twitter_oauth
        """)
    for row in txn.fetchall():
        sn = row['screen_name']
        at = row['access_token']
        ats = row['access_token_secret']
        twtokens[sn] = oauth.OAuthToken(at, ats)
    bot.tw_access_tokens = twtokens
    log.msg("load_twitter_from_db(): %s oauth tokens found" % (txn.rowcount,))


def load_facebook_from_db(txn, bot):
    """ Load facebook config from database """
    txn.execute("""
        SELECT fbpid, channel from """+bot.name+"""_fb_subscriptions
        """)
    fbrt = {}
    for row in txn.fetchall():
        page = row['fbpid']
        channel = row['channel']
        if channel not in fbrt:
            fbrt[channel] = []
        fbrt[channel].append(page)
    bot.fb_routingtable = fbrt

    txn.execute("""
        SELECT fbpid, access_token from """+bot.name+"""_fb_access_tokens
        """)

    for row in txn.fetchall():
        page = row['fbpid']
        at = row['access_token']
        bot.fb_access_tokens[page] = at


def load_chatlog(bot):
    """load up our pickled chatlog"""
    if not os.path.isfile(bot.PICKLEFILE):
        return
    try:
        oldlog = pickle.load(open(bot.PICKLEFILE, 'rb'))
        for rm in oldlog:
            bot.chatlog[rm] = oldlog[rm]
            seq = bot.chatlog[rm][-1].seqnum
            if seq is not None and int(seq) > bot.seqnum:
                bot.seqnum = int(seq)
        log.msg("Loaded CHATLOG pickle: %s, seqnum: %s" % (bot.PICKLEFILE,
                                                           bot.seqnum))
    except Exception as exp:
        log.err(exp)


def safe_twitter_text(text):
    """ Attempt to rip apart a message that is too long!
    To be safe, the URL is counted as 24 chars
    """
    # Convert two or more spaces into one
    text = ' '.join(text.split())
    # If we are already below TWEET_CHARS, we don't have any more work to do...
    if len(text) < TWEET_CHARS and text.find("http") == -1:
        return text
    chars = 0
    words = text.split()
    # URLs only count as 25 chars, so implement better accounting
    for word in words:
        if word.startswith('http'):
            chars += 25
        else:
            chars += (len(word) + 1)
    if chars < TWEET_CHARS:
        return text
    urls = re.findall(r'https?://[^\s]+', text)
    if len(urls) == 1:
        text2 = text.replace(urls[0], '')
        sections = re.findall('(.*) for (.*)( till [0-9A-Z].*)', text2)
        if len(sections) == 1:
            text = "%s%s%s" % (sections[0][0], sections[0][2], urls[0])
            if len(text) > TWEET_CHARS:
                sz = TWEET_CHARS - 26 - len(sections[0][2])
                text = "%s%s%s" % (sections[0][0][:sz], sections[0][2],
                                   urls[0])
            return text
        if len(text) > TWEET_CHARS:
            # 25 for URL, three dots and space for 29
            return "%s... %s" % (text2[:(TWEET_CHARS - 29)], urls[0])
    if chars > TWEET_CHARS:
        if words[-1].startswith('http'):
            i = -2
            while len(' '.join(words[:i])) > (TWEET_CHARS - 3 - 25):
                i -= 1
            return ' '.join(words[:i]) + '... ' + words[-1]
    return text[:TWEET_CHARS]


def chatlog2rssitem(timestamp, txt):
    """Convert a txt Jabber room message to a RSS feed entry

    Args:
      timestamp(str): A string formatted timestamp in the form YYYYMMDDHHMI
      txt(str): The text variant of the chatroom message that was set.

    Returns:
      PyRSSGen.RSSItem
    """
    ts = datetime.datetime.strptime(timestamp, "%Y%m%d%H%M%S")
    m = re.search(r"https?://", txt)
    urlpos = -1
    if m:
        urlpos = m.start()
    else:
        txt += "  "
    ltxt = txt[urlpos:].replace("&amp;", "&").strip()
    if ltxt == "":
        ltxt = "https://mesonet.agron.iastate.edu/projects/iembot/"
    return PyRSS2Gen.RSSItem(title=txt[:urlpos].strip(),
                             link=ltxt,
                             guid=ltxt,
                             pubDate=ts.strftime("%a, %d %b %Y %H:%M:%S GMT"))
