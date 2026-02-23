"""Send content to various webhooks."""

import json
import time
from functools import partial
from typing import Any

import requests
from twisted.internet.threads import deferToThread
from twisted.python import log

from iembot.types import JabberClient


def load_webhooks_from_db(txn, bot: JabberClient):
    """Load twitter config from database"""
    txn.execute(
        """
    select c.channel_name, w.iembot_account_id, w.url from iembot_webhooks w,
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
            res: list[dict[str, Any]] = table.setdefault(channel, [])
            res.append(
                {
                    "iembot_account_id": row["iembot_account_id"],
                    "url": url,
                }
            )
    bot.webhooks_routingtable = table
    log.msg(f"load_webhooks_from_db(): {txn.rowcount} subs found")


def really_hook(url: str, postdata: bytes, **kwargs: dict) -> str:
    """Process the webook within a thread, so sleeping is OK..."""
    try:
        resp = requests.post(url, data=postdata, timeout=5)
        resp.raise_for_status()
        if resp.status_code == 200:
            return resp.text
    except Exception as e:
        log.err(f"Webhook error {url}: {e}")
        time.sleep(kwargs.get("sleep", 30))
    # One more time
    resp = requests.post(url, data=postdata, timeout=5)
    resp.raise_for_status()
    return resp.text


def route(bot: JabberClient, channels, elem, **kwargs):
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
        for entry in hooks:
            if entry["url"] in used:
                continue
            used.append(entry["url"])
            df = deferToThread(really_hook, entry["url"], postdata, **kwargs)
            df.addCallback(
                partial(bot.log_iembot_social_log, entry["iembot_account_id"])
            )
            df.addErrback(log.err)
