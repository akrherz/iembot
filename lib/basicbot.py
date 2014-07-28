""" Basic iembot/nwsbot implementation, upstream for this code is 
    on github: https://github.com/akrherz/iembot
"""

from twisted.words.xish import domish
from twisted.words.xish import xpath
from twisted.words.protocols.jabber import jid, client
from twisted.internet import reactor
from twisted.application import internet
from twisted.python import log
from twisted.python.logfile import DailyLogFile
import twisted.web.error as weberror

import datetime
import pytz
import json
import traceback
import StringIO
import random
import os
import locale
import re
import glob
from twittytwister import twitter
locale.setlocale(locale.LC_ALL, 'en_US')

def safe_twitter_text( text ):
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

    def __init__(self, dbpool):
        """ Constructor """
        self.startup_time = datetime.datetime.utcnow().replace(
                                                tzinfo=pytz.timezone("UTC"))
        self.dbpool = dbpool
        self.config = {}
        self.IQ = {}
        self.rooms = {}
        self.has_football = True
        self.xmlstream = None
        self.firstrun = False
        self.xmllog = DailyLogFile('xmllog', 'logs/')
        self.myjid = None
        self.conference = None

        self.fortunes = open('startrek', 'r').read().split("\n%\n")

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
        self.conference = self.config['bot.mucservice']

        # We need to clean up after ourselves and do stuff while running
        #lc = LoopingCall( self.housekeeping )
        #lc.start(60)
        
        # We need to clean up after ourselves and do stuff while running
        #lc2 = LoopingCall( self.purge_logs )
        #lc2.start(60*60*24)
        
        # Start up task to spam rooms at the 0z time
        #tnext =  mx.DateTime.gmt() + mx.DateTime.RelativeDateTime(hour=0,
        #                                        days=1, minute=0, second=0)
        #secs = (tnext - mx.DateTime.gmt()).seconds
        #reactor.callLater(secs, self.daily_timestamp)
        
        factory = client.basicClientFactory(self.myjid, 
                                            self.config['bot.password'])
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

        # Reset MAIL_COUNT at the top of the new day
        if gmtnow.hour == 0 and gmtnow.minute < 5 and self.MAIL_COUNT != 24:
            log.msg("Resetting MAIL_COUNT, old was %s" % (self.MAIL_COUNT,))
            self.MAIL_COUNT = 24

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
        message = domish.Element(('jabber:client','message'))
        message['to'] = "%s@%s" % (room, self.conference)
        message['type'] = "groupchat"
        message.addElement('body', None, plain)
        html = message.addElement('html', 'http://jabber.org/protocol/xhtml-im')
        body = html.addElement('body', 'http://www.w3.org/1999/xhtml')
        if htmlstr:
            body.addRawXml( htmlstr )
        else:
            body.addContent( plain )
        self.send_groupchat_elem( message )
        
    def send_groupchat_elem(self, elem, to=None, secondtrip=False):
        """ Wrapper for sending groupchat elements """
        if to is not None:
            elem['to'] = to
        room = jid.JID(elem['to']).user
        if not self.rooms[room]['occupants'].has_key( self.myjid.user ):
            if secondtrip:
                log.msg("ABORT of send to room: %s, msg: %s, not in room" % (
                                                        room, elem))
                return
            log.msg("delaying send to room: %s, not in room" % (room,))
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
        twttxt = safe_twitter_text( twttxt )
        df = twt.update( twttxt, None, twtextra )
        df.addCallback(self.tweet_cb, twttxt, room, myjid, twituser)
        df.addErrback(self.tweet_eb, twttxt, room, myjid, twituser)
        df.addErrback( log.err )

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
        """
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
        #log.msg("presence_processor() called")
        items = xpath.queryForNodes("/presence/x[@xmlns='http://jabber.org/protocol/muc#user']/item", elem)
        if items is None:
            return
        
        _room = jid.JID( elem["from"] ).user
        _handle = jid.JID( elem["from"] ).resource
        for item in items:
            affiliation = item.getAttribute('affiliation')
            _jid = item.getAttribute('jid')
            role = item.getAttribute('role')
            self.rooms[ _room ]['occupants'][ _handle ] = {
                  'jid': _jid,
                  'affiliation': affiliation,
                  'role': role }
            
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

        if _from.userhost() == self.ingestJID.userhost():
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

    def processor(self, elem):
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