"""Send content to various webhooks."""

import json
from io import BytesIO

from twisted.internet import reactor
from twisted.python import log
from twisted.web.client import Agent, FileBodyProducer, readBody
from twisted.web.http_headers import Headers

from iembot.types import JabberClient


def load_webhooks_from_db(txn, bot: JabberClient):
    """Load twitter config from database"""
    txn.execute(
        """
    select c.channel_name, w.url from iembot_webhooks w,
    iembot_subscriptions s, iembot_channels c
    where w.iembot_account_id = s.iembot_account_id and s.channel_id = c.id
    order by channel_name asc
        """
    )
    table = {}
    for row in txn.fetchall():
        url = row["url"]
        channel = row["channel_name"]
        # Unsure how this could happen, but just in case
        if url != "" and channel != "":
            res = table.setdefault(channel, [])
            res.append(url)
    bot.webhooks_routingtable = table
    log.msg(f"load_webhooks_from_db(): {txn.rowcount} subs found")


def route(bot: JabberClient, channels, elem):
    """Route messages found in provided elem.

    Args:
      bot: iembot instance.
      channels (list): channels for this message.
      elem: xish element.
    """
    subs = [
        bot.webhooks_routingtable[channel]
        for channel in channels
        if channel in bot.webhooks_routingtable
    ]
    if not subs:
        return
    data = {"text": str(elem.body)}
    postdata = json.dumps(data).encode("utf-8", "ignore")
    used = []
    for hooks in subs:
        for hook in hooks:
            if hook in used:
                continue
            used.append(hook)
            bp = FileBodyProducer(BytesIO(postdata))
            defer = Agent(reactor).request(
                method=b"POST",
                uri=hook.encode("ascii"),
                headers=Headers({"Content-type": ["application/json"]}),
                bodyProducer=bp,
            )
            defer.addCallback(_cb)
            defer.addErrback(_eb)


def _eb(*args):
    """errback."""
    log.msg(str(args))


def _cb(*args):
    d = readBody(args[0])
    d.addCallback(_cbBody)
    return d


def _cbBody(body):
    """deferred deferred."""
    log.msg(body)
