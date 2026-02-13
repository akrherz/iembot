"""test twitter."""

from unittest import mock

import pytest
import pytest_twisted
import responses
from twisted.words.xish.domish import Element

from iembot.twitter import (
    disable_twitter_user,
    load_twitter_from_db,
    really_tweet,
    route,
    safe_twitter_text,
    tweet,
    tweet_cb,
)
from iembot.types import JabberClient

IEM_MESOPLOT_URL = "https://mesonet.agron.iastate.edu/data/mesonet.gif"


def test_media_upload_failure(bot: JabberClient):
    """Test that we gracefully handle a twitter media upload failure."""
    xtra = {
        "twitter_media": "http://localhost/bah.gif",
        "sleep": 0,
    }
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            url="http://localhost/bah.gif",
            body=b"fake image data",
            status=200,
        )
        rsps.add(
            responses.POST,
            url="https://api.x.com/2/media/upload",
            json={"error": "media type unrecognized"},
            status=400,
        )
        rsps.add(
            responses.POST,
            url="https://api.x.com/2/tweets",
            json={
                "status": 999,
            },
            status=502,
        )
        assert really_tweet(bot, 123, "This is a test", **xtra) is None


def test_gh163_unhandled_twitter_error(bot: JabberClient):
    """Test that we reach a code path for unhandled errors."""
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.POST,
            url="https://api.x.com/2/tweets",
            json={
                "status": 999,
            },
            status=502,
        )
        assert really_tweet(bot, 123, "This is a test", sleep=0) is None


def test_gh163_duplicate_content_403(bot: JabberClient):
    """Test the handling of a 403 status."""
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.POST,
            url="https://api.x.com/2/tweets",
            json={
                "detail": (
                    "You are not allowed to create a Tweet "
                    "with duplicate content."
                ),
                "type": "about:blank",
                "title": "Forbidden",
                "status": 403,
            },
            status=403,
        )
        assert really_tweet(bot, 123, "This is a test") is None


def test_route_without_x(bot: JabberClient):
    """Test route with message missing x element."""
    elem = Element(("jabber:client", "message"))
    elem["body"] = "This is a test"
    assert route(bot, ["XXX"], elem) is None


@pytest.mark.parametrize("database", ["iembot"])
def test_load_twitter_from_db(dbcursor, bot: JabberClient):
    """Test loading config."""
    load_twitter_from_db(dbcursor, bot)


@pytest.mark.parametrize("rescode", [401, 403])
@pytest_twisted.inlineCallbacks
def test_tweet_gh154_twitter(bot: JabberClient, rescode: int):
    """Test the handling of a 401 or 403 response from twitter."""
    elem = Element(("jabber:client", "message"))
    elem.x = Element(("", "x"))
    elem.x["twitter"] = "This is a test"
    elem["body"] = "This is a test"

    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.POST,
            url="https://api.x.com/2/tweets",
            json={
                "title": "Unauthorized",
                # Goosing here, yuck
                "type": "about:blank" if rescode == 401 else "Bahl/suspended",
                "status": rescode,
                "detail": "Unauthorized",
            },
            status=rescode,
        )
        route(
            bot,
            [
                "XXX",
            ],
            elem,
        )
        yield tweet(bot, 123, "This is a test")
        assert 123 not in bot.tw_users


