"""Twitter/X stuff."""

from typing import TYPE_CHECKING

from twisted.python import log
from twisted.words.xish.domish import Element

if TYPE_CHECKING:
    from iembot.bot import JabberClient


def route(bot: "JabberClient", channels: list, elem: Element):
    """Do the twitter work."""
    alertedPages = []
    for channel in channels:
        for user_id in bot.tw_routingtable.get(channel, []):
            if user_id not in bot.tw_users:
                log.msg(f"Failed to tweet due to no access_tokens {user_id}")
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
            bot.tweet(
                user_id,
                elem.x["twitter"],
                twitter_media=elem.x.getAttribute("twitter_media"),
                latitude=lat,
                longitude=long,
            )
