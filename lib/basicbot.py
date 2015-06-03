""" Basic iembot/nwsbot implementation, upstream for this code is
    on github: https://github.com/akrherz/iembot
"""

from twisted.words.xish import domish
from twisted.words.xish import xpath
from twisted.words.protocols.jabber import jid, client
from twisted.words.xish.xmlstream import STREAM_END_EVENT
from twisted.internet import reactor
from twisted.application import internet
from twisted.python import log
from twisted.python.logfile import DailyLogFile
import twisted.web.error as weberror
from twisted.internet.task import LoopingCall
from twisted.mail import smtp
from twisted.web import client as webclient

from oauth import oauth

import datetime
import pytz
import json
import traceback
from email.MIMEText import MIMEText
import StringIO
import random
import os
import pwd
import urllib
import socket
import locale
import re
import glob
from twittytwister import twitter
locale.setlocale(locale.LC_ALL, 'en_US')

PRESENCE_MUC_ITEM = (
    "/presence/x[@xmlns='http://jabber.org/protocol/muc#user']/item")


def load_chatrooms_from_db(txn, bot, always_join):
    """ Load database configuration and do work

    Args:
      txn (dbtransaction): database cursor
      bot (basicbot): the running bot instance
      always_join (boolean): do we force joining each room, regardless
    """
    # Load up the channel keys
    txn.execute("SELECT id, channel_key from %s_channels" % (bot.name,))
    for row in txn:
        bot.channelkeys[row['channel_key']] = row['id']

    # Load up the routingtable for bot products
    rt = {}
    txn.execute("""
        SELECT roomname, channel from %s_room_subscriptions
    """ % (bot.name,))
    for row in txn:
        rm = row['roomname']
        channel = row['channel']
        if channel not in rt:
            rt[channel] = []
        rt[channel].append(rm)
    bot.routingtable = rt
    log.msg(("... loaded %s channel subscriptions for %s rooms"
             ) % (txn.rowcount, len(rt)))

    # Now we need to load up the syndication
    synd = {}
    txn.execute("""
        SELECT roomname, endpoint from %s_room_syndications
    """ % (bot.name,))
    for row in txn:
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
    oldrooms = bot.rooms.keys()
    joined = 0
    for i, row in enumerate(txn):
        rm = row['roomname']
        # Setup Room Config Dictionary
        if rm not in bot.rooms:
            bot.rooms[rm] = {'fbpage': None, 'twitter': None,
                             'occupants': {}}
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

        del(bot.rooms[rm])
    log.msg(("... loaded %s chatrooms, joined %s of them, left %s of them"
             ) % (txn.rowcount, joined, len(oldrooms)))


def load_twitter_from_db(txn, bot):
    """ Load twitter config from database """
    txn.execute("SELECT screen_name, channel from %s_twitter_subs" % (
                                                                bot.name,))
    twrt = {}
    for row in txn:
        sn = row['screen_name']
        channel = row['channel']
        if sn == '' or channel == '':
            continue
        if not twrt.has_key(channel):
            twrt[channel] = []
        twrt[channel].append( sn )
    bot.tw_routingtable = twrt
    log.msg("load_twitter_from_db(): %s subs found" % (txn.rowcount,))
        
    txn.execute("""SELECT screen_name, access_token, access_token_secret 
        from %s_twitter_oauth""" % (bot.name,))
    for row in txn:
        sn = row['screen_name']
        at = row['access_token']
        ats = row['access_token_secret']
        bot.tw_access_tokens[sn] =  oauth.OAuthToken(at,ats)
    log.msg("load_twitter_from_db(): %s oauth tokens found" % (txn.rowcount,))

def load_facebook_from_db(txn, bot):
    """ Load facebook config from database """
    txn.execute("SELECT fbpid, channel from %s_fb_subscriptions" % (bot.name,))
    fbrt = {}
    for row in txn:
        page = row['fbpid']
        channel = row['channel']
        if not fbrt.has_key(channel):
            fbrt[channel] = []
        fbrt[channel].append( page )
    bot.fb_routingtable = fbrt
        
    txn.execute("SELECT fbpid, access_token from %s_fb_access_tokens" % (bot.name,))
    
    for row in txn:
        page = row['fbpid']
        at = row['access_token']
        bot.fb_access_tokens[page] =  at


def safe_twitter_text(text):
    """ Attempt to rip apart a message that is too long! 
    To be safe, the URL is counted as 24 chars
    """
    # Convert two or more spaces into one
    text = ' '.join( text.split() )
    # If we are already below 140, we don't have any more work to do...
    if len(text) < 140:
        return text
    chars = 0
    for word in text.split():
        if word.find('http') == 0:
            chars += 25
        else:
            chars += (len(word) + 1 )
    if chars < 140:
        return text

    urls = re.findall('https?://[^\s]+', text)
    if len(urls) == 1:
        text2 = text.replace(urls[0], '')
        sections = re.findall('(.*) for (.*)( till [0-9A-Z].*)', text2)
        if len(sections) == 1:
            text = "%s%s%s" % (sections[0][0], sections[0][2], urls[0])
            if len(text) > 140:
                sz = 112 - len(sections[0][2])
                text = "%s%s%s" % (sections[0][0][:sz], sections[0][2], urls[0])
            return text
        if len(text) > 140:
            return "%s... %s" % (text2[:109], urls[0])
    return text[:140]


