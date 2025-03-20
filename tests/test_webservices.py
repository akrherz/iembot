"""Try to test the webservices."""

from iembot import webservices
from iembot.basicbot import BasicBot


def test_status():
    """Test the status renderer."""
    bot = BasicBot("iembot", None, xml_log_path="/tmp")
    ss = webservices.StatusChannel(bot)
    assert ss.render(None) is not None


def test_api():
    """Can we import API?"""
    bot = BasicBot("iembot", None, xml_log_path="/tmp")
    res = webservices.wfo_rss(bot, "dmxchat")
    assert res is not None
