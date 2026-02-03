"""Test bot API."""

from unittest.mock import Mock

from iembot.bot import JabberClient


def test_bot_apis(bot: JabberClient):
    """Exercise things within the bot."""
    bot.fire_client(None, Mock())
    bot.send_help_message("admin")
    bot.send_groupchat_help("dmxchat")


def test_authd_api(bot: JabberClient):
    """Call authd."""
    xs = Mock()
    bot.connected(xs)
    bot.authd()
