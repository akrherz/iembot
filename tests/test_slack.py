"""Exercises Slack related tests."""

from unittest import mock

import pytest
from twisted.internet import defer
from twisted.web.server import NOT_DONE_YET
from twisted.web.test.requesthelper import DummyRequest

from iembot.slack import (
    SlackInstallChannel,
    SlackSubscribeChannel,
    load_slack_from_db,
    requests,
    send_to_slack,
)
from iembot.types import JabberClient


@defer.inlineCallbacks
def test_subscribe_channel_render(bot: JabberClient):
    """Test that we can run the render workflow."""
    ss = SlackSubscribeChannel(bot)
    request = DummyRequest([])
    request.args = {
        b"team_id": [b"T12345"],
        b"channel_id": [b"C67890"],
        b"text": [b"AFDDMX"],
    }
    bot.dbpool.runInteraction = mock.Mock(return_value=defer.succeed(None))
    result = ss.render(request)
    assert result == NOT_DONE_YET
    yield defer.succeed(None)
    assert b"Subscribed" in b"".join(request.written)


def test_install_channel_render(bot: JabberClient):
    """See if we can render the install channel."""
    ss = SlackInstallChannel(bot)
    request = DummyRequest([b""])
    result = ss.render(request)
    assert result is not None
    assert request.responseCode == 302


@pytest.mark.parametrize("database", ["iembot"])
def test_subscribe_channel(dbcursor, bot):
    """See if we can subscribe?"""
    ss = SlackSubscribeChannel(bot)
    ss.store_slack_subscription(
        dbcursor,
        "TSS",
        "CSD",
        "AFDDMX",
    )


@pytest.mark.parametrize("database", ["iembot"])
def test_gh136_slack_first_channel_subscription(dbcursor, bot):
    """See if subscribe works when we need to create a slack channel."""
    ss = SlackSubscribeChannel(bot)
    ss.store_slack_subscription(
        dbcursor,
        "TSS",  # needs to exist in iembot_slack_teams
        "CSD2",  # new channel on slack unknown to the bot so far
        "AFDDMX",
    )


@pytest.mark.parametrize("database", ["iembot"])
def test_load_from_db(dbcursor, bot: JabberClient):
    """Exercise."""
    load_slack_from_db(dbcursor, bot)


def test_send_to_slack(monkeypatch):
    """Test sending to Slack."""
    posted = {}

    def mock_post(url, headers, data):
        """Mock requests.post"""
        posted["url"] = url
        posted["headers"] = headers
        posted["data"] = data

        class MockResponse:
            """Mock response object."""

            def __init__(self):
                self.content = b'{"ok":true}'

            def raise_for_status(self):
                """Mock raise for status."""

        return MockResponse()

    monkeypatch.setattr(requests, "post", mock_post)

    bot = mock.Mock()
    bot.slack_teams = {"T12345": "xoxb-fake-token"}
    channel_id = "C67890"
    elem = mock.Mock()
    elem.x = {"twitter": "Hello, Slack!"}

    send_to_slack("xoxb-fake-token", channel_id, elem)

    assert posted["url"] == "https://slack.com/api/chat.postMessage"
    assert posted["headers"]["Authorization"] == "Bearer xoxb-fake-token"
    assert posted["headers"]["Content-Type"] == "application/json"
    import json as jsonlib

    data = jsonlib.loads(posted["data"])
    assert data["text"] == "Hello, Slack!"
    assert data["channel"] == channel_id
    assert data["mrkdwn"] is False


def test_install(bot):
    """Test the status renderer."""
    ss = SlackInstallChannel(bot)
    request = mock.Mock()
    request.setResponseCode = mock.Mock()
    request.write = mock.Mock()
    assert ss.render(request) is not None
