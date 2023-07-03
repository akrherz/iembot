"""Test basicbot API."""

from unittest.mock import Mock

from iembot.basicbot import basicbot


def test_authd_api():
    """Call authd."""
    dbpool = Mock()
    bot = basicbot(None, dbpool, xml_log_path="/tmp/")
    xs = Mock()
    bot.connected(xs)
    bot.authd()
