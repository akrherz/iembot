"""Exercises Slack related tests."""

from unittest import mock

import pytest
import pytest_twisted
import responses
from twisted.internet import defer
from twisted.web.server import NOT_DONE_YET
from twisted.web.test.requesthelper import DummyRequest
from twisted.words.xish.domish import Element

from iembot.slack import (
    SlackInstallChannel,
    SlackSubscribeChannel,
    load_slack_from_db,
    route,
    send_to_slack,
)
from iembot.types import JabberClient


@pytest_twisted.inlineCallbacks
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


@pytest_twisted.inlineCallbacks
def test_route(bot: JabberClient):
    """Quasi test a route."""
    elem = Element(("jabber:client", "message"))
    elem.x = Element(("", "x"))
    elem.x["twitter"] = "Hello"
    elem["body"] = "Hello, Slack!"

    yield route(
        bot,
        ["XXX"],
        elem,
    )


def test_send_to_slack():
    """Test sending to Slack."""
    elem = Element(("jabber:client", "message"))
    elem.x = Element(("", "x"))
    elem.x["twitter"] = "Hello"
    elem["body"] = "Hello, Slack!"

    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.POST,
            "https://slack.com/api/chat.postMessage",
            status=200,
            body="Hello",
        )
        send_to_slack(
            "Test",
            "XXX",
            elem,
        )


def test_install(bot):
    """Test the status renderer."""
    ss = SlackInstallChannel(bot)
    request = mock.Mock()
    request.setResponseCode = mock.Mock()
    request.write = mock.Mock()
    assert ss.render(request) is not None
