"""XMPP Stuff."""

from typing import TYPE_CHECKING

from twisted.words.xish.domish import Element

if TYPE_CHECKING:
    from iembot.bot import JabberClient


def route(bot: "JabberClient", channels: list, elem: Element):
    """Do XMPP stuff."""
    alertedRooms = []
    for channel in channels:
        for room in bot.routingtable.get(channel, []):
            if room in alertedRooms:
                continue
            alertedRooms.append(room)
            elem["to"] = f"{room}@{bot.config['bot.mucservice']}"
            bot.send_groupchat_elem(elem)