class basicbot:
    """ Here lies the Jabber Bot """

    def __init__(self, name, dbpool):
        """ Constructor """
        self.startup_time = datetime.datetime.utcnow().replace(
                                                tzinfo=pytz.timezone("UTC"))
        self.name = name
        self.dbpool = dbpool
        self.config = {}
        self.IQ = {}
        self.rooms = {}
        self.chatlog = {}
        self.seqnum = 0
        self.routingtable = {}
        self.tw_access_tokens = {}
        self.tw_routingtable = {}
        self.fb_access_tokens = {}
        self.fb_routingtable = {}
        self.has_football = True
        self.xmlstream = None
        self.firstlogin = False
        self.channelkeys = {}
        self.syndication = {}
        self.xmllog = DailyLogFile('xmllog', 'logs/')
        self.myjid = None
        self.ingestjid = None
        self.conference = None
        self.email_timestamps = []
        self.fortunes = open('startrek', 'r').read().split("\n%\n")
        self.twitter_oauth_consumer = None
        self.logins = 0

        lc2 = LoopingCall( self.purge_logs )
        lc2.start(60*60*24)

    def on_firstlogin(self):
        """ callbacked when we are first logged in """
        pass

    def authd(self, xmlstream):
        """ callback when we are logged into the server! """
        msg = "Logged into jabber server as %s" % (self.myjid,)
        self.email_error(None, msg)
        if not self.firstlogin:
            self.compute_daily_caller()
            self.on_firstlogin()
            self.firstlogin = True
        
        # Resets associated with the previous login session, perhaps
        self.rooms = {}
        self.IQ = {}
        
        # Assignment of xmlstream!
        self.xmlstream = xmlstream
        self.xmlstream.rawDataInFn = self.rawDataInFn
        self.xmlstream.rawDataOutFn = self.rawDataOutFn

        self.xmlstream.addObserver('/message',  self.message_processor)
        self.xmlstream.addObserver('/iq',  self.iq_processor)
        self.xmlstream.addObserver('/presence/x/item',  self.presence_processor)
        
        self.load_twitter()
        self.send_presence()
        self.load_chatrooms(True)
        self.load_facebook()
        
        lc = LoopingCall(self.housekeeping)
        lc.start(60)
        self.xmlstream.addObserver(STREAM_END_EVENT, lambda _: lc.stop())

    def next_seqnum( self ):
        """
        Simple tool to generate a sequence number for message logging
        """
        self.seqnum += 1
        return self.seqnum

    def load_chatrooms(self, always_join):
        """
        Load up the chatrooms and subscriptions from the database!, I also
        support getting called at a later date for any changes
        """
        log.msg("load_chatrooms() called...")
        df = self.dbpool.runInteraction(load_chatrooms_from_db, self, 
                                            always_join)
        df.addErrback( self.email_error, "load_chatrooms() failure" )
        
    def load_twitter(self):
        ''' Load the twitter subscriptions and access tokens '''
        log.msg("load_twitter() called...")
        df = self.dbpool.runInteraction(load_twitter_from_db, self)
        df.addErrback( self.email_error, "load_twitter() failure" )

    def load_facebook(self):
        """
        Load up the facebook configuration page/channel subscriptions
        """
        log.msg("load_facebook() called...")
        df = self.dbpool.runInteraction(load_facebook_from_db, self)
        df.addErrback( self.email_error )

    def tweet_cb(self, response, twttxt, room, myjid, twituser):
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
            self.send_groupchat(room, plain, html)

        # Log
        df = self.dbpool.runOperation("""
            INSERT into """ + self.name + """_social_log(medium, source,
            resource_uri, message, response, response_code)
            values (%s,%s,%s,%s,%s,%s)
            """, ('twitter', myjid, url, twttxt, response, 200))
        df.addErrback(log.err)
        return response

    def tweet_eb(self, err, twttxt, room, myjid, twituser):
        """
        Called after error going to twitter
        """
        log.msg("====== Twitter Error! ======")
        log.err(err)

        # Make sure we only are trapping API errors
        err.trap( weberror.Error )
        # Don't email duplication errors
        j = {}
        try:
            j = json.loads(err.value.response)
        except:
            log.msg("Unable to parse response |%s| as JSON" % (
                                                        err.value.response,))
        if (len(j.get('errors', [])) > 0 and 
            j['errors'][0].get('code', 0) !=  187):
            self.email_error(err, ("Room: %s\nmyjid: %s\ntwituser: %s\n"
                                   +"tweet: %s\nError:%s\n") % (
                                room, myjid, twituser, twttxt,
                                err.value.response))

        log.msg(err.getErrorMessage())
        log.msg(err.value.response)

        msg = "Sorry, an error was encountered with the tweet."
        htmlmsg = "Sorry, an error was encountered with the tweet."
        if err.value.status == "401":
            msg = "Post to twitter failed. Access token for %s " % (twituser,)
            msg += "is no longer valid."
            htmlmsg = msg + " Please refresh access tokens "
            htmlmsg += "<a href='https://nwschat.weather.gov/nws/twitter.php'>here</a>."
        if room is not None:
            self.send_groupchat(room, msg, htmlmsg)

        # Log this
        deffered = self.dbpool.runOperation("""
            INSERT into """+self.name+"""_social_log(medium, source, message,
            response, response_code, resource_uri) values (%s,%s,%s,%s,%s,%s)
            """, ('twitter', myjid, twttxt, err.value.response, 
                 err.value.status, "https://twitter.com/%s" % (twituser,) ))
        deffered.addErrback(log.err)

        # return err.value.response

    def email_error(self, exp, message=''):
        """
        Something to email errors when something fails
        """
        # Always log a message about our fun
        cstr = StringIO.StringIO()
        
        if exp is not None:
            traceback.print_exc(file=cstr)
            cstr.seek(0)
            if isinstance(exp, Exception):
                log.err( exp )
            else:
                log.msg( exp )
        log.msg( message )

        
        def should_email():
            utcnow = datetime.datetime.utcnow()
            self.email_timestamps.insert(0, utcnow )
            delta = self.email_timestamps[0] - self.email_timestamps[-1]
            if len(self.email_timestamps) < 10:
                return True
            while len(self.email_timestamps) > 10:
                self.email_timestamps.pop()

            return (delta > datetime.timedelta(hours=1))

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

        # TODO: add his local name
        msg['subject'] = '[bot] Traceback -- %s' % (socket.gethostname(),)

        msg['From'] = self.config['bot.email_errors_from']
        msg['To'] = self.config['bot.email_errors_to']

        df = smtp.sendmail(self.config['bot.smtp_server'], msg["From"], msg["To"], 
                           msg)
        df.addErrback( log.err )
        return True

    def check_for_football(self):
        """ Logic to check if we have the football or not, this should
        be over-ridden """
        self.has_football = True

    def fire_client_with_config(self, res, serviceCollection):
        """ Calledback once bot has loaded its database configuration """
        log.msg("fire_client_with_config() called ...")

        for row in res:
            self.config[ row['propname'] ] = row['propvalue']
        
        self.myjid = jid.JID("%s@%s/twisted_words" % (
                                                self.config["bot.username"],
                                                self.config["bot.xmppdomain"]))
        self.ingestjid = jid.JID("%s@%s" % (
                                            self.config["bot.ingest_username"],
                                            self.config["bot.xmppdomain"]))
        self.conference = self.config['bot.mucservice']

        self.twitter_oauth_consumer = oauth.OAuthConsumer(
                            self.config['bot.twitter.consumerkey'],
                            self.config['bot.twitter.consumersecret'])

        factory = client.basicClientFactory(self.myjid, 
                                            self.config['bot.password'])
        # Limit reconnection delay to 60 seconds
        factory.maxDelay = 60
        factory.addBootstrap('//event/stream/authd', self.authd)

        i = internet.TCPClient(self.config['bot.connecthost'], 5222, 
                               factory)
        i.setServiceParent(serviceCollection)

    def get_fortune(self):
        """ Get a random value from the array """
        offset = int((len(self.fortunes)-1) * random.random())
        return " ".join( self.fortunes[offset].replace("\n","").split() )

    def failure(self, f):
        log.err( f )

    def debug(self, elem):
        log.msg( elem )

    def rawDataInFn(self, data):
        self.xmllog.write("%s RECV %s\n" % (
                    datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), 
                                            data))

    def rawDataOutFn(self, data):
        self.xmllog.write("%s SEND %s\n" % (
                    datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                                            data))

    def purge_logs(self):
        """ Remove chat logs on a 24 HR basis """
        log.msg("purge_logs() called...")
        basets = datetime.datetime.utcnow() - datetime.timedelta(
                days=int(self.config.get('bot.purge_xmllog_days', 7)))
        basets = basets.replace(tzinfo=pytz.timezone("UTC"))
        for fn in glob.glob("logs/xmllog.*"):
            ts = datetime.datetime.strptime(fn,'logs/xmllog.%Y_%m_%d')
            ts = ts.replace(tzinfo=pytz.timezone("UTC"))
            if ts < basets:
                log.msg("Purging logfile %s" % (fn,))
                os.remove(fn)

    def housekeeping(self):
        """ 
        This gets exec'd every minute to keep up after ourselves 
        1. XMPP Server Ping
        2. Check if we have the football
        3. Update presence
        """
        gmtnow = datetime.datetime.utcnow()
        self.check_for_football()

        if len( self.IQ.keys() ) > 0:
            log.msg("ERROR: missing IQs %s" % (self.IQ.keys(),))
        if len( self.IQ.keys() ) > 5:
            self.IQ = {}
            self.email_error("Logging out of Chat!", "IQ error limit reached...")
            if self.xmlstream is not None:
                self.xmlstream.sendFooter()
                self.xmlstream.connectionLost('BAD')
            return
        ping = domish.Element((None,'iq'))
        ping['to'] = self.myjid.host
        ping['type'] = 'get'
        pingid = "%s" % (gmtnow.strftime("%Y%m%d%H%M"), )
        ping['id'] = pingid
        ping.addChild( domish.Element(('urn:xmpp:ping', 'ping')) )
        if self.xmlstream is not None:
            self.IQ[ pingid ] = 1
            self.xmlstream.send( ping )
            if gmtnow.minute % 10 == 0:
                self.send_presence()
                # Reset our service guard
                self.logins = 1


    def send_privatechat(self, to, mess, htmlstr=None):
        """
        Helper method to send private messages

        @param to: String jabber ID to send the message too
        @param mess: String plain text version to send
        @param html: Optional String html version 
        """
        message = domish.Element(('jabber:client','message'))
        if to.find("@") == -1: # base username, add domain
            to = "%s@%s" % (to, self.config["bot.xmppdomain"])
        message['to'] = to
        message['type'] = "chat"
        message.addElement('body', None, mess)
        html = message.addElement('html', 'http://jabber.org/protocol/xhtml-im')
        body = html.addElement('body', 'http://www.w3.org/1999/xhtml')
        if htmlstr:
            body.addRawXml( htmlstr )
        else:
            body.addContent( mess )
        self.xmlstream.send(message)

    def send_groupchat(self, room, plain, htmlstr=None, secondtrip=False):
        """
        Helper method to send messages to chatrooms

        @param room: String name of the chatroom name
        @param plain: Plain Text variant
        @param html:  HTML version of what message to send, optional
        """
        message = domish.Element(('jabber:client', 'message'))
        message['to'] = "%s@%s" % (room, self.conference)
        message['type'] = "groupchat"
        message.addElement('body', None, plain)
        html = message.addElement('html',
                                  'http://jabber.org/protocol/xhtml-im')
        body = html.addElement('body',
                               'http://www.w3.org/1999/xhtml')
        if htmlstr:
            body.addRawXml(htmlstr)
        else:
            body.addContent(plain)
        self.send_groupchat_elem(message)

    def send_groupchat_elem(self, elem, to=None, secondtrip=False):
        """ Wrapper for sending groupchat elements """
        if to is not None:
            elem['to'] = to
        room = jid.JID(elem['to']).user
        if room not in self.rooms:
            self.email_error(("Attempted to send message to room [%s] "
                              "we have not joined...") % (room,), elem)
            return
        if self.myjid.user not in self.rooms[room]['occupants']:
            if secondtrip:
                log.msg("ABORT of send to room: %s, msg: %s, not in room" % (
                                                        room, elem))
                return
            log.msg("delaying send to room: %s, not in room yet" % (room,))
            # Need to prevent elem['to'] object overwriting
            reactor.callLater(300, self.send_groupchat_elem, elem, elem['to'],
                              True)
            return
        self.xmlstream.send(elem)

    def send_presence(self):
        """
        Set a presence for my login
        """
        presence = domish.Element(('jabber:client','presence'))
        msg = "Booted: %s Updated: %s UTC, Rooms: %s, Messages: %s" % (
                                        self.startup_time.strftime("%d %b"),
                                        datetime.datetime.utcnow().strftime("%H%M"),
                                        len(self.rooms), 
                                        locale.format("%d", self.seqnum, grouping=True) )
        presence.addElement('status').addContent(msg)
        if self.xmlstream is not None:
            self.xmlstream.send(presence)

    def tweet(self, twttxt, access_token, room=None, myjid=None, twituser=None,
              twtextra=dict()):
        """
        Tweet a message 
        """
        twt = twitter.Twitter(consumer=self.twitter_oauth_consumer, 
                              token=access_token)
        twttxt = safe_twitter_text(twttxt)
        df = twt.update(twttxt, None, twtextra)
        df.addCallback(self.tweet_cb, twttxt, room, myjid, twituser)
        df.addErrback(self.tweet_eb, twttxt, room, myjid, twituser)
        df.addErrback(log.err)

        return df

    def compute_daily_caller(self):
        log.msg("compute_daily_caller() called...")
        # Figure out when to spam all rooms with a timestamp
        utc = datetime.datetime.utcnow() + datetime.timedelta(days=1)
        tnext =  utc.replace(hour=0,minute=0,second=0)
        log.msg('Initial Calling daily_timestamp in %s seconds' % (
                            (tnext - datetime.datetime.utcnow()).seconds, ))
        reactor.callLater((tnext - datetime.datetime.utcnow()).seconds, 
                          self.daily_timestamp)

    def daily_timestamp(self):
        """  Send date each 00:00 UTC Day, helps to break apart logs """
        utcnow = (datetime.datetime.utcnow()).replace(
                                            tzinfo=pytz.timezone("UTC"))
        # Make sure we are a bit into the future!
        utc0z = utcnow + datetime.timedelta(hours=1)
        utc0z = utc0z.replace(hour=0, minute=0, second=0, microsecond=0)
        mess = "------ %s [UTC] ------" % (utc0z.strftime("%b %-d, %Y"),)
        for rm in self.rooms.keys():
            self.send_groupchat(rm, mess)

        tnext = utc0z + datetime.timedelta(hours=24)
        delta = (tnext - utcnow).days * 86400. + (tnext - utcnow).seconds
        log.msg('Calling daily_timestamp in %.2f seconds' % (delta, ))
        reactor.callLater(delta, self.daily_timestamp)

    def presence_processor(self, elem):
        """Process the presence stanza

        The bot process keeps track of room occupants and their affiliations,
        roles so to provide ACLs for room admin activities.

        Args:
          elem (domish.Element): stanza

<presence xmlns='jabber:client' to='nwsbot@laptop.local/twisted_words'
    from='dmxchat@conference.laptop.local/nws-daryl.herzmann'>
    <priority>1</priority>
    <c xmlns='http://jabber.org/protocol/caps' node='http://pidgin.im/'
        ver='AcN1/PEN8nq7AHD+9jpxMV4U6YM=' ext='voice-v1 camera-v1 video-v1'
        hash='sha-1'/>
    <x xmlns='vcard-temp:x:update'><photo/></x>
    <x xmlns='http://jabber.org/protocol/muc#user'>
        <item affiliation='owner' jid='nws-mortal@laptop.local/laptop'
        role='moderator'/>
    </x>
</presence>
        """
        # log.msg("presence_processor() called")
        items = xpath.queryForNodes(PRESENCE_MUC_ITEM, elem)
        if items is None:
            return

        _room = jid.JID(elem["from"]).user
        _handle = jid.JID(elem["from"]).resource
        for item in items:
            affiliation = item.getAttribute('affiliation')
            _jid = item.getAttribute('jid')
            role = item.getAttribute('role')
            self.rooms[_room]['occupants'][_handle] = {
                  'jid': _jid,
                  'affiliation': affiliation,
                  'role': role}

    def route_message(self, elem, source='nwsbot_ingest'):
        """
        Route XML messages to the appropriate room

        @param elem: domish.Element stanza to process
        @param source optional source of this message, assume nwsbot_ingest
        """
        # Go look for body to see routing info! 
        # Get the body string
        if not elem.body:
            log.msg("Unprocessable message:")
            log.msg(elem )
            return

        bstring = unicode(elem.body)
        if not bstring:
            log.msg("Nothing found in body?")
            log.msg( elem )
            return

        # Send message to botstalk, unmodified
        elem['type'] = "groupchat"
        elem['to'] = "botstalk@%s" % (self.conference,)
        self.send_groupchat_elem( elem )

        if elem.x and elem.x.hasAttribute("channels"):
            channels = elem.x['channels'].split(",")
        else:
            # The body string contains
            (channel, meat) = bstring.split(":", 1)
            channels = [channel,]
            # Send to chatroom, clip body of channel notation
            elem.body.children[0] = meat
            
        # Look for custom twitter formatting
        twt = bstring
        if elem.x and elem.x.hasAttribute("twitter"):
            twt = elem.x['twitter']

        # Route to subscription channels
        alertedRooms = []
        for channel in channels:
            if self.routingtable.has_key(channel):
                for room in self.routingtable[channel]:
                    if room in alertedRooms:
                        continue
                    alertedRooms.append( room )
                    elem['to'] = "%s@%s" % (room, self.conference)
                    if elem.x and elem.x.hasAttribute("facebookonly"):
                        continue
                    self.send_groupchat_elem(elem)
            else:
                self.routingtable[channel] = []
        # Facebook Routing
        alertedPages = []
        alertedTwitter = []
        for channel in channels:
            if channel == '':
                continue
            if self.tw_routingtable.has_key(channel):
                log.msg('Twitter wants channel: %s' % (channel,))
                for page in self.tw_routingtable[channel]:
                    if page in alertedTwitter:
                        continue
                    log.msg('Twitter Page: %s wants channel: %s' % (page,
                                                                    channel))
                    alertedTwitter.append( page )
                    if elem.x and elem.x.hasAttribute("nwschatonly"):
                        continue
                    if self.tw_access_tokens.has_key(page):
                        log.msg('Channel: [%s] Page: [%s] Tweet: [%s]' % (
                                                        channel, page, twt))
                        if self.has_football:
                            twtextra = {}
                            if (elem.x and elem.x.hasAttribute("lat") and 
                                elem.x.hasAttribute("long")):
                                twtextra['lat'] = elem.x['lat']
                                twtextra['long'] = elem.x['long']
                            self.tweet(twt, self.tw_access_tokens[page],
                                       twituser=page, myjid=source,
                                       twtextra=twtextra)
                            # ASSUME we joined twitter room already
                            self.send_groupchat('twitter', twt)
                        else:
                            log.msg("No Twitter since we have no football")
                            self.send_groupchat('twitter', "NO FOOTBALL %s" % (twt,) )

            if self.fb_routingtable.has_key(channel):
                log.msg('Facebook wants channel: %s' % (channel,))
                for page in self.fb_routingtable[channel]:
                    log.msg('Facebook Page: %s wants channel: %s' % (page,
                                                                    channel))
                    if page in alertedPages:
                        continue
                    alertedPages.append( page )
                    if elem.x and elem.x.hasAttribute("nwschatonly"):
                        continue
                    self.send_fb_fanpage(elem, page)

    def fbfail(self, err, room, myjid, message, fbpage):
        """ We got a failure from facebook API!"""
        log.msg("=== Facebook API Failure ===")
        log.err( err )
        err.trap( weberror.Error )
        j = None
        try:
            j = json.loads(err.value.response)
        except:
            pass
        log.msg( err.getErrorMessage() )
        log.msg( err.value.response )
        self.email_error(err, "FBError room: %s\nmyjid: %s\nmessage: %s\nError:%s" % (
                        room, myjid, message, err.value.response))
    
        msg = 'Posting to facebook failed! Got this message: %s' % ( 
                            err.getErrorMessage(),)
        if j is not None:
            msg = 'Posting to facebook failed with this message: %s' % (
                            j.get('error', {}).get('message', 'Missing'),)
    
        if room is not None:
            self.send_groupchat(room, msg)

        # Log this
        df = self.dbpool.runOperation(""" 
            INSERT into nwsbot_social_log(medium, source, message,
            response, response_code, resource_uri) values (%s,%s,%s,%s,%s,%s)
            """, ('facebook', myjid, message, err.value.response, 
                 err.value.status, fbpage ))
        df.addErrback( log.err )
        
    def fbsuccess(self, response, room, myjid, message):
        """ Got a response from facebook! """
        d = json.loads(response)
        (pageid, postid) = d["id"].split("_")
        url = "http://www.facebook.com/permalink.php?story_fbid=%s&id=%s" % (
                                                            postid, pageid)
        html = "Posted Facebook Message! View <a href=\"%s\">here</a>" % (
                                                url.replace("&", "&amp;"),)
        plain = "Posted Facebook Message! %s" % (url,)
        if room is not None:
            self.send_groupchat(room, plain, html)
        
        # Log this
        df = self.dbpool.runOperation(""" 
            INSERT into nwsbot_social_log(medium, source, resource_uri, message,
            response, response_code) values (%s,%s,%s,%s,%s,%s)
            """, ('facebook', myjid, url, message, response, 200))
        df.addErrback( log.err )
 
    def iq_processor(self, elem):
        """
        Something to process IQ messages
        """
        if elem.hasAttribute("id") and self.IQ.has_key( elem["id"] ):
            del( self.IQ[ elem["id"] ] )
    
    def processMessagePC(self, elem):
        """
        Process a XML stanza that is a private chat

        @param elem: domish.Element stanza to process
        """
        _from = jid.JID( elem["from"] )
        # Don't react to broadcast messages
        if _from.user is None:
            return

        # Intercept private messages via a chatroom, can't do that :)
        if _from.host == self.conference:
            self.convert_to_privatechat( _from )
            return

        if _from.userhost() == self.ingestjid.userhost():
            self.route_message(elem)
        else:
            self.talkWithUser(elem)

    def send_help_message(self, user):
        """
        Send a user a help message about what I can do
        """
        msg = """Hi, I am %s.  You can try talking directly with me.
I currently do not support any commands, sorry.""" % (self.myjid.user,)
        htmlmsg = msg.replace("\n","<br />").replace(self.myjid.user, 
                 "<a href=\"https://%s/%sfaq.php\">%s</a>" % (self.myjid.host, 
                                            self.myjid.user, self.myjid.user) )
        self.send_privatechat(user, msg, htmlmsg)

    def convert_to_privatechat(self, myjid):
        """
        The bot can't handle private chats via a MUC, readdress to a
        private chat

        @param myjid: MUC chat jabber ID to reroute
        """
        _handle = myjid.resource
        _room = myjid.user
        if (not self.rooms[_room]['occupants'].has_key(_handle)):
            return
        realjid = self.rooms[_room]['occupants'][_handle]["jid"]

        self.send_help_message( realjid )

        message = domish.Element(('jabber:client','message'))
        message['to'] = myjid.full()
        message['type'] = "chat"
        message.addElement('body', None, "I can't help you here, please chat \
with me outside of a groupchat.  I have initated such a chat for you.")
        self.xmlstream.send(message)

    def processMessage(self, elem):
        """
        This is our business method, figure out if this chat is a
        private message or a group one
        """
        if elem.hasAttribute("type") and elem["type"] == "groupchat":
            self.processMessageGC(elem)
        elif elem.hasAttribute("type") and elem["type"] == "error":
            self.email_error("Got Error Stanza?", elem.toXml())
        else:
            self.processMessagePC(elem)

    def message_processor(self, elem):
        try:
            self.processMessage(elem)
        except:
            io = StringIO.StringIO()
            traceback.print_exc(file=io)
            self.email_error(io.getvalue(), elem.toXml())

    def talkWithUser(self, elem):
        """
        Look for commands that a user may be asking me for
        @param elem domish.Element to process
        """
        if not elem.body:
            log.msg("Empty conversation?") 
            log.msg( elem.toXml() )
            return 

        bstring = unicode(elem.body).lower()
        #if re.match(r"^set sms#", bstring):
        #    self.handle_sms_request( elem, bstring)
        #if re.match(r"^cs[0-9]+", bstring):
        #    self.confirm_sms( elem, bstring)
        if re.match(r"^flood", bstring):
            self.handle_flood_request( elem, bstring)
        else:
            self.send_help_message( elem["from"] )
            
    def process_groupchat_cmd(self, room, res, cmd):
        """
        Logic to process any groupchat commands proferred to nwsbot

        @param room String roomname that this command came from
        @param res String value of the resource that sent the command
        @param cmd String command that the resource sent
        """
        # Make sure we know who the real JID of this user is....
        if not self.rooms[room]['occupants'].has_key(res):
            self.send_groupchat(room, "%s: Sorry, I am unable to process your request due to a lookup failure.  Please consider rejoining the chatroom if you really wish to speak with me." % (res, ))
            return

        # Figure out the user's affiliation
        aff = self.rooms[room]['occupants'][res]['affiliation']
        jid = self.rooms[room]['occupants'][res]['jid']

        # Support legacy ping, return as done
        if re.match(r"^ping", cmd, re.I):
            self.send_groupchat(room, "%s: %s"%(res, "pong"))

        # Listing of channels is not admin privs
        elif re.match(r"^channels list", cmd, re.I):
            self.channels_room_list(room)

        # Add a channel to the room's subscriptions
        elif re.match(r"^channels add", cmd, re.I):
            if aff in ['owner', 'admin']:
                self.channels_room_add(room, cmd[12:])
            else:
                err = "%s: Sorry, you must be a room admin to add a channel" \
                       % (res,)
                self.send_groupchat(room, err)

        # Del a channel to the room's subscriptions
        elif re.match(r"^channels del", cmd, re.I):
            if aff in ['owner', 'admin']:
                self.channels_room_del(room, cmd[12:])
            else:
                err = "%s: Sorry, you must be a room admin to add a channel" \
                       % (res,)
                self.send_groupchat(room, err)

        # Look for users request
        elif re.match(r"^users", cmd, re.I):
            if aff in ['owner', 'admin']:
                rmess = ""
                for hndle in self.rooms[room]['occupants'].keys():
                    rmess += "%s (%s), " % (hndle, 
                                          self.rooms[room]['occupants'][hndle]['jid'])
                self.send_privatechat(jid, "JIDs in room: %s" % (rmess,))
            else:
                err = "%s: Sorry, you must be a room admin to query users" \
                       % (res,)
                self.send_groupchat(room, err)


        # Else send error message about what I support
        else:
            err = "ERROR: unsupported command: '%s'" % (cmd,)
            self.send_groupchat(room, err)
            self.send_groupchat_help(room)

    def channels_room_list(self, room):
        """
        Send a listing of channels that the room is subscribed to...
        @param room to list
        """
        channels = []
        for channel in self.routingtable.keys():
            if room in self.routingtable[channel]:
                channels.append( channel )

        # Need to add a space in the channels listing so that the string does
        # not get so long that it causes chat clients to bail
        msg = "This room is subscribed to %s channels (%s)" % ( len(channels), 
                                                ", ".join(channels) )
        self.send_groupchat(room, msg)

    def channels_room_add(self, room, channel):
        """
        Logic to add a channel to a given room, this may get tricky
        """
        channel = channel.upper().strip().replace(" ", "")
        if len(channel) == 0:
            self.send_groupchat(room, "Blank or missing channel")
            return
        if channel.find(",") > -1:
            self.send_groupchat(room, "commas not permitted, using first entry")
            channel = channel.split(",")[0]

        if not self.routingtable.has_key(channel):
            # Add to the database
            sql = "INSERT into nwsbot_channels(id, name)\
                values ('%s','%s')" % (channel, channel)
            self.dbpool.runOperation(sql).addErrback( self.email_error, sql)
            # Add to the routing table blank array
            self.routingtable[channel] = []

        if room not in self.routingtable[channel]:
            # Add to routing table
            self.routingtable[channel].append( room )
            # Add to database
            sql = "INSERT into nwsbot_room_subscriptions \
                (roomname, channel) VALUES ('%s', '%s')" % (room, channel)
            self.dbpool.runOperation(sql).addErrback( self.email_error, sql)
            self.send_groupchat(room, "Subscribed %s to channel %s" % \
                (room, channel))
        else:
            self.send_groupchat(room, "%s was already subscribed to \
channel %s" % (room, channel))

        self.channels_room_list(room)

    def channels_room_del(self, room, channel):
        """
        Remove a certain channel from the room!
        """
        channel = channel.upper().strip().replace(" ", "")
        if len(channel) == 0:
            self.send_groupchat(room, "Blank or missing channel")
            return


        if not self.routingtable.has_key(channel):
            self.send_groupchat(room, "Unknown channel: %s" % (channel,))
            return

        if room not in self.routingtable[channel]:
            self.send_groupchat(room, "Room not subscribed to channel: %s" \
                  % (channel,))
            return

        # Remove from routing table
        self.routingtable[channel].remove(room)
        # Remove from database
        sql = "DELETE from nwsbot_room_subscriptions WHERE \
            roomname = '%s' and channel = '%s'" % (room, channel)
        self.dbpool.runOperation(sql).addErrback( self.email_error, sql)
        self.send_groupchat(room, "Unscribed %s to channel %s" % \
            (room, channel))
        self.channels_room_list(room)

    def send_groupchat_help(self, room):
        """
        Send a message to a given chatroom about what commands I support
        """
        msg = """Current Supported Commands:
  %(i)s: channels add channelname ### Add single channel to this room 
  %(i)s: channels del channelname ### Delete single channel to this room 
  %(i)s: channels list ### List channels this room is subscribed to
  %(i)s: ping          ### Test connectivity with a 'pong' response
  %(i)s: users         ### Generates list of users in room""" % {
                                                    'i': self.myjid.user }

        htmlmsg = msg.replace("\n", "<br />")
        self.send_groupchat(room, msg, htmlmsg)

    def handle_flood_request(self, elem, bstring):
        """
        All a user to flood a chatroom with messages to flush it!
        with star trek quotes, yes!
        """
        _from = jid.JID( elem["from"] )
        if not re.match(r"^nws-", _from.user):
            msg = "Sorry, you must be NWS to flood a chatroom!"
            self.send_privatechat(elem["from"], msg)
            return
        tokens = bstring.split()
        if len(tokens) == 1:
            msg = "Did you specify a room to flood?"
            self.send_privatechat(elem["from"], msg)
            return
        room = tokens[1].lower()
        o = open('util/startrek', 'r').read()
        fortunes = o.split("\n%\n")
        cnt_fortunes = len(fortunes)
        i = 0
        while i < 60:
            offset = int(cnt_fortunes * random.random())
            msg = fortunes[offset]
            self.send_groupchat(room, msg)
            i += 1
        self.send_groupchat(room, "Room flooding complete, offending message should no longer appear")

    def send_fb_fanpage(self, elem, page):
        """
        Post something to facebook fanpage
        """
        log.msg('attempting to send to facebook page %s' % (page,))
        bstring = unicode(elem.body)
        post_args = {}
        post_args['access_token'] = self.fb_access_tokens[page]
        tokens = bstring.split("http")
        if len(tokens) == 1:
            post_args['message'] = bstring
        else:
            post_args['message'] = tokens[0]
            post_args['link'] = "http"+ tokens[1]
            post_args['name'] = 'Product Link'
        if elem.x:
            for key in ['picture', 'name', 'link', 'caption',
                        'description']:
                if elem.x.hasAttribute(key):
                    post_args[key] = elem.x[key]

        url = "https://graph.facebook.com/me/feed?"
        postdata = urllib.urlencode(post_args)
        if self.has_football:
            cf = webclient.getPage( url, method='POST', postdata=postdata)
            cf.addCallback(self.fbsuccess, None, 'nwsbot_ingest',
                           post_args['message'])
            cf.addErrback(self.fbfail, None, 'nwsbot_ingest', 
                          post_args['message'], page)
            cf.addErrback( log.err )
        else:
            log.msg("Skipping facebook relay as I don't have the football")
   
    def process_twitter_cmd(self, room, res, plaintxt):
        """
        Process a command (#twitter or #social) generated within a chatroom
        """
        # Lets see if this room has a twitter page associated with it
        twitter = self.rooms[room]['twitter']
        if twitter is None:
            msg = '%s: Sorry, this room is not associated with ' % (res,)
            msg += 'a twitter account. Please contact Admin Team'
            self.send_groupchat(room, msg)
            return
        
        myjid = "%s,%s" % (room, self.rooms[room]['occupants'][res]['jid'])
        if self.rooms[room]['occupants'][res]['jid'] is None:
            msg = "%s: Sorry, I am unable to process your facebook " % (res,)
            msg += "request due to a lookup failure.  Please consider "
            msg += "rejoining the chatroom if you really wish to speak with me"
            self.send_groupchat(room, msg)
            return
   
        aff = self.rooms[room]['occupants'][res]['affiliation']
        
        if aff not in ['owner', 'admin']:
            msg = "%s: Sorry, you need to be a local room admin " % (res,)
            msg += "or owner to use twitter feature!"
            self.send_groupchat(room, msg)
            return
        
        access_token = self.tw_access_tokens.get(twitter, None)
        if access_token is None:
            msg = "%s: Sorry, I don't have permission to post to your " % (res,)
            msg += "page."
            self.send_groupchat(room, msg)
            return
        
        if len(plaintxt) > 139:
            msg = "%s: Sorry, your message is longer than 140 " % (res,)
            msg += "characters, so I can not relay to twitter!"
            self.send_groupchat(room, msg)
            return 
        
        # We can finally tweet! 
        self.tweet(plaintxt, access_token, room=room, myjid=myjid, 
                   twituser=twitter )
   
    def process_facebook_cmd(self, room, res, plaintxt):
        """
        Process a command (#facebook) generated within a chatroom requesting 
        facebook posting
          1. User must be local admin
          2. Bot posts back a link to the post, tricky!
        @param room The room name this request came from
        @param res The resource this came from
        @param plaintxt The plain text variant of this message
        """
        # Make sure the local room has a FB page associated with it
        if self.rooms[room]['fbpage'] is None:
            self.send_groupchat(room, "%s: Sorry, this room is not associated with Facebook Page.  Please contact Admin Team." % (res, ))
            return
        fbpage = self.rooms[room]['fbpage']
        
        # Make sure we know who the real JID of this user is....
        if not self.rooms[room]['occupants'].has_key(res):
            self.send_groupchat(room, "%s: Sorry, I am unable to process your facebook request due to a lookup failure.  Please consider rejoining the chatroom if you really wish to speak with me." % (res, ))
            return

        # Figure out the user's affiliation
        aff = self.rooms[room]['occupants'][res]['affiliation']
        myjid = "%s,%s" % (room, self.rooms[room]['occupants'][res]['jid'])

        if aff not in ['owner', 'admin']:
            self.send_groupchat(room, "%s: Sorry, you need to be a local room admin or owner to use facebook feature!" % (res, ))
            return
        
        if not self.fb_access_tokens.has_key(fbpage):
            self.send_groupchat(room, "%s: Sorry, I don't have permission to post to your page." % (res, ))
            return

        # Done with error checking!
        post_args = {}
        post_args['access_token'] = self.fb_access_tokens[fbpage]
        # Without encoding, this causes urlencode to be angry
        post_args['message'] = plaintxt.replace("#facebook", "").encode( 
                                       'ascii', 'ignore')

        # Need to use async proxy, please
        url = "https://graph.facebook.com/me/feed?"
        postdata = urllib.urlencode(post_args)
        if self.has_football:
            cf = webclient.getPage( url, method='POST', postdata=postdata)
            cf.addCallback(self.fbsuccess, room, myjid, post_args['message'])
            cf.addErrback(self.fbfail, room, myjid, post_args['message'], fbpage)            
            cf.addErrback( log.err )
        else:
            log.msg("Skipping facebook relay as I don't have the football")
            self.send_groupchat(room, "%s: Sorry, I am currently in non-production mode, so I am not sending facebook messages." % (res,))
