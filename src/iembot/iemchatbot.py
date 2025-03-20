"""Chat bot implementation of IEMBot"""

import datetime
import re

from twisted.internet import reactor
from twisted.mail.smtp import SMTPSenderFactory
from twisted.python import log
from twisted.words.protocols.jabber import jid
from twisted.words.xish import xpath

from iembot.basicbot import ROOM_LOG_ENTRY, BasicBot
from iembot.webhooks import route as webhooks_route

# http://stackoverflow.com/questions/7016602
SMTPSenderFactory.noisy = False


class JabberClient(BasicBot):
    """I am a Jabber Bot

    I provide some customizations that are not provided by basicbot, here are
    some details on calling order

    1. Twisted .tac calls 'basicbot.fire_client_with_config'
    2. jabber.client callsback 'authd' when we login
       -> 'auth' will call on_login
    3-inf. jabber.client callsback 'authd' when we get logged in
       -> 'auth' will call on_login
    """

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
        if re.match(r"^" f"{self.name}:", body):
            self.process_groupchat_cmd(room, res, body[7:].strip())

        # In order for the message to be logged, it needs to be from iembot
        # and have a channels attribute
        if res is None or res != "iembot":
            return

        a = xpath.queryForNodes("/message/x[@xmlns='nwschat:nwsbot']", elem)
        if a is None or not a:
            return

        roomlog = self.chatlog.setdefault(room, [])
        ts = datetime.datetime.utcnow()

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
            # log.msg("Got a response! res: %s" % (res, ))
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

    def processMessagePC(self, elem):
        # log.msg("processMessagePC() called from %s...." % (elem['from'],))
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
            # Send to chatroom, clip body of channel notation
            # elem.body.children[0] = meat

        # Always send to botstalk
        elem["to"] = f"botstalk@{self.config['bot.mucservice']}"
        elem["type"] = "groupchat"
        self.send_groupchat_elem(elem)

        alertedRooms = []
        alertedPages = []
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
