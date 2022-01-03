""" Basic iembot/nwsbot implementation. """
import datetime
import traceback
from io import StringIO
import random
from collections import namedtuple
import copy
import urllib.parse as urlparse
import pickle
import re
import os
from xml.etree import ElementTree as ET

from twisted.words.xish import domish
from twisted.words.xish import xpath
from twisted.words.protocols.jabber import jid, client, error, xmlstream
from twisted.words.xish.xmlstream import STREAM_END_EVENT
from twisted.internet import reactor, threads
from twisted.application import internet
from twisted.python import log
from twisted.python.logfile import DailyLogFile
from twisted.internet.task import LoopingCall
from twisted.web import client as webclient

from oauth import oauth

from twittytwister import twitter
from pyiem.util import utc
import iembot.util as botutil

DATADIR = os.sep.join([os.path.dirname(__file__), "data"])
ROOM_LOG_ENTRY = namedtuple(
    "ROOM_LOG_ENTRY",
    [
        "seqnum",
        "timestamp",
        "log",
        "author",
        "product_id",
        "product_text",
        "txtlog",
    ],
)
PRESENCE_MUC_ITEM = (
    "/presence/x[@xmlns='http://jabber.org/protocol/muc#user']/item"
)
PRESENCE_MUC_STATUS = (
    "/presence/x[@xmlns='http://jabber.org/protocol/muc#user']/status"
)


