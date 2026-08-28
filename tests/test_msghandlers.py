"""Test iembot.msghandlers."""

from twisted.words.xish.domish import Element

from iembot.bot import JabberClient
from iembot.msghandlers import process_groupchat
from iembot.webservices import wfo_rss


def test_gh28_body_double_encode(bot: JabberClient):
    """Test that the body is not double-encoded in the log."""

    msg = Element((None, "message"))
    msg["from"] = "botstalk@localhost/iembot"
    msg["to"] = "me@localhost"
    msg["type"] = "groupchat"
    msg.addElement("body", content="Hello & World")

    msg.x = msg.addChild(Element(("nwschat:nwsbot", "x")))
    msg.x["channels"] = "XXX"
    process_groupchat(bot, msg)

    assert bot.chatlog["botstalk"][0].txtlog == "Hello & World"

    # Now check what we get for RSS
    rss = wfo_rss(bot, "botstalk")
    assert b"Hello &amp; World" in rss
