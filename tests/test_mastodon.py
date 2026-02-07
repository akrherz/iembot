"""Test iembot.mastodon"""

from unittest import mock

import mastodon
import pytest
from twisted.words.xish.domish import Element

from iembot.bot import JabberClient
from iembot.mastodon import (
    disable_mastodon_user,
    load_mastodon_from_db,
    mastodon_errback,
    route,
    toot,
    toot_cb,
)


def test_gh150_route(bot: JabberClient):
    """Can we route a message?"""
    bot.md_routingtable = {
        "XXX": [123],
    }
    bot.md_users = {
        123: {
            "screen_name": "testuser",
            "access_token": "123",
            "api_base_url": "https://localhost",
            "iem_owned": False,
        }
    }
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
    route(bot, ["XXX"], elem)


def test_toot_cb_no_response():
    """Test toot_cb with None response."""
    bot = mock.Mock()
    result = toot_cb(None, bot, "text", "123")
    assert result is None


def test_toot_cb_no_user():
    """Test toot_cb with unknown user."""
    bot = mock.Mock()
    bot.md_users = {}
    result = toot_cb({"content": "test"}, bot, "text", "999")
    assert result == {"content": "test"}


def test_toot_cb_no_content():
    """Test toot_cb with response missing content."""
    bot = mock.Mock()
    bot.md_users = {"123": {"screen_name": "test"}}
    result = toot_cb({"error": "bad"}, bot, "text", "123")
    assert result is None


def test_toot_cb_success():
    """Test toot_cb with successful response."""
    bot = mock.Mock()
    bot.md_users = {"123": {"screen_name": "testuser"}}
    bot.dbpool.runOperation.return_value = mock.Mock()
    response = {
        "content": "test",
        "url": "https://mastodon.social/@test/123",
        "account": {},
    }
    result = toot_cb(response, bot, "text", "123")
    assert result == {
        "content": "test",
        "url": "https://mastodon.social/@test/123",
    }
    bot.dbpool.runOperation.assert_called_once()


@pytest.mark.parametrize("database", ["iembot"])
def test_load_mastodon_from_db(dbcursor):
    """Test the method."""
    bot = JabberClient(None, None)
    load_mastodon_from_db(dbcursor, bot)


def test_util_toot():
    """Test the method."""
    bot = JabberClient(None, None)
    bot.md_users = {
        "123": {
            "screen_name": "iembot",
            "access_token": "123",
            "api_base_url": "https://localhost",
        }
    }
    toot(bot, "123", "test", sleep=0)


def test_mastodon_errback_not_found():
    """Test mastodon_errback with 404 error."""
    bot = mock.Mock()
    bot.md_users = {"123": {"screen_name": "test", "iem_owned": False}}
    bot.dbpool.runOperation.return_value = mock.Mock()
    err = mastodon.errors.MastodonNotFoundError("Not found")
    mastodon_errback(err, bot, "123", "test toot")
    # User should be disabled
    assert "123" not in bot.md_users


def test_mastodon_errback_unauthorized():
    """Test mastodon_errback with 401 error."""
    bot = mock.Mock()
    bot.md_users = {"123": {"screen_name": "test", "iem_owned": False}}
    bot.dbpool.runOperation.return_value = mock.Mock()
    err = mastodon.errors.MastodonUnauthorizedError("Unauthorized")
    mastodon_errback(err, bot, "123", "test toot")
    # User should be disabled
    assert "123" not in bot.md_users


def test_disable_mastodon_user_unknown():
    """Test disable_mastodon_user with unknown user."""
    bot = mock.Mock()
    bot.md_users = {}
    assert disable_mastodon_user(bot, "unknown") is False


def test_disable_mastodon_user_iem_owned():
    """Test disable_mastodon_user with IEM owned account."""
    bot = mock.Mock()
    bot.md_users = {"123": {"screen_name": "iembot", "iem_owned": True}}
    assert disable_mastodon_user(bot, "123") is False


def test_disable_mastodon_user_success():
    """Test disable_mastodon_user with valid user."""
    bot = mock.Mock()
    bot.md_users = {"123": {"screen_name": "testuser", "iem_owned": False}}
    bot.dbpool.runOperation.return_value = mock.Mock()
    result = disable_mastodon_user(bot, "123", errcode=401)
    assert result is True
    assert "123" not in bot.md_users
