"""test twitter."""

from unittest import mock

from twisted.python.failure import Failure
from twitter import TwitterError

from iembot.twitter import (
    disable_twitter_user,
    safe_twitter_text,
    tweet_cb,
    twitter_errback,
    twittererror_exp_to_code,
)


def test_error_conversion():
    """Test that we can convert errors."""
    err = TwitterError("BLAH")
    assert twittererror_exp_to_code(err) is None
    err = TwitterError(
        "[{'code': 185, 'message': 'User is over daily status update limit.'}]"
    )
    assert twittererror_exp_to_code(err) == 185
    assert twittererror_exp_to_code(Failure(err)) == 185


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
    bot.name = "iembot"
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
    result = tweet_cb({"error": "bad"}, bot, "text", "room", "jid", "123")
    assert result is None


def test_tweet_cb_success():
    """Test tweet_cb with successful response."""
    bot = mock.Mock()
    bot.name = "iembot"
    bot.tw_users = {"123": {"screen_name": "testuser"}}
    bot.dbpool.runOperation.return_value = mock.Mock()
    response = {"data": {"id": "tweet123"}}
    result = tweet_cb(response, bot, "text", "room", "jid", "123")
    assert result == response
    bot.dbpool.runOperation.assert_called_once()


def test_tweet_cb_no_response():
    """Test tweet_cb with None response."""
    bot = mock.Mock()
    result = tweet_cb(None, bot, "text", "room", "jid", "123")
    assert result is None


def test_tweet_cb_no_user():
    """Test tweet_cb with unknown user."""
    bot = mock.Mock()
    bot.tw_users = {}
    result = tweet_cb(
        {"data": {"id": "123"}}, bot, "text", "room", "jid", "999"
    )
    assert result == {"data": {"id": "123"}}


def test_twitter_errback_disable_code():
    """Test twitter_errback with disable code."""
    bot = mock.Mock()
    bot.tw_users = {"123": {"screen_name": "test", "iem_owned": False}}
    bot.dbpool.runOperation.return_value = mock.Mock()
    err = TwitterError("[{'code': 89, 'message': 'Expired token'}]")
    twitter_errback(err, bot, "123", "test tweet")
    # User should be disabled
    assert "123" not in bot.tw_users


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
