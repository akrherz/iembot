"""Test iembot.mastodon"""

import pytest
import pytest_twisted
import responses
from mastodon.errors import MastodonNetworkError
from twisted.words.xish.domish import Element

from iembot.bot import JabberClient
from iembot.mastodon import (
    load_mastodon_from_db,
    really_toot,
    route,
    toot,
)


def test_really_toot_without_known_user(bot: JabberClient):
    """Test a theoretical error."""
    assert really_toot(bot, 0, "Test") is None


def test_route_unknown_user(bot: JabberClient):
    """Test we handle when we have an unknown user."""
    elem = Element(("jabber:client", "message"))
    elem.x = Element(("", "x"))
    elem.x["twitter"] = "test message"
    bot.md_routingtable["YYY"] = [
        4321,
    ]
    route(bot, ["YYY"], elem)


@pytest_twisted.inlineCallbacks
def test_trigger_mastodon_errback(bot: JabberClient):
    """Test that mastodon_errback gets hit, somehow."""
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.POST,
            "https://localhost/api/v1/statuses",
            body="Attempting to provoke MastodonNotFoundError",
            status=404,
        )
        yield toot(bot, 123, "test message", sleep=0)
    assert 123 in bot.md_users


@pytest_twisted.inlineCallbacks
def test_dont_disable_iemowned(bot: JabberClient):
    """Test that oauth tokens are removed in this scenario."""
    bot.md_users[123]["iem_owned"] = True
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.POST,
            "https://localhost/api/v1/statuses",
            body="Your login is currently disabled",
            status=403,
        )
        yield toot(bot, 123, "test message", sleep=0)
    assert 123 in bot.md_users


@pytest_twisted.inlineCallbacks
def test_gh175_disable_mastodon(bot: JabberClient):
    """Test that oauth tokens are removed in this scenario."""
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.POST,
            "https://localhost/api/v1/statuses",
            body="Your login is currently disabled",
            status=403,
        )
        yield toot(bot, 123, "test message", sleep=0)
    assert 123 not in bot.md_users


@pytest_twisted.inlineCallbacks
def test_media_upload(bot: JabberClient):
    """Can we route a message?"""
    extra = {"twitter_media": "http://localhost/bah.png", "sleep": 0}
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            "http://localhost/bah.png",
            body=b"fakeimagecontent",
            status=200,
        )
        rsps.add(
            responses.GET,
            "https://localhost/api/v2/instance/",
            json={
                "version": "4.4.3",
                "api_versions": {"mastodon": 6},
                "domain": "localhost",
            },
            status=200,
        )
        rsps.add(
            responses.POST,
            "https://localhost/api/v1/media",
            json={"id": 12345},
            status=200,
        )
        rsps.add(
            responses.POST,
            "https://localhost/api/v1/statuses",
            json={"id": 67890},
            status=200,
        )
        yield toot(bot, 123, "test message", **extra)


@pytest_twisted.inlineCallbacks
def test_mastodon_unauthorized(bot: JabberClient):
    """Test the errorback chain for an unaccounted for exception."""
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.POST,
            "https://localhost/api/v1/statuses",
            body="",
            status=401,
        )
        yield toot(bot, 123, "test message", sleep=0)
    assert 123 not in bot.md_users


@pytest_twisted.inlineCallbacks
def test_mastodon_rate_limit_error(bot: JabberClient):
    """Test the errorback chain for an unaccounted for exception."""
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.POST,
            "https://localhost/api/v1/statuses",
            body="",
            status=429,
        )
        yield toot(bot, 123, "test message", sleep=0)


@pytest_twisted.inlineCallbacks
def test_gh161_mastodon_network_error(bot: JabberClient):
    """Test an exception path."""
    with responses.RequestsMock() as rsps:
        # Note any exception within requests will be MastodonNetworkError
        rsps.add(
            responses.POST,
            "https://localhost/api/v1/statuses",
            body=MastodonNetworkError("Network error"),
        )
        yield toot(bot, 123, "test message", sleep=0)


def test_gh150_route(bot: JabberClient):
    """Can we route a message?"""
    msgtxt = (
        "BOX continues Cold Weather Advisory valid at Feb 7, 6:00 PM EST for "
        "Barnstable, Central Middlesex County, Dukes, Eastern Essex, Eastern "
        "Norfolk, Eastern Plymouth, Northern Bristol, Northwest Middlesex "
        "County, Southeast Middlesex, Southern Bristol, Southern Plymouth, "
        "Suffolk, Western Essex, Western Norfolk, Western Plymouth [MA] and "
        "Block Island, Bristol, Eastern Kent, Newport, Northwest Providence, "
        "Southeast Providence, Washington, Western Kent [RI] till "
        "Feb 8, 1:00 PM EST "
        "https://iem.local/vtec/f/2026-O-CON-KBOX-CW-Y-0005_2026-02-07T23:00Z"
    )
    elem = Element(("jabber:client", "message"))
    elem.x = Element(("", "x"))
    elem.x["twitter"] = msgtxt
    elem["body"] = msgtxt
    # Duplicated to check the dedup
    del bot.md_users[123]  # Remove user to prevent actual call to Mastodon
    route(bot, ["XXX", "XXX"], elem)


@pytest.mark.parametrize("database", ["iembot"])
def test_load_mastodon_from_db(dbcursor, bot: JabberClient):
    """Test the method."""
    load_mastodon_from_db(dbcursor, bot)


def test_util_toot(bot: JabberClient):
    """Test the method."""
    toot(bot, 123, "test", sleep=0)


def test_route_without_x(bot: JabberClient):
    """Test that we require x."""
    elem = Element(("jabber:client", "message"))
    elem["body"] = "Test Message"
    route(bot, ["XXX"], elem)
