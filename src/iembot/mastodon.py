"""Mastodon stuff."""

from twisted.python import log
from twisted.words.xish.domish import Element

from iembot.types import JabberClient


def route(bot: JabberClient, channels: list, elem: Element):
    """Do Maston stuff."""
    alertedPages = []
    for channel in channels:
        for user_id in bot.md_routingtable.get(channel, []):
            if user_id not in bot.md_users:
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
            bot.toot(
                user_id,
                elem.x["twitter"],
                twitter_media=elem.x.getAttribute("twitter_media"),
                latitude=lat,  # TODO: unused
                longitude=long,  # TODO: unused
            )