class basicbot:
    """Here lies the Jabber Bot"""

    PICKLEFILE = "iembot_chatlog_v2.pickle"

    def __init__(
        self, name, dbpool, memcache_client=None, xml_log_path="logs"
    ):
        """Constructor"""
        self.startup_time = utc()
        self.name = name
        self.dbpool = dbpool
        self.memcache_client = memcache_client
        self.config = {}
        self.IQ = {}
        self.rooms = {}
        self.chatlog = {}
        self.seqnum = 0
        self.routingtable = {}
        self.tw_users = {}  # Storage by user_id => {screen_name: ..., oauth:}
        self.tw_routingtable = {}  # Storage by channel => [user_id, ]
        self.fb_access_tokens = {}
        self.fb_routingtable = {}
        self.webhooks_routingtable = {}
        self.has_football = True
        self.xmlstream = None
        self.firstlogin = False
        self.channelkeys = {}
        self.syndication = {}
        self.xmllog = DailyLogFile("xmllog", xml_log_path)
        self.myjid = None
        self.ingestjid = None
        self.conference = None
        self.email_timestamps = []
        self.fortunes = (
            open("%s/startrek" % (DATADIR,), "r").read().split("\n%\n")
        )
        self.twitter_oauth_consumer = None
        self.logins = 0
        botutil.load_chatlog(self)

        lc2 = LoopingCall(botutil.purge_logs, self)
        lc2.start(60 * 60 * 24)
        lc3 = LoopingCall(self.save_chatlog)
        lc3.start(600)  # Every 10 minutes

    def save_chatlog(self):
        """persist"""

        def really_save_chat_log():
            """called from a thread"""
            log.msg(f"Saving CHATLOG to {self.PICKLEFILE}")
            # unsure if deepcopy is necessary, but alas
            pickle.dump(
                copy.deepcopy(self.chatlog), open(self.PICKLEFILE, "wb")
            )

        reactor.callInThread(really_save_chat_log)

    def on_firstlogin(self):
        """callbacked when we are first logged in"""
        return

    def authd(self, _xs=None):
        """callback when we are logged into the server!"""
        botutil.email_error(
            None, self, "Logged into jabber server as %s" % (self.myjid,)
        )
        if not self.firstlogin:
            self.compute_daily_caller()
            self.on_firstlogin()
            self.firstlogin = True

        # Resets associated with the previous login session, perhaps
        self.rooms = {}
        self.IQ = {}

        self.load_twitter()
        self.send_presence()
        self.load_chatrooms(True)
        self.load_facebook()
        self.load_webhooks()

        lc = LoopingCall(self.housekeeping)
        lc.start(60)
        self.xmlstream.addObserver(STREAM_END_EVENT, lambda _: lc.stop())

    def next_seqnum(self):
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
        df = self.dbpool.runInteraction(
            botutil.load_chatrooms_from_db, self, always_join
        )
        df.addErrback(botutil.email_error, self, "load_chatrooms() failure")

    def load_twitter(self):
        """Load the twitter subscriptions and access tokens"""
        log.msg("load_twitter() called...")
        df = self.dbpool.runInteraction(botutil.load_twitter_from_db, self)
        df.addErrback(botutil.email_error, self, "load_twitter() failure")

    def load_webhooks(self):
        """Load the twitter subscriptions and access tokens"""
        log.msg("load_webhooks() called...")
        df = self.dbpool.runInteraction(botutil.load_webhooks_from_db, self)
        df.addErrback(botutil.email_error, self, "load_webhooks() failure")

    def load_facebook(self):
        """
        Load up the facebook configuration page/channel subscriptions
        """
        log.msg("load_facebook() called...")
        df = self.dbpool.runInteraction(botutil.load_facebook_from_db, self)
        df.addErrback(botutil.email_error, self)

    def check_for_football(self):
        """Logic to check if we have the football or not, this should
        be over-ridden"""
        self.has_football = True

    def fire_client_with_config(self, res, serviceCollection):
        """Calledback once bot has loaded its database configuration"""
        log.msg("fire_client_with_config() called ...")

        for row in res:
            self.config[row["propname"]] = row["propvalue"]
        log.msg(f"{len(self.config)} properties were loaded from the database")

        self.myjid = jid.JID(
            "%s@%s/twisted_words"
            % (self.config["bot.username"], self.config["bot.xmppdomain"])
        )
        self.ingestjid = jid.JID(
            "%s@%s"
            % (
                self.config["bot.ingest_username"],
                self.config["bot.xmppdomain"],
            )
        )
        self.conference = self.config["bot.mucservice"]

        self.twitter_oauth_consumer = oauth.OAuthConsumer(
            self.config["bot.twitter.consumerkey"],
            self.config["bot.twitter.consumersecret"],
        )

        factory = client.XMPPClientFactory(
            self.myjid, self.config["bot.password"]
        )
        # Limit reconnection delay to 60 seconds
        factory.maxDelay = 60
        factory.addBootstrap(xmlstream.STREAM_CONNECTED_EVENT, self.connected)
        factory.addBootstrap(xmlstream.STREAM_AUTHD_EVENT, self.authd)
        factory.addBootstrap(xmlstream.INIT_FAILED_EVENT, self.init_failed)
        factory.addBootstrap(xmlstream.STREAM_END_EVENT, self.disconnected)

        # pylint: disable=no-member
        i = internet.TCPClient(self.config["bot.connecthost"], 5222, factory)
        i.setServiceParent(serviceCollection)

    def connected(self, xs):
        """connected callback"""
        log.msg("Connected")
        self.xmlstream = xs
        self.xmlstream.rawDataInFn = self.rawDataInFn
        self.xmlstream.rawDataOutFn = self.rawDataOutFn

        self.xmlstream.addObserver("/message", self.on_message)
        self.xmlstream.addObserver("/iq", self.on_iq)
        self.xmlstream.addObserver("/presence/x/item", self.on_presence)

    def disconnected(self, _xs=None):
        """disconnected callback"""
        log.msg("disconnected() was called...")

    def init_failed(self, failure):
        """init failed for some reason"""
        log.err(failure)

    def get_fortune(self):
        """Get a random value from the array"""
        offset = int((len(self.fortunes) - 1) * random.random())
        return " ".join(self.fortunes[offset].replace("\n", "").split())

    def failure(self, f):
        """Some failure"""
        log.err(f)

    def debug(self, elem):
        """Debug"""
        log.msg(elem)

    def rawDataInFn(self, data):
        """write xmllog"""
        self.xmllog.write(
            "%s RECV %s\n" % (utc().strftime("%Y-%m-%d %H:%M:%S"), data)
        )

    def rawDataOutFn(self, data):
        """write xmllog"""
        self.xmllog.write(
            "%s SEND %s\n" % (utc().strftime("%Y-%m-%d %H:%M:%S"), data)
        )

    def housekeeping(self):
        """
        This gets exec'd every minute to keep up after ourselves
        1. XMPP Server Ping
        2. Check if we have the football
        3. Update presence
        """
        utcnow = utc()
        self.check_for_football()

        if self.IQ:
            log.msg("ERROR: missing IQs %s" % (list(self.IQ.keys()),))
        if len(self.IQ) > 5:
            self.IQ = {}
            botutil.email_error(
                "Logging out of Chat!", self, "IQ error limit reached..."
            )
            if self.xmlstream is not None:
                # Unsure of the proper code that a client should generate
                exc = error.StreamError("gone")
                self.xmlstream.sendStreamError(exc)
            return
        ping = domish.Element((None, "iq"))
        ping["to"] = self.myjid.host
        ping["type"] = "get"
        pingid = "%s" % (utcnow.strftime("%Y%m%d%H%M"),)
        ping["id"] = pingid
        ping.addChild(domish.Element(("urn:xmpp:ping", "ping")))
        if self.xmlstream is not None:
            self.IQ[pingid] = 1
            self.xmlstream.send(ping)
            if utcnow.minute % 10 == 0:
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
        message = domish.Element(("jabber:client", "message"))
        if to.find("@") == -1:  # base username, add domain
            to = "%s@%s" % (to, self.config["bot.xmppdomain"])
        message["to"] = to
        message["type"] = "chat"
        message.addElement("body", None, mess)
        html = message.addElement(
            "html", "http://jabber.org/protocol/xhtml-im"
        )
        body = html.addElement("body", "http://www.w3.org/1999/xhtml")
        if htmlstr is not None:
            body.addRawXml(htmlstr)
        else:
            p = body.addElement("p")
            p.addContent(mess)
        self.xmlstream.send(message)

    def send_groupchat(self, room, plain, htmlstr=None):
        """Send a groupchat message to a given room

        Args:
          room (str): The roomname (which we should have already joined)
          plain (str): The message to send to the room, no escaping necessary
          htmlstr (str, optional): The HTML variant of the message

        Returns:
          twisted.words.xish.domish.Element: the element that was sent
        """
        message = domish.Element(("jabber:client", "message"))
        message["to"] = "%s@%s" % (room, self.conference)
        message["type"] = "groupchat"
        message.addElement("body", None, plain)
        html = message.addElement(
            "html", "http://jabber.org/protocol/xhtml-im"
        )
        body = html.addElement("body", "http://www.w3.org/1999/xhtml")
        if htmlstr is not None:
            body.addRawXml(htmlstr)
        else:
            # Careful here, we always want to have valid xhtml, so we should
            # wrap plain text in a paragraph tag
            p = body.addElement("p")
            p.addContent(plain)
        # Ensure that we have well formed XML before sending it
        try:
            ET.fromstring(message.toXml())
        except Exception as exp:
            botutil.email_error(exp, self, message.toXml())
            return None
        else:
            self.send_groupchat_elem(message)
        return message

    def send_groupchat_elem(self, elem, to=None, secondtrip=False):
        """Wrapper for sending groupchat elements"""
        if to is not None:
            elem["to"] = to
        room = jid.JID(elem["to"]).user
        if room not in self.rooms:
            botutil.email_error(
                (
                    "Attempted to send message to room [%s] "
                    "we have not joined..."
                )
                % (room,),
                self,
                elem,
            )
            return
        if not self.rooms[room]["joined"]:
            if secondtrip:
                log.msg(
                    ("ABORT of send to room: %s, msg: %s, not in room")
                    % (room, elem)
                )
                return
            log.msg("delaying send to room: %s, not in room yet" % (room,))
            # Need to prevent elem['to'] object overwriting
            reactor.callLater(300, self.send_groupchat_elem, elem, elem["to"])
            return
        self.xmlstream.send(elem)

    def send_presence(self):
        """
        Set a presence for my login
        """
        presence = domish.Element(("jabber:client", "presence"))
        msg = ("Booted: %s Updated: %s UTC, Rooms: %s, Messages: %s") % (
            self.startup_time.strftime("%d %b"),
            utc().strftime("%H%M"),
            len(self.rooms),
            self.seqnum,
        )
        presence.addElement("status").addContent(msg)
        if self.xmlstream is not None:
            self.xmlstream.send(presence)

    def tweet(
        self,
        twttxt,
        access_token,
        room=None,
        myjid=None,
        user_id=None,
        twtextra=None,
        trip=0,
        twitter_media=None,
    ):
        """
        Tweet a message
        """
        if trip > 3:
            botutil.email_error("tweet retries exhausted", self, twttxt)
            return
        twttxt = botutil.safe_twitter_text(twttxt)
        if twitter_media:
            # hacky end-around to some blocking code
            df = threads.deferToThread(
                botutil.tweet,
                self,
                access_token,
                twttxt,
                twitter_media,
            )
            df.addCallback(botutil.tweet_cb, self, twttxt, "", "", user_id)
            df.addErrback(
                botutil.twitter_errback,
                self,
                user_id,
                f"User:{user_id} Tweet:{twttxt}",
            )
            df.addErrback(
                botutil.email_error,
                self,
                f"User: {user_id}, Text: {twttxt} Hit double exception",
            )
            return
        twt = twitter.Twitter(
            consumer=self.twitter_oauth_consumer, token=access_token
        )
        if twtextra is None:
            twtextra = dict()
        df = twt.update(twttxt, None, twtextra)
        df.addCallback(botutil.tweet_cb, self, twttxt, room, myjid, user_id)
        df.addErrback(
            botutil.tweet_eb,
            self,
            twttxt,
            access_token,
            room,
            myjid,
            user_id,
            twtextra,
            trip,
        )
        df.addErrback(log.err)

        return df

    def compute_daily_caller(self):
        """Figure out when to be called"""
        log.msg("compute_daily_caller() called...")
        # Figure out when to spam all rooms with a timestamp
        utcnow = utc() + datetime.timedelta(days=1)
        tnext = utcnow.replace(hour=0, minute=0, second=0)
        log.msg(
            "Initial Calling daily_timestamp in %s seconds"
            % ((tnext - utc()).seconds,)
        )
        reactor.callLater(
            (tnext - utc()).seconds, botutil.daily_timestamp, self
        )

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
        if _room not in self.rooms:
            botutil.email_error(
                "Got MUC presence from unknown room '%s'" % (_room,),
                self,
                elem,
            )
            return
        _handle = jid.JID(elem["from"]).resource
        statuses = xpath.queryForNodes(PRESENCE_MUC_STATUS, elem)
        muc_codes = []
        if statuses is not None:
            muc_codes = [status.getAttribute("code") for status in statuses]

        for item in items:
            affiliation = item.getAttribute("affiliation")
            _jid = item.getAttribute("jid")
            role = item.getAttribute("role")
            left = affiliation == "none" and role == "none"
            selfpres = "110" in muc_codes
            if selfpres:
                log.msg("MUC '%s' self presence left: %s" % (_room, left))
                self.rooms[_room]["joined"] = not left

            self.rooms[_room]["occupants"][_handle] = {
                "jid": _jid,
                "affiliation": affiliation,
                "role": role,
            }

    def route_message(self, elem, source="nwsbot_ingest"):
        """
        Route XML messages to the appropriate room

        @param elem: domish.Element stanza to process
        @param source optional source of this message, assume nwsbot_ingest
        """
        # Go look for body to see routing info!
        # Get the body string
        if not elem.body:
            log.msg("Unprocessable message:")
            log.msg(elem)
            return

        bstring = elem.body
        if not bstring:
            log.msg("Nothing found in body?")
            log.msg(elem)
            return

        # Send message to botstalk, unmodified
        elem["type"] = "groupchat"
        elem["to"] = "botstalk@%s" % (self.conference,)
        self.send_groupchat_elem(elem)

        if elem.x and elem.x.hasAttribute("channels"):
            channels = elem.x["channels"].split(",")
        else:
            # The body string contains
            (channel, meat) = bstring.split(":", 1)
            channels = [channel]
            # Send to chatroom, clip body of channel notation
            elem.body.children[0] = meat

        # Look for custom twitter formatting
        twt = bstring
        if elem.x and elem.x.hasAttribute("twitter"):
            twt = elem.x["twitter"]

        # Route to subscription channels
        alertedRooms = []
        for channel in channels:
            for room in self.routingtable.setdefault(channel, []):
                # hack attribute to avoid MUC relay alltogether
                if elem.x and elem.x.hasAttribute("facebookonly"):
                    continue
                # Don't send a message twice, this may be from redundant subs
                if room in alertedRooms:
                    continue
                alertedRooms.append(room)
                # Don't send to a room we don't know about
                if room not in self.rooms:
                    log.msg(
                        (
                            "Refusing to send MUC msg to unknown room: "
                            "'%s' msg: %s"
                        )
                        % (room, elem)
                    )
                    continue
                elem["to"] = "%s@%s" % (room, self.conference)
                self.send_groupchat_elem(elem)
        # Facebook Routing
        alertedPages = []
        alertedTwitter = []
        for channel in channels:
            if channel == "":
                continue
            if channel in self.tw_routingtable:
                log.msg("Twitter wants channel: %s" % (channel,))
                for user_id in self.tw_routingtable[channel]:
                    if user_id in alertedTwitter:
                        continue
                    log.msg(
                        "Twitter: %s wants channel: %s" % (user_id, channel)
                    )
                    alertedTwitter.append(user_id)
                    if elem.x and elem.x.hasAttribute("nwschatonly"):
                        continue
                    twuser = self.tw_users.get(user_id)
                    if twuser is None:
                        continue
                    log.msg(
                        "Channel: [%s] User: [%s,%s] Tweet: [%s]"
                        % (channel, user_id, twuser["screen_name"], twt)
                    )
                    if self.has_football:
                        twtextra = {}
                        if (
                            elem.x
                            and elem.x.hasAttribute("lat")
                            and elem.x.hasAttribute("long")
                        ):
                            twtextra["lat"] = elem.x["lat"]
                            twtextra["long"] = elem.x["long"]
                        self.tweet(
                            twt,
                            twuser["access_token"],
                            user_id=user_id,
                            myjid=source,
                            twtextra=twtextra,
                        )
                        # ASSUME we joined twitter room already
                        self.send_groupchat("twitter", twt)
                    else:
                        log.msg("No Twitter since we have no football")
                        self.send_groupchat(
                            "twitter", "NO FOOTBALL %s" % (twt,)
                        )

            if channel in self.fb_routingtable:
                log.msg("Facebook wants channel: %s" % (channel,))
                for page in self.fb_routingtable[channel]:
                    log.msg(
                        "Facebook Page: %s wants channel: %s" % (page, channel)
                    )
                    if page in alertedPages:
                        continue
                    alertedPages.append(page)
                    if elem.x and elem.x.hasAttribute("nwschatonly"):
                        continue
                    self.send_fb_fanpage(elem, page)

    def iq_processor(self, elem):
        """
        Something to process IQ messages
        """
        if elem.hasAttribute("id") and elem["id"] in self.IQ:
            del self.IQ[elem["id"]]

    def processMessagePC(self, elem):
        """
        Process a XML stanza that is a private chat

        @param elem: domish.Element stanza to process
        """
        _from = jid.JID(elem["from"])
        # Don't react to broadcast messages
        if _from.user is None:
            return

        # Intercept private messages via a chatroom, can't do that :)
        if _from.host == self.conference:
            self.convert_to_privatechat(_from)
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
I currently do not support any commands, sorry.""" % (
            self.myjid.user,
        )
        htmlmsg = msg.replace("\n", "<br />").replace(
            self.myjid.user,
            ('<a href="https://%s/%sfaq.php">%s</a>')
            % (self.myjid.host, self.myjid.user, self.myjid.user),
        )
        self.send_privatechat(user, msg, htmlmsg)

    def convert_to_privatechat(self, myjid):
        """
        The bot can't handle private chats via a MUC, readdress to a
        private chat

        @param myjid: MUC chat jabber ID to reroute
        """
        _handle = myjid.resource
        _room = myjid.user
        if _handle not in self.rooms[_room]["occupants"]:
            return
        realjid = self.rooms[_room]["occupants"][_handle]["jid"]

        self.send_help_message(realjid)

        message = domish.Element(("jabber:client", "message"))
        message["to"] = myjid.full()
        message["type"] = "chat"
        message.addElement(
            "body",
            None,
            (
                "I can't help you here, please chat "
                "with me outside of a groupchat.  "
                "I have initated such a chat for "
                "you."
            ),
        )
        self.xmlstream.send(message)

    def processMessageGC(self, elem):  # pylint: disable=unused-argument
        """override me please"""
        return

    def message_processor(self, elem):
        """
        This is our business method, figure out if this chat is a
        private message or a group one
        """
        if elem.hasAttribute("type") and elem["type"] == "groupchat":
            self.processMessageGC(elem)
        elif elem.hasAttribute("type") and elem["type"] == "error":
            botutil.email_error("Got Error Stanza?", self, elem.toXml())
        else:
            self.processMessagePC(elem)

    def on_message(self, elem):
        """We got a message!"""
        self.stanza_callback(self.message_processor, elem)

    def on_presence(self, elem):
        """We got a presence"""
        self.stanza_callback(self.presence_processor, elem)

    def on_iq(self, elem):
        """We got an IQ"""
        self.stanza_callback(self.iq_processor, elem)

    def stanza_callback(self, func, elem):
        """main callback on receipt of stanza

        We are currently wrapping this to prevent the callback from getting
        removed from the factory in case of a processing error.  There are
        likely more proper ways to do this.
        """
        try:
            func(elem)
        except Exception as exp:
            log.err(exp)
            io = StringIO()
            traceback.print_exc(file=io)
            botutil.email_error(io.getvalue(), self, elem.toXml())

    def talkWithUser(self, elem):
        """
        Look for commands that a user may be asking me for
        @param elem domish.Element to process
        """
        if not elem.body:
            log.msg("Empty conversation?")
            log.msg(elem.toXml())
            return

        bstring = elem.body.lower()
        if re.match(r"^flood", bstring):
            self.handle_flood_request(elem, bstring)
        else:
            self.send_help_message(elem["from"])

    def process_groupchat_cmd(self, room, res, cmd):
        """
        Logic to process any groupchat commands proferred to nwsbot

        @param room String roomname that this command came from
        @param res String value of the resource that sent the command
        @param cmd String command that the resource sent
        """
        # Make sure we know who the real JID of this user is....
        if res not in self.rooms[room]["occupants"]:
            self.send_groupchat(
                room,
                (
                    "%s: Sorry, I am unable to process "
                    "your request due to a lookup failure."
                    "  Please consider rejoining the "
                    "chatroom if you really wish to "
                    "speak with me."
                )
                % (res,),
            )
            return

        # Figure out the user's affiliation
        aff = self.rooms[room]["occupants"][res]["affiliation"]
        _jid = self.rooms[room]["occupants"][res]["jid"]

        # Support legacy ping, return as done
        if re.match(r"^ping", cmd, re.I):
            self.send_groupchat(room, "%s: %s" % (res, "pong"))

        # Listing of channels is not admin privs
        elif re.match(r"^channels list", cmd, re.I):
            botutil.channels_room_list(self, room)

        # Add a channel to the room's subscriptions
        elif re.match(r"^channels add", cmd, re.I):
            add_channel = cmd[12:].strip().upper()
            if aff in ["owner", "admin"]:
                if len(add_channel) < 24:
                    df = self.dbpool.runInteraction(
                        botutil.channels_room_add, self, room, cmd[12:]
                    )
                    df.addErrback(
                        botutil.email_error, self, room + " -> " + cmd
                    )
                else:
                    err = (
                        "%s: Error, channels are less than 24 characters!"
                    ) % (res,)
                    self.send_groupchat(room, err)
            else:
                err = (
                    "%s: Sorry, you must be a room admin to add a channel"
                ) % (res,)
                self.send_groupchat(room, err)

        # Del a channel to the room's subscriptions
        elif re.match(r"^channels del", cmd, re.I):
            if aff in ["owner", "admin"]:
                df = self.dbpool.runInteraction(
                    botutil.channels_room_del, self, room, cmd[12:]
                )
                df.addErrback(botutil.email_error, self, room + " -> " + cmd)
            else:
                err = (
                    "%s: Sorry, you must be a room admin to add a channel"
                ) % (res,)
                self.send_groupchat(room, err)

        # Look for users request
        elif re.match(r"^users", cmd, re.I):
            if aff in ["owner", "admin"]:
                rmess = ""
                for hndle in self.rooms[room]["occupants"].keys():
                    rmess += ("%s (%s), ") % (
                        hndle,
                        self.rooms[room]["occupants"][hndle]["jid"],
                    )
                self.send_privatechat(_jid, "JIDs in room: %s" % (rmess,))
            else:
                err = (
                    "%s: Sorry, you must be a room admin to query users"
                ) % (res,)
                self.send_groupchat(room, err)

        # Else send error message about what I support
        else:
            err = "ERROR: unsupported command: '%s'" % (cmd,)
            self.send_groupchat(room, err)
            self.send_groupchat_help(room)

    def send_groupchat_help(self, room):
        """
        Send a message to a given chatroom about what commands I support
        """
        msg = (
            "Current Supported Commands:\n"
            "%(i)s: channels add channelname[,channelname] "
            "### Add channel subscription(s) for this room\n"
            "%(i)s: channels del channelname[,channelname] "
            "### Delete channel subscriptions(s) for this room\n"
            "%(i)s: channels list "
            "### List channels this room is subscribed to\n"
            "%(i)s: ping          "
            "### Test connectivity with a 'pong' response\n"
            "%(i)s: users         ### Generates list of users in room"
        ) % {"i": self.myjid.user}

        htmlmsg = msg.replace("\n", "<br />")
        self.send_groupchat(room, msg, htmlmsg)

    def handle_flood_request(self, elem, bstring):
        """
        All a user to flood a chatroom with messages to flush it!
        with star trek quotes, yes!
        """
        _from = jid.JID(elem["from"])
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
        for _i in range(60):
            self.send_groupchat(room, self.get_fortune())
        self.send_groupchat(
            room,
            (
                "Room flooding complete, offending message "
                "should no longer appear"
            ),
        )

    def send_fb_fanpage(self, elem, page):
        """
        Post something to facebook fanpage
        """
        log.msg("attempting to send to facebook page %s" % (page,))
        bstring = elem.body
        post_args = {}
        post_args["access_token"] = self.fb_access_tokens[page]
        tokens = bstring.split("http")
        if len(tokens) == 1:
            post_args["message"] = bstring
        else:
            post_args["message"] = tokens[0]
            post_args["link"] = "http" + tokens[1]
            post_args["name"] = "Product Link"
        if elem.x:
            for key in ["picture", "name", "link", "caption", "description"]:
                if elem.x.hasAttribute(key):
                    post_args[key] = elem.x[key]

        url = "https://graph.facebook.com/me/feed?"
        postdata = urlparse.urlencode(post_args)
        if self.has_football:
            cf = webclient.getPage(url, method="POST", postdata=postdata)
            cf.addCallback(
                botutil.fbsuccess,
                self,
                None,
                "nwsbot_ingest",
                post_args["message"],
            )
            cf.addErrback(
                botutil.fbfail,
                self,
                None,
                "nwsbot_ingest",
                post_args["message"],
                page,
            )
            cf.addErrback(log.err)
        else:
            log.msg("Skipping facebook relay as I don't have the football")
