"""Test basicbot API."""

from unittest.mock import Mock

from iembot.basicbot import BasicBot


def test_authd_api():
    """Call authd."""
    dbpool = Mock()
    bot = BasicBot(None, dbpool, xml_log_path="/tmp/")
    xs = Mock()
    bot.connected(xs)
    bot.authd()
