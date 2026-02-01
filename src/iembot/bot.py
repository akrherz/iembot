"""Basic iembot/nwsbot implementation."""

import copy
import os
import pickle
import random
import re
import traceback
from datetime import timedelta
from io import StringIO
from typing import NamedTuple
from xml.etree import ElementTree as ET

from pyiem.util import utc
from twisted.application import internet
from twisted.internet import reactor, threads
from twisted.internet.task import LoopingCall
from twisted.mail.smtp import SMTPSenderFactory
from twisted.python import log
from twisted.python.logfile import DailyLogFile
from twisted.words.protocols.jabber import client, jid, xmlstream
from twisted.words.xish import domish, xpath

import iembot.util as botutil
from iembot.atworker import ATManager
from iembot.slack import load_slack_from_db, send_to_slack
from iembot.webhooks import route as webhooks_route

# http://stackoverflow.com/questions/7016602
SMTPSenderFactory.noisy = False
DATADIR = os.sep.join([os.path.dirname(__file__), "data"])


class ROOM_LOG_ENTRY(NamedTuple):
    seqnum: int
    timestamp: str
    log: str
    author: str
    product_id: str
    product_text: str
    txtlog: str


PRESENCE_MUC_ITEM = (
    "/presence/x[@xmlns='http://jabber.org/protocol/muc#user']/item"
)
PRESENCE_MUC_STATUS = (
    "/presence/x[@xmlns='http://jabber.org/protocol/muc#user']/status"
)


