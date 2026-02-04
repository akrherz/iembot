"""Test iembot.xmpp"""

from twisted.words.xish.domish import Element

from iembot.xmpp import route


def test_route(bot):
    """Can we route stuff, yes we can."""
    msg = Element((None, "message"))
    msg["from"] = "test@example.com"
    msg["to"] = "dmxchat@localhost"
    msg.addElement("body", content="Hello, world!")
    route(bot, ["DMX"], msg)
