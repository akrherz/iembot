"""XMPP Stuff."""

from twisted.words.xish.domish import Element

from iembot.types import JabberClient


def route(bot: JabberClient, channels: list, elem: Element):
    """Do XMPP stuff."""
    alertedRooms = []
    for channel in channels:
        for room in bot.routingtable.get(channel, []):
            if room in alertedRooms:
                continue
            alertedRooms.append(room)
            elem["to"] = f"{room}@{bot.config['bot.mucservice']}"
            bot.send_groupchat_elem(elem)
            iembot_account_id = bot.rooms.get(room, {}).get(
                "iembot_account_id"
            )
            if iembot_account_id is not None:
                # Meh, this is sort of the response, hehe
                bot.log_iembot_social_log(iembot_account_id, str(elem))