@pytest_twisted.inlineCallbacks
def test_tweet(bot: JabberClient):
    """Test that we can sort of tweet."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            url=IEM_MESOPLOT_URL,
            body=b"fake image data",
            status=200,
        )
        rsps.add(
            responses.POST,
            url="https://api.x.com/2/media/upload",
            json={"data": {"id": "1234567890"}},
        )
        rsps.add(
            responses.POST,
            url="https://api.x.com/2/tweets",
            json={"data": {"id": "1234567890"}},
        )
        result = yield tweet(
            bot,
            123,
            "This is a test",
            twitter_media=IEM_MESOPLOT_URL,
        )
        assert result["data"]["id"] == "1234567890"


def test_disable_twitter_user_unknown():
    """Test disable_twitter_user with unknown user."""
    bot = mock.Mock()
    bot.tw_users = {}
    assert disable_twitter_user(bot, "unknown") is False


def test_disable_twitter_user_iem_owned():
    """Test disable_twitter_user with IEM owned account."""
    bot = mock.Mock()
    bot.tw_users = {"123": {"screen_name": "iembot", "iem_owned": True}}
    assert disable_twitter_user(bot, "123") is False


def test_disable_twitter_user_success():
    """Test disable_twitter_user with valid user."""
    bot = mock.Mock()
    bot.tw_users = {"123": {"screen_name": "testuser", "iem_owned": False}}
    bot.dbpool.runOperation.return_value = mock.Mock()
    result = disable_twitter_user(bot, "123", errcode=185)
    assert result is True
    assert "123" not in bot.tw_users


def test_tweettext():
    """Are we doing the right thing here"""
    msgin = (
        "At 1:30 PM, 1 WNW Lake Mills [Winnebago Co, IA] TRAINED "
        "SPOTTER reports TSTM WND GST of E61 MPH. SPOTTER MEASURED "
        "61 MPH WIND GUST. HIS CAR DOOR WAS ALSO CAUGHT BY THE WIND "
        "WHEN HE WAS OPENING THE DOOR, PUSHING THE DOOR INTO HIS FACE. "
        "THIS CONTACT BR.... "
        "https://iem.local/lsr/#DMX/201807041830/201807041830"
    )
    msgout = safe_twitter_text(msgin)
    assert msgout == msgin


def test_tweet_unescape():
    """Test that we remove html entities from string."""
    msg = "Hail &gt; 2.0 INCHES"
    ans = "Hail > 2.0 INCHES"
    assert safe_twitter_text(msg) == ans


def test_tweet_cb_no_data():
    """Test tweet_cb with response missing data."""
    bot = mock.Mock()
    bot.tw_users = {"123": {"screen_name": "test"}}
    result = tweet_cb({"error": "bad"}, bot, "text", "jid", "123")
    assert result is None


def test_tweet_cb_success():
    """Test tweet_cb with successful response."""
    bot = mock.Mock()
    bot.tw_users = {"123": {"screen_name": "testuser"}}
    bot.dbpool.runOperation.return_value = mock.Mock()
    response = {"data": {"id": "tweet123"}}
    result = tweet_cb(response, bot, "text", "jid", "123")
    assert result == response
    bot.dbpool.runOperation.assert_called_once()


def test_tweet_cb_no_response():
    """Test tweet_cb with None response."""
    bot = mock.Mock()
    result = tweet_cb(None, bot, "text", "jid", "123")
    assert result is None


def test_tweet_cb_no_user():
    """Test tweet_cb with unknown user."""
    bot = mock.Mock()
    bot.tw_users = {}
    result = tweet_cb({"data": {"id": "123"}}, bot, "text", "jid", "999")
    assert result == {"data": {"id": "123"}}


def test_twittertext():
    """Tricky stuff when URLs are included"""
    msg = (
        "Tropical Storm #Danny Intermediate ADVISORY 23A issued. "
        "Outer rainbands spreading across the southern leeward "
        "islands. http://go.usa.gov/W3H"
    )
    msg2 = safe_twitter_text(msg)
    assert msg2 == (
        "Tropical Storm #Danny Intermediate ADVISORY 23A "
        "issued. Outer rainbands spreading across the "
        "southern leeward islands. http://go.usa.gov/W3H"
    )


def test_safe_twitter_text_long_with_url():
    """Test safe_twitter_text with long text and URL."""
    url = "https://example.com/very/long/path"
    # Create a message that's over the limit
    msg = "A" * 300 + " " + url
    result = safe_twitter_text(msg)
    assert url in result
    assert "..." in result


def test_safe_twitter_text_sections():
    """Test safe_twitter_text with for/till pattern."""
    url = "https://example.com/alert"
    msg = (
        "Tornado Warning for Very Long County Name and Another County Name "
        "till 3:00 PM CDT " + url
    )
    result = safe_twitter_text(msg)
    assert url in result


def test_safe_twitter_text_double_spaces():
    """Test safe_twitter_text removes double spaces."""
    msg = "Hello  World   Test"
    result = safe_twitter_text(msg)
    assert result == "Hello World Test"


def test_safe_twitter_text_no_url():
    """Test safe_twitter_text with no URL and under limit."""
    msg = "Short message without URL"
    result = safe_twitter_text(msg)
    assert result == msg


def test_safe_twitter_text_url_only_counts_25():
    """Test that URL counts as 25 chars for limit calculation."""
    # 250 chars + 25 for URL = 275, under 280
    msg = "A" * 250 + " https://example.com"
    result = safe_twitter_text(msg)
    assert result == msg
