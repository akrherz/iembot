"""Try to test the webservices."""

from twisted.web.test.requesthelper import DummyRequest

from iembot.types import JabberClient
from iembot.webservices import (
    RoomChannel,
    StatusChannel,
    wfo_rss,
)


def test_gh189_invalid_seqnum(bot: JabberClient):
    """Test an invalid seqnum."""
    ss = RoomChannel(bot)
    request = DummyRequest([])
    request.uri = b"/room/dmxchat"
    request.addArg(b"seqnum", b"")
    res = ss.render(request)
    assert res == b'"ERROR"'


def test_status(bot: JabberClient):
    """Test the status renderer."""
    ss = StatusChannel(bot)
    assert ss.render(None) is not None


def test_api(bot: JabberClient):
    """Can we import API?"""
    res = wfo_rss(bot, "dmxchat")
    assert res is not None
