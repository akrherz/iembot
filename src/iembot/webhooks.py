"""Send content to various webhooks."""

import json
from io import BytesIO

from twisted.internet import reactor
from twisted.python import log
from twisted.web.client import Agent, FileBodyProducer, readBody
from twisted.web.http_headers import Headers


def route(bot, channels, elem):
    """Route messages found in provided elem.

    Args:
      bot: iembot instance.
      channels (list): channels for this message.
      elem: xish element.
    """
    # {'DMX': [url, url, ...]}
    subs = [
        bot.webhooks_routingtable[channel]
        for channel in channels
        if channel in bot.webhooks_routingtable
    ]
    if not subs:
        return
    data = {"text": str(elem.body)}
    postdata = json.dumps(data).encode("utf-8", "ignore")
    for hooks in subs:
        for hook in hooks:
            log.msg(hook)
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