class JabberClient:
    """Here lies the Jabber Bot"""

    def __init__(
        self, name, dbpool, memcache_client=None, xml_log_path="logs"
    ):
        """Constructor"""
        self.startup_time = utc()
        self.picklefile = f"{name}_chatlog_v2.pickle"
        self.name = name
        self.dbpool = dbpool
        self.memcache_client = memcache_client
        self.config = {}
        # Adds entries of ping requests made to the server and if we get
        # a response. If this gets to 5 items, we reconnect.
        self.outstanding_pings = []
        self.rooms = {}
        self.chatlog = {}
        self.seqnum = 0
        self.routingtable = {}
        self.at_manager = ATManager()
        self.tw_users = {}  # Storage by user_id => {screen_name: ..., oauth:}
        self.tw_routingtable = {}  # Storage by channel => [user_id, ]
        # Storage by user_id => {access_token: ..., api_base_url: ...}
        self.md_users = {}
        self.md_routingtable = {}  # Storage by channel => [user_id, ]
        # Slack integration
        self.slack_teams = {}
        self.slack_routingtable = {}
        # Webhooks integration
        self.webhooks_routingtable = {}
        self.xmlstream = None
        self.firstlogin = False
        self.xmllog = DailyLogFile("xmllog", xml_log_path)
        self.myjid = None
        self.ingestjid = None
        self.conference = None
        self.email_timestamps = []
        self.keepalive_lc = None  # Keepalive LoopingCall
        fn = os.path.join(DATADIR, "startrek")
        with open(fn, encoding="utf-8") as fp:
            self.fortunes = fp.read().split("\n%\n")
        botutil.load_chatlog(self)

        lc2 = LoopingCall(botutil.purge_logs, self)
        lc2.start(60 * 60 * 24)
        lc3 = LoopingCall(reactor.callInThread, self.save_chatlog)
        lc3.start(600)  # Every 10 minutes

    def save_chatlog(self):
        """called from a thread"""
        log.msg(f"Saving CHATLOG to {self.picklefile}")
        with open(self.picklefile, "wb") as fh:
            # unsure if deepcopy is necessary, but alas
            pickle.dump(copy.deepcopy(self.chatlog), fh)

    def reload_config(self, always_join: bool):
        """Jobs the bot should do when a database reload is needed."""
        self.load_twitter()
        self.load_mastodon()
        self.load_chatrooms(always_join)
        self.load_webhooks()
        self.load_slack()

    def authd(self, _xs=None):
        """callback when we are logged into the server!"""
        botutil.email_error(
            None, self, f"Logged into jabber server as {self.myjid}"
        )
        if not self.firstlogin:
            self.compute_daily_caller()
            self.firstlogin = True

        # Resets associated with the previous login session, perhaps
        self.rooms = {}
        self.outstanding_pings = []

        self.reload_config(always_join=True)

        # Start the keepalive loop
        if self.keepalive_lc is None:
            self.keepalive_lc = LoopingCall(self.housekeeping)
            self.keepalive_lc.start(60)

    def next_seqnum(self):
        """
        Simple tool to generate a sequence number for message logging
        """
        self.seqnum += 1
        return self.seqnum

    def load_chatrooms(self, always_join: bool):
        """
        Load up the chatrooms and subscriptions from the database!, I also
        support getting called at a later date for any changes
        """
        log.msg("load_chatrooms() called...")
        df = self.dbpool.runInteraction(
            botutil.load_chatrooms_from_db, self, always_join
        )
        # Send a presence update, which in the case of the first login will
        # provoke any offline messages to be sent.
        df.addCallback(self.send_presence)
        df.addErrback(botutil.email_error, self, "load_chatrooms() failure")

    def load_twitter(self):
        """Load the twitter subscriptions and access tokens"""
        log.msg("load_twitter() called...")
        df = self.dbpool.runInteraction(botutil.load_twitter_from_db, self)
        df.addErrback(botutil.email_error, self, "load_twitter() failure")

    def load_slack(self):
        """Load the slack subscriptions and access tokens"""
        log.msg("load_slack() called...")
        df = self.dbpool.runInteraction(load_slack_from_db, self)
        df.addErrback(botutil.email_error, self, "load_slack() failure")

    def load_mastodon(self):
        """Load the Mastodon subscriptions and access tokens"""
        log.msg("load_mastodon() called...")
        df = self.dbpool.runInteraction(botutil.load_mastodon_from_db, self)
        df.addErrback(botutil.email_error, self, "load_mastodon() failure")

    def load_webhooks(self):
        """Load the twitter subscriptions and access tokens"""
        log.msg("load_webhooks() called...")
        df = self.dbpool.runInteraction(botutil.load_webhooks_from_db, self)
        df.addErrback(botutil.email_error, self, "load_webhooks() failure")

    def fire_client_with_config(self, res, serviceCollection):
        """Calledback once bot has loaded its database configuration"""
        log.msg("fire_client_with_config() called ...")

        for row in res:
            self.config[row["propname"]] = row["propvalue"]
        log.msg(f"{len(self.config)} properties were loaded from the database")

        self.myjid = jid.JID(
            f"{self.config['bot.username']}@{self.config['bot.xmppdomain']}/"
            "twisted_words"
        )
        self.ingestjid = jid.JID(
            f"{self.config['bot.ingest_username']}@"
            f"{self.config['bot.xmppdomain']}"
        )
        self.conference = self.config["bot.mucservice"]

        factory = client.XMPPClientFactory(
            self.myjid, self.config["bot.password"]
        )
        # Limit reconnection delay to 60 seconds
        factory.maxDelay = 60
        factory.addBootstrap(xmlstream.STREAM_CONNECTED_EVENT, self.connected)
        factory.addBootstrap(xmlstream.STREAM_AUTHD_EVENT, self.authd)
        factory.addBootstrap(xmlstream.INIT_FAILED_EVENT, log.err)
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

    def get_fortune(self):
        """Get a random value from the array"""
        offset = int((len(self.fortunes) - 1) * random.random())
        return " ".join(self.fortunes[offset].replace("\n", "").split())

    def rawDataInFn(self, data):
        """write xmllog"""
        self.xmllog.write(
            f"{utc():%Y-%m-%d %H:%M:%S} RECV "
            f"{data.decode('utf-8', 'ignore')}\n"
        )

    def rawDataOutFn(self, data):
        """write xmllog"""
        self.xmllog.write(
            f"{utc():%Y-%m-%d %H:%M:%S} SEND "
            f"{data.decode('utf-8', 'ignore')}\n"
        )

    def housekeeping(self):
        """
        This gets exec'd every minute to keep up after ourselves
        1. XMPP Server Ping
        2. Update presence
        """
        if self.outstanding_pings:
            log.msg(f"Currently unresponded pings: {self.outstanding_pings}")
        if len(self.outstanding_pings) > 5:
            self.outstanding_pings = []
            botutil.email_error(
                "Logging out of Chat!", self, "IQ error limit reached..."
            )
            if self.xmlstream is not None:
                # send a disconnect
                self.xmlstream.sendFooter()
            return
        if self.xmlstream is None:
            log.msg("xmlstream is None, not sending ping")
            return
        utcnow = utc()
        ping = domish.Element((None, "iq"))
        ping["to"] = self.myjid.host
        ping["type"] = "get"
        pingid = f"{utcnow:%Y%m%d%H%M.%S}"
        ping["id"] = pingid
        ping.addChild(domish.Element(("urn:xmpp:ping", "ping")))
        self.outstanding_pings.append(pingid)
        self.xmlstream.send(ping)
        # Update our presence every ten minutes with some debugging info
        if utcnow.minute % 10 == 0:
            self.send_presence()

    def send_privatechat(self, to, mess, htmlstr=None):
        """
        Helper method to send private messages

        @param to: String jabber ID to send the message too
        @param mess: String plain text version to send
        @param html: Optional String html version
        """
        message = domish.Element(("jabber:client", "message"))
        if to.find("@") == -1:  # base username, add domain
            to = f"{to}@{self.config['bot.xmppdomain']}"
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
        message["to"] = f"{room}@{self.conference}"
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
                f"Attempted to send message to room [{room}] "
                "we have not joined...",
                self,
                elem,
            )
            return
        if not self.rooms[room]["joined"]:
            if secondtrip:
                log.msg(
                    f"ABORT of send to room: {room}, msg: {elem}, not in room"
                )
                return
            secs = random.randint(0, 10)
            log.msg(f"delaying by {secs}s send to: {room}, not in room yet")
            # Need to prevent elem['to'] object overwriting
            reactor.callLater(secs, self.send_groupchat_elem, elem, elem["to"])
            return
        self.xmlstream.send(elem)

    def send_presence(self, _=None):
        """
        Set a presence for my login, could be from a callback (load_chatrooms).
        """
        presence = domish.Element(("jabber:client", "presence"))
        msg = (
            f"Booted: {self.startup_time:%d %b} "
            f"Updated: {utc():%H%M} UTC, Rooms: {len(self.rooms)}, "
            f"Messages: {self.seqnum}"
        )
        presence.addElement("status").addContent(msg)
        if self.xmlstream is not None:
            self.xmlstream.send(presence)

    def tweet(self, user_id, twttxt, **kwargs):
        """
        Tweet a message
        """
        twttxt = botutil.safe_twitter_text(twttxt)
        botutil.at_send_message(self, user_id, twttxt, **kwargs)

        df = threads.deferToThread(
            botutil.tweet,
            self,
            user_id,
            twttxt,
            **kwargs,
        )
        df.addCallback(botutil.tweet_cb, self, twttxt, "", "", user_id)
        df.addErrback(
            botutil.twitter_errback,
            self,
            user_id,
            twttxt,
        )
        df.addErrback(
            botutil.email_error,
            self,
            f"User: {user_id}, Text: {twttxt} Hit double exception",
        )
        return df

    def toot(self, user_id, twttxt, **kwargs):
        """
        Send a message to Mastodon
        """
        twttxt = botutil.safe_twitter_text(twttxt)
        df = threads.deferToThread(
            botutil.toot,
            self,
            user_id,
            twttxt,
            **kwargs,
        )
        df.addCallback(botutil.toot_cb, self, twttxt, "", "", user_id)
        df.addErrback(
            botutil.mastodon_errback,
            self,
            user_id,
            twttxt,
        )
        df.addErrback(
            botutil.email_error,
            self,
            f"User: {user_id}, Text: {twttxt} Hit double exception",
        )
        return df

    def compute_daily_caller(self):
        """Figure out when to be called"""
        log.msg("compute_daily_caller() called...")
        # Figure out when to spam all rooms with a timestamp
        utcnow = utc() + timedelta(days=1)
        tnext = utcnow.replace(hour=0, minute=0, second=0)
        log.msg(
            "Initial Calling daily_timestamp in "
            f"{(tnext - utc()).seconds} seconds"
        )
        reactor.callLater(
            (tnext - utc()).seconds, botutil.daily_timestamp, self
        )

    def presence_processor(self, elem):
        """Process the presence stanza

                The bot process keeps track of room occupants and their
                affiliations, roles so to provide ACLs for room admin
                activities.

                Args:
                  elem (domish.Element): stanza

        <presence xmlns='jabber:client' to='nwsbot@laptop.local/twisted_words'
            from='dmxchat@conference.laptop.local/nws-daryl.herzmann'>
            <priority>1</priority>
            <c xmlns='http://jabber.org/protocol/caps'
            node='http://pidgin.im/'
                ver='AcN1/PEN8nq7AHD+9jpxMV4U6YM='
                ext='voice-v1 camera-v1 video-v1'
                hash='sha-1'/>
            <x xmlns='vcard-temp:x:update'><photo/></x>
            <x xmlns='http://jabber.org/protocol/muc#user'>
                <item affiliation='owner' jid='nws-mortal@laptop.local/laptop'
                role='moderator'/>
            </x>
        </presence>
        """
        items = xpath.queryForNodes(PRESENCE_MUC_ITEM, elem)
        if items is None:
            return

        _room = jid.JID(elem["from"]).user
        if _room not in self.rooms:
            botutil.email_error(
                f"Got MUC presence from unknown room '{_room}'",
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
                log.msg(f"MUC '{_room}' self presence left: {left}")
                self.rooms[_room]["joined"] = not left

            self.rooms[_room]["occupants"][_handle] = {
                "jid": _jid,
                "affiliation": affiliation,
                "role": role,
            }

    def iq_processor(self, elem: domish.Element):
        """Response to IQ stanzas."""
        typ = elem.getAttribute("type")
        # A response is being requested of us.
        if typ == "get" and elem.firstChildElement().name == "ping":
            # Respond to a ping request.
            pong = domish.Element((None, "iq"))
            pong["type"] = "result"
            pong["to"] = elem["from"]
            pong["from"] = elem["to"]
            pong["id"] = elem["id"]
            self.xmlstream.send(pong)
        # We are getting a response to a request we sent, maybe.
        elif typ == "result":
            if elem.getAttribute("id") in self.outstanding_pings:
                self.outstanding_pings.remove(elem.getAttribute("id"))

    def processMessagePC(self, elem):
        _from = jid.JID(elem["from"])
        if elem["from"] == self.config["bot.xmppdomain"]:
            log.msg("MESSAGE FROM SERVER?")
            return
        # Intercept private messages via a chatroom, can't do that :)
        if _from.host == self.config["bot.mucservice"]:
            log.msg("ERROR: message is MUC private chat")
            return

        if (
            _from.userhost()
            != f"iembot_ingest@{self.config['bot.xmppdomain']}"
        ):
            log.msg("ERROR: message not from iembot_ingest")
            return

        # Go look for body to see routing info!
        # Get the body string
        bstring = xpath.queryForString("/message/body", elem)
        if not bstring:
            log.msg("Nothing found in body?")
            return

        if elem.x and elem.x.hasAttribute("channels"):
            channels = elem.x["channels"].split(",")
        else:
            # The body string contains
            channel = bstring.split(":", 1)[0]
            channels = [channel]

        # Always send to botstalk
        elem["to"] = f"botstalk@{self.config['bot.mucservice']}"
        elem["type"] = "groupchat"
        self.send_groupchat_elem(elem)

        alertedRooms = []
        alertedPages = []
        alertedSlacks = []
        for channel in channels:
            for room in self.routingtable.get(channel, []):
                if room in alertedRooms:
                    continue
                alertedRooms.append(room)
                elem["to"] = f"{room}@{self.config['bot.mucservice']}"
                self.send_groupchat_elem(elem)
            for user_id in self.tw_routingtable.get(channel, []):
                if user_id not in self.tw_users:
                    log.msg(
                        f"Failed to tweet due to no access_tokens {user_id}"
                    )
                    continue
                # Require the x.twitter attribute to be set to prevent
                # confusion with some ingestors still sending tweets themself
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
                # Finally, actually tweet, this is in basicbot
                self.tweet(
                    user_id,
                    elem.x["twitter"],
                    twitter_media=elem.x.getAttribute("twitter_media"),
                    latitude=lat,
                    longitude=long,
                )
            for slack_key in self.slack_routingtable.get(channel, []):
                if slack_key in alertedSlacks:
                    continue
                alertedSlacks.append(slack_key)
                log.msg("Attempting slack send...")
                d = threads.deferToThread(
                    send_to_slack, self, *slack_key.split("|"), elem
                )
                d.addErrback(log.msg)

            for user_id in self.md_routingtable.get(channel, []):
                if user_id not in self.md_users:
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
                self.toot(
                    user_id,
                    elem.x["twitter"],
                    twitter_media=elem.x.getAttribute("twitter_media"),
                    latitude=lat,  # TODO: unused
                    longitude=long,  # TODO: unused
                )
        webhooks_route(self, channels, elem)

    def send_help_message(self, user):
        """
        Send a user a help message about what I can do
        """
        me = self.myjid.user
        msg = (
            f"Hi, I am {me}.  You can try talking directly "
            "with me. I currently do not support any commands, sorry."
        )
        htmlmsg = msg.replace("\n", "<br />").replace(
            self.myjid.user,
            f'<a href="https://{self.myjid.host}/{me}faq.php">%s</a>',
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

    def processMessageGC(self, elem):
        """Process a stanza element that is from a chatroom"""
        # Ignore all messages that are x-stamp (delayed / room history)
        # <delay xmlns='urn:xmpp:delay' stamp='2016-05-06T20:04:17.513Z'
        #  from='nwsbot@laptop.local/twisted_words'/>
        if xpath.queryForNodes(
            "/message/delay[@xmlns='urn:xmpp:delay']", elem
        ):
            return

        _from = jid.JID(elem["from"])
        room = _from.user
        res = _from.resource

        body = xpath.queryForString("/message/body", elem)
        if body is not None and len(body) >= 4 and body[:4] == "ping":
            self.send_groupchat(room, f"{res}: {self.get_fortune()}")

        # Look for bot commands
        if body.startswith(self.name):
            self.process_groupchat_cmd(room, res, body[7:].strip())

        # In order for the message to be logged, it needs to be from iembot
        # and have a channels attribute
        if res is None or res != "iembot":
            return

        a = xpath.queryForNodes("/message/x[@xmlns='nwschat:nwsbot']", elem)
        if a is None or not a:
            return

        roomlog = self.chatlog.setdefault(room, [])
        ts = utc()

        product_id = ""
        if elem.x and elem.x.hasAttribute("product_id"):
            product_id = elem.x["product_id"]

        html = xpath.queryForNodes("/message/html/body", elem)
        log_entry = body
        if html is not None:
            log_entry = html[0].toXml()

        if len(roomlog) > 40:
            roomlog.pop()

        def writelog(product_text=None):
            """Actually do what we want to do"""
            if product_text is None or product_text == "":
                product_text = "Sorry, product text is unavailable."
            roomlog.insert(
                0,
                ROOM_LOG_ENTRY(
                    seqnum=self.next_seqnum(),
                    timestamp=ts.strftime("%Y%m%d%H%M%S"),
                    log=log_entry,
                    author=res,
                    product_id=product_id,
                    product_text=product_text,
                    txtlog=body,
                ),
            )

        if product_id == "":
            writelog()
            return

        def got_data(res, trip):
            """got a response!"""
            (_flag, data) = res
            if data is None:
                if trip < 5:
                    reactor.callLater(10, memcache_fetch, trip)
                else:
                    writelog()
                return
            if trip > 1:
                log.msg(f"memcache lookup of {product_id} succeeded")
            writelog(data.decode("ascii", "ignore"))

        def no_data(mixed):
            """got no data"""
            log.err(mixed)
            writelog()

        def memcache_fetch(trip):
            """fetch please"""
            trip += 1
            if trip > 1:
                log.msg(f"memcache_fetch(trip={trip}, product_id={product_id}")
            defer = self.memcache_client.get(product_id.encode("utf-8"))
            defer.addCallback(got_data, trip)
            defer.addErrback(no_data)

        memcache_fetch(0)

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
                    f"{res}: Sorry, I am unable to process "
                    "your request due to a lookup failure."
                    "  Please consider rejoining the "
                    "chatroom if you really wish to "
                    "speak with me."
                ),
            )
            return

        # Figure out the user's affiliation
        aff = self.rooms[room]["occupants"][res]["affiliation"]
        _jid = self.rooms[room]["occupants"][res]["jid"]

        # Support legacy ping, return as done
        if re.match(r"^ping", cmd, re.IGNORECASE):
            self.send_groupchat(room, f"{res}: pong")

        # Listing of channels is not admin privs
        elif re.match(r"^channels list", cmd, re.IGNORECASE):
            botutil.channels_room_list(self, room)

        # Add a channel to the room's subscriptions
        elif re.match(r"^channels add", cmd, re.IGNORECASE):
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
                        f"{res}: Error, channels are less than 24 characters!"
                    )
                    self.send_groupchat(room, err)
            else:
                err = (
                    f"{res}: Sorry, you must be a room admin to add a channel"
                )
                self.send_groupchat(room, err)

        # Del a channel to the room's subscriptions
        elif re.match(r"^channels del", cmd, re.IGNORECASE):
            if aff in ["owner", "admin"]:
                df = self.dbpool.runInteraction(
                    botutil.channels_room_del, self, room, cmd[12:]
                )
                df.addErrback(botutil.email_error, self, f"{room} -> {cmd}")
            else:
                err = (
                    f"{res}: Sorry, you must be a room admin to add a channel"
                )
                self.send_groupchat(room, err)

        # Look for users request
        elif re.match(r"^users", cmd, re.IGNORECASE):
            if _jid is None:
                err = "Sorry, I am not able to see room occupants."
                self.send_groupchat(room, err)
            elif aff in ["owner", "admin"]:
                rmess = ""
                for hndle in self.rooms[room]["occupants"].keys():
                    rmess += (
                        f"{hndle} "
                        f"({self.rooms[room]['occupants'][hndle]['jid']}), "
                    )
                self.send_privatechat(_jid, f"JIDs in room: {rmess}")
            else:
                err = f"{res}: Sorry, you must be a room admin to query users"
                self.send_groupchat(room, err)

        # Else send error message about what I support
        else:
            err = f"ERROR: unsupported command: '{cmd}'"
            self.send_groupchat(room, err)
            self.send_groupchat_help(room)

    def send_groupchat_help(self, room):
        """
        Send a message to a given chatroom about what commands I support
        """
        msg = (
            "Current Supported Commands:\n"
            f"{self.myjid.user}: channels add channelname[,channelname] "
            "### Add channel subscription(s) for this room\n"
            f"{self.myjid.user}: channels del channelname[,channelname] "
            "### Delete channel subscriptions(s) for this room\n"
            f"{self.myjid.user}: channels list "
            "### List channels this room is subscribed to\n"
            f"{self.myjid.user}: ping          "
            "### Test connectivity with a 'pong' response\n"
            f"{self.myjid.user}: users   ### Generates list of users in room"
        )

        htmlmsg = msg.replace("\n", "<br />")
        self.send_groupchat(room, msg, htmlmsg)

    def handle_flood_request(self, elem, bstring):
        """
        All a user to flood a chatroom with messages to flush it!
        with star trek quotes, yes!
        """
        _from = jid.JID(elem["from"])
        if not re.match("^nws-", str(_from.user)):
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
