"""Tests for iembot atmosphere module."""

import queue
from unittest import mock

import pytest
import responses
from twisted.words.xish.domish import Element

from iembot.atmosphere import (
    ATManager,
    ATWorkerThread,
    at_send_message,
    load_atmosphere_from_db,
    route,
)
from iembot.types import JabberClient


# Fixed FakeATClient to match real signatures and return values
class FakeATClient:
    def __init__(self):
        self.login_calls = []
        self.send_post_calls = []
        self.send_image_calls = []

    def login(self, handle, password):
        self.login_calls.append((handle, password))
        return "me"

    def send_post(self, msg):
        if msg == "RAISE":
            raise Exception("Test exception")
        self.send_post_calls.append(msg)

    def send_image(self, msg, image=None, image_alt=None):
        self.send_image_calls.append((msg, image, image_alt))


@pytest.mark.timeout(10)  # Ensure the thread hackery does not cause trouble
def test_atworkerthread_run_and_process_message():
    """Test ATWorkerThread run loop and process_message logic."""
    q = queue.Queue()
    worker = ATWorkerThread(q, "user", "pw")
    worker.client = FakeATClient()
    # Put a message with media and msg
    q.put({"twitter_media": "http://fake", "msg": "hello http://link"})
    # Message where the twitter_media request will fail
    q.put({"twitter_media": "http://r404", "msg": "just text"})
    # Message where the twitter_media request will generate +1MB image
    q.put({"twitter_media": "http://toobig", "msg": "just text"})
    # Message that will raise unaccounted for exception
    q.put({"msg": "RAISE"})
    # Signal thread to exit
    q.put(None)

    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, "http://fake", body=b"fakeimage", status=200)
        rsps.add(responses.GET, "http://r404", body=b"fakeimage", status=404)
        rsps.add(
            responses.GET, "http://toobig", body=b"x" * 1_000_001, status=200
        )
        worker.start()
        q.join()  # Wait for all tasks
        worker.join(timeout=2)
    # Check that login and send_post/send_image were called
    assert worker.client.login_calls[0] == ("user", "pw")
    assert worker.client.send_image_calls or worker.client.send_post_calls


@pytest.mark.parametrize("database", ["iembot"])
def test_load_atmosphere_from_db(dbcursor, bot: JabberClient):
    """Test the method."""
    load_atmosphere_from_db(dbcursor, bot)


def test_route_no_x_in_message(bot: JabberClient):
    """Test what happens with a message without X."""
    msg = Element(("jabber:client", "message"))
    msg["body"] = "Test Message"
    route(bot, "unknown_user", msg)


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
