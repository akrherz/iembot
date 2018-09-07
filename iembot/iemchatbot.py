""" Chat bot implementation of IEMBot """
from __future__ import print_function
import datetime
import re

from twisted.internet import reactor
from twisted.web.client import HTTPClientFactory
from twisted.mail.smtp import SMTPSenderFactory
from twisted.words.protocols.jabber import jid
from twisted.words.xish import xpath
from twisted.python import log
from iembot import basicbot


# http://stackoverflow.com/questions/7016602
HTTPClientFactory.noisy = False
SMTPSenderFactory.noisy = False


class JabberClient(basicbot.basicbot):
    """ I am a Jabber Bot

    I provide some customizations that are not provided by basicbot, here are
    some details on calling order

    1. Twisted .tac calls 'basicbot.fire_client_with_config'
    2. jabber.client callsback 'authd' when we login
       -> 'authd' will call on_firstlogin when this is the first_run
       -> 'auth' will call on_login
    3-inf. jabber.client callsback 'authd' when we get logged in
       -> 'auth' will call on_login
    """

    def on_firstlogin(self):
        """ local stuff that we care about, that gets called on first login """
        pass

    def processMessageGC(self, elem):
        """Process a stanza element that is from a chatroom"""
        # Ignore all messages that are x-stamp (delayed / room history)
        # <delay xmlns='urn:xmpp:delay' stamp='2016-05-06T20:04:17.513Z'
        #  from='nwsbot@laptop.local/twisted_words'/>
        if xpath.queryForNodes("/message/delay[@xmlns='urn:xmpp:delay']",
                               elem):
            return

        _from = jid.JID(elem["from"])
        room = _from.user
        res = _from.resource

        body = xpath.queryForString('/message/body', elem)
        if body is not None and len(body) >= 4 and body[:4] == "ping":
            self.send_groupchat(room, "%s: %s" % (res, self.get_fortune()))

        # Look for bot commands
        if re.match(r"^%s:" % (self.name,), body):
            self.process_groupchat_cmd(room, res, body[7:].strip())

        # In order for the message to be logged, it needs to be from iembot
        # and have a channels attribute
        if res is None or res != 'iembot':
            return

        a = xpath.queryForNodes("/message/x[@xmlns='nwschat:nwsbot']", elem)
        if a is None or not a:
            return

        roomlog = self.chatlog.setdefault(room, [])
        ts = datetime.datetime.utcnow()

        product_id = ''
        if elem.x and elem.x.hasAttribute("product_id"):
            product_id = elem.x['product_id']

        html = xpath.queryForNodes('/message/html/body', elem)
        log_entry = body
        if html is not None:
            log_entry = html[0].toXml()

        if len(roomlog) > 40:
            roomlog.pop()

        def writelog(product_text=None):
            """Actually do what we want to do"""
            if product_text is None or product_text == '':
                product_text = 'Sorry, product text is unavailable.'
            roomlog.insert(0, basicbot.ROOM_LOG_ENTRY(
                seqnum=self.next_seqnum(),
                timestamp=ts.strftime("%Y%m%d%H%M%S"),
                log=log_entry,
                author=res,
                product_id=product_id,
                product_text=product_text,
                txtlog=body)
            )
        if product_id == '':
            writelog()
            return

        def got_data(res, trip):
            """got a response!"""
            # print("got_data(%s, %s)" % (res, trip))
            (_flag, data) = res
            if data is None:
                if trip < 5:
                    reactor.callLater(10, memcache_fetch, trip)
                else:
                    writelog()
                return
            log.msg("memcache lookup of %s succeeded" % (product_id, ))
            # log.msg("Got a response! res: %s" % (res, ))
            writelog(data.decode('ascii', 'ignore'))

        def no_data(mixed):
            """got no data"""
            log.err(mixed)
            writelog()

        def memcache_fetch(trip):
            """fetch please"""
            trip += 1
            log.msg("memcache_fetch(trip=%s, product_id=%s" % (trip,
                                                               product_id))
            defer = self.memcache_client.get(product_id.encode('utf-8'))
            defer.addCallback(got_data, trip)
            defer.addErrback(no_data)

        memcache_fetch(0)

    def processMessagePC(self, elem):
        # log.msg("processMessagePC() called from %s...." % (elem['from'],))
        _from = jid.JID(elem["from"])
        if elem["from"] == self.config['bot.xmppdomain']:
            log.msg("MESSAGE FROM SERVER?")
            return
        # Intercept private messages via a chatroom, can't do that :)
        if _from.host == self.config['bot.mucservice']:
            log.msg("ERROR: message is MUC private chat")
            return

        if _from.userhost() != "iembot_ingest@%s" % (
                                            self.config['bot.xmppdomain']):
            log.msg("ERROR: message not from iembot_ingest")
            return

        # Go look for body to see routing info!
        # Get the body string
        bstring = xpath.queryForString('/message/body', elem)
        if not bstring:
            log.msg("Nothing found in body?")
            return

        if elem.x and elem.x.hasAttribute("channels"):
            channels = elem.x['channels'].split(",")
        else:
            # The body string contains
            channel = bstring.split(":", 1)[0]
            channels = [channel, ]
            # Send to chatroom, clip body of channel notation
            # elem.body.children[0] = meat

        # Always send to botstalk
        elem['to'] = "botstalk@%s" % (self.config['bot.mucservice'],)
        elem['type'] = "groupchat"
        self.send_groupchat_elem(elem)

        alertedRooms = []
        for channel in channels:
            for room in self.routingtable.get(channel, []):
                if room in alertedRooms:
                    continue
                alertedRooms.append(room)
                elem['to'] = "%s@%s" % (room, self.config['bot.mucservice'])
                self.send_groupchat_elem(elem)
            for page in self.tw_routingtable.get(channel, []):
                if page not in self.tw_access_tokens:
                    log.msg(("Failed to tweet due to no access_tokens for %s"
                             ) % (page,))
                    continue
                # Require the x.twitter attribute to be set to prevent
                # confusion with some ingestors still sending tweets themself
                if not elem.x.hasAttribute("twitter"):
                    continue
                twtextra = {}
                if (elem.x and elem.x.hasAttribute("lat") and
                        elem.x.hasAttribute("long")):
                    twtextra['lat'] = elem.x['lat']
                    twtextra['long'] = elem.x['long']
                log.msg("Sending tweet '%s' to page '%s'" % (elem.x['twitter'],
                                                             page))
                # Finally, actually tweet, this is in basicbot
                self.tweet(elem.x['twitter'], self.tw_access_tokens[page],
                           twtextra=twtextra, twituser=page)
