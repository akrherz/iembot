"""Test bot API."""

from unittest.mock import Mock

from iembot.bot import JabberClient


def test_authd_api():
    """Call authd."""
    dbpool = Mock()
    bot = JabberClient(None, dbpool, xml_log_path="/tmp/")
    xs = Mock()
    bot.connected(xs)
    bot.authd()
