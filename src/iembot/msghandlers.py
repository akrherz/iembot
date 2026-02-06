"""Logic handling messages the bot receives."""

from pyiem.util import utc
from twisted.internet import reactor
from twisted.python import log
from twisted.words.protocols.jabber import jid
from twisted.words.xish import xpath
from twisted.words.xish.domish import Element

from iembot import ROOM_LOG_ENTRY
from iembot.types import JabberClient

REGISTERED_HANDLERS = []


def register_handler(handler: callable):
    """Add a message handler to the registry."""
    if handler not in REGISTERED_HANDLERS:
        REGISTERED_HANDLERS.append(handler)


def process_privatechat(bot: JabberClient, elem: Element) -> None:
    """Starting point for processing a private (1 on 1) chat.

    Args:
      bot (JabberClient): The running bot instance receiving the message
      elem (Element): The XML Received.
    """
    _from = jid.JID(elem["from"])
    if elem["from"] == bot.config["bot.xmppdomain"]:
        log.msg("MESSAGE FROM SERVER?")
        return
    # Intercept private messages via a chatroom, can't do that :)
    if _from.host == bot.config["bot.mucservice"]:
        log.msg("ERROR: message is MUC private chat")
        return

    if _from.userhost() != f"iembot_ingest@{bot.config['bot.xmppdomain']}":
        log.msg("ERROR: message not from iembot_ingest")
        return

    # Ready for launch
    process_message_from_ingest(bot, elem)


def process_message_from_ingest(bot: JabberClient, elem: Element) -> None:
    """Process a message received from the ingest system."""

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
    elem["to"] = f"botstalk@{bot.config['bot.mucservice']}"
    elem["type"] = "groupchat"
    bot.send_groupchat_elem(elem)

    for handler in REGISTERED_HANDLERS:
        handler(bot, channels, elem)


def process_groupchat(bot: JabberClient, elem: Element) -> None:
    """Starting point for groupchat processing.

    Args:
      bot (JabberClient): Running bot instance
      elem (Element): Payload received.
    """
    # Ignore all messages that are x-stamp (delayed / room history)
    # <delay xmlns='urn:xmpp:delay' stamp='2016-05-06T20:04:17.513Z'
    #  from='nwsbot@laptop.local/twisted_words'/>
    if xpath.queryForNodes("/message/delay[@xmlns='urn:xmpp:delay']", elem):
        return

    _from = jid.JID(elem["from"])
    room: str = _from.user
    res = _from.resource

    body = xpath.queryForString("/message/body", elem)
    if body is not None and len(body) >= 4 and body[:4] == "ping":
        bot.send_groupchat(room, f"{res}: {bot.get_fortune()}")

    # Look for bot commands
    if body.startswith(bot.name):
        bot.process_groupchat_cmd(room, res, body[7:].strip())

    # In order for the message to be logged, it needs to be from iembot
    # and have a channels attribute
    if res is None or res != "iembot":
        return

    a = xpath.queryForNodes("/message/x[@xmlns='nwschat:nwsbot']", elem)
    if a is None or not a:
        return

    roomlog = bot.chatlog.setdefault(room, [])
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
                seqnum=bot.next_seqnum(),
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

    def got_data(data: bytes | None, trip: int):
        """got a response!"""
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

    def memcache_fetch(trip: int):
        """fetch please"""
        next_trip = trip + 1
        if next_trip > 0:
            log.msg(f"memcache_fetch(trip={trip}, product_id={product_id}")
        defer = bot.memcache_client.get(product_id.encode("utf-8"))
        defer.addCallback(got_data, next_trip)
        defer.addErrback(no_data)

    memcache_fetch(0)
