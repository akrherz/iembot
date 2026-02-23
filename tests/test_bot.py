"""Test bot API."""

from unittest.mock import Mock, patch

import pytest_twisted

from iembot.bot import JabberClient


@pytest_twisted.inlineCallbacks
def test_gh185_no_str_response(bot: JabberClient):
    """Test that we can persist things."""
    with patch("iembot.bot.log.err") as mock_err:
        yield bot.log_iembot_social_log(123, {"not": "a string"})
    mock_err.assert_not_called()


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


def test_xml(bot):
    msg = bot.send_groupchat("roomname", "Hello Friend")
    assert msg is not None

    msg = bot.send_groupchat("roomname", "Hello Friend &")
    assert msg is not None

    msg = bot.send_groupchat("roomname", "Hello Friend &&amp;")
    assert msg is not None
