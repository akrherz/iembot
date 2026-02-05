"""Tests for iembot atmosphere module."""

from unittest import mock

import pytest
from twisted.words.xish.domish import Element

from iembot.atmosphere import (
    ATManager,
    at_send_message,
    load_atmosphere_from_db,
    route,
)
from iembot.types import JabberClient


@pytest.mark.parametrize("database", ["iembot"])
def test_load_atmosphere_from_db(dbcursor, bot: JabberClient):
    """Test the method."""
    load_atmosphere_from_db(dbcursor, bot)


def test_at_send_message_unknown_user(bot: JabberClient):
    """Test at_send_message with unknown user."""
    # Should not raise an error
    msg = Element(("jabber:client", "message"))
    msg["body"] = "Test Message"
    msg.x = Element(("", "x"))
    msg.x["twitter"] = "Test message"
    route(bot, "unknown_user", msg)


def test_at_send_message_no_handle(bot: JabberClient):
    """Test at_send_message with user that has no at_handle."""
    bot.at_users = {"123": {"at_handle": None}}
    bot.at_routingtable = {
        "XXX": [
            "123",
        ]
    }
    msg = Element(("jabber:client", "message"))
    msg.x = Element(("", "x"))
    msg.x["twitter"] = "Test message"
    msg.x["twitter_media"] = (
        "https://mesonet.agron.iastate.edu/data/mesonet.gif"
    )
    msg["body"] = "Test Message"
    route(bot, ["XXX"], msg)


def test_at_send_message_with_handle(bot: JabberClient):
    """Test at_send_message with valid at_handle."""
    bot.at_users = {"123": {"at_handle": "test.bsky.social"}}
    bot.at_manager = ATManager()
    bot.at_manager.at_clients["test.bsky.social"] = mock.Mock()
    bot.at_manager.submit = mock.Mock()
    at_send_message(bot, "123", "test message", extra_key="value")
    bot.at_manager.submit.assert_called_once_with(
        "test.bsky.social", {"msg": "test message", "extra_key": "value"}
    )


def test_atmanager_add_client():
    """Test ATManager add_client."""
    manager = ATManager()
    with mock.patch("iembot.atmosphere.ATWorkerThread") as mock_thread:
        mock_instance = mock.Mock()
        mock_thread.return_value = mock_instance
        manager.add_client("test.bsky.social", "password123")
        mock_thread.assert_called_once()
        mock_instance.start.assert_called_once()
        assert "test.bsky.social" in manager.at_clients


def test_atmanager_add_client_duplicate():
    """Test ATManager doesn't add duplicate clients."""
    manager = ATManager()
    manager.at_clients["test.bsky.social"] = mock.Mock()
    with mock.patch("iembot.atmosphere.ATWorkerThread") as mock_thread:
        manager.add_client("test.bsky.social", "password123")
        mock_thread.assert_not_called()


def test_atmanager_submit():
    """Test ATManager submit."""
    manager = ATManager()
    mock_queue = mock.Mock()
    mock_thread = mock.Mock()
    mock_thread.queue = mock_queue
    manager.at_clients["test.bsky.social"] = mock_thread

    manager.submit("test.bsky.social", {"msg": "Hello"})
    mock_queue.put.assert_called_once_with({"msg": "Hello"})
