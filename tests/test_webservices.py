"""Try to test the webservices."""

from iembot import webservices


def test_status(bot):
    """Test the status renderer."""
    ss = webservices.StatusChannel(bot)
    assert ss.render(None) is not None


def test_api(bot):
    """Can we import API?"""
    res = webservices.wfo_rss(bot, "dmxchat")
    assert res is not None
