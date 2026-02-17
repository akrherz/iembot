"""Tests, gasp"""

from unittest import mock

import pytest
from twisted.words.xish.domish import Element

from iembot.bot import JabberClient
from iembot.msghandlers import process_groupchat
from iembot.util import (
    channels_room_list,
    daily_timestamp,
    htmlentities,
    load_chatlog,
    load_chatrooms_from_db,
    remove_control_characters,
    safe_twitter_text,
)


def test_theoretical_unfixable_text():
    """Test what happens with this scenario."""
    msg = "A" * 100 + " http://localhost http://localhost2"
    ans = "AAAAAAAAAAAAAAAAAAAAAAAAA... http://localhost2"
    assert safe_twitter_text(msg, 50) == ans


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


def test_safe_twitter_text_long_with_url():
    """Test safe_twitter_text with long text and URL."""
    url = "https://example.com/very/long/path"
    # Create a message that's over the limit
    msg = "A" * 300 + " " + url
    result = safe_twitter_text(msg)
    assert url in result
    assert "..." in result


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


def test_remove_control_characters():
    """Test remove_control_characters function."""
    # Test control characters are removed
    assert remove_control_characters("hello\x00world") == "helloworld"
    assert remove_control_characters("test\x07data") == "testdata"
    assert remove_control_characters("clean text") == "clean text"
    # Tab and newline should be preserved (not in the removed range)
    assert remove_control_characters("tab\there") == "tab\there"


def test_channels_room_list():
    """Test channels_room_list."""
    bot = mock.Mock()
    bot.routingtable = {
        "ABC": ["room1", "room2"],
        "DEF": ["room1"],
        "GHI": ["room3"],
    }
    channels_room_list(bot, "room1")
    bot.send_groupchat.assert_called_once()
    call_args = bot.send_groupchat.call_args
    assert "room1" in call_args[0][0]
    assert "2 channels" in call_args[0][1]


def test_load_chatlog(tmp_path, bot: JabberClient):
    """Test our pickling fun."""
    print(bot.seqnum)
    bot.picklefile = tmp_path / "chatlog.pkl"
    bot.save_chatlog()
    load_chatlog(bot)
    assert bot.seqnum == 0

    # Create a faked message
    message = Element(("jabber:client", "message"))
    message["from"] = f"lotchat@{bot.conference}/iembot"
    message["type"] = "groupchat"
    message.addElement("body", None, "Hello World")
    xelem = message.addElement("x", "nwschat:nwsbot")
    xelem["channels"] = "ABC"
    process_groupchat(bot, message)
    bot.save_chatlog()
    load_chatlog(bot)
    assert bot.seqnum == 1


@pytest.mark.parametrize("database", ["iembot"])
def test_load_chatrooms_fromdb(dbcursor):
    """Can we load up chatroom details?"""
    bot = mock.Mock()
    bot.rooms = {}
    load_chatrooms_from_db(dbcursor, bot, True)
    assert bot


def test_daily_timestamp(bot: JabberClient):
    """Does the daily timestamp algo return a deferred."""
    assert daily_timestamp(bot) is not None


def test_htmlentites():
    """Do replacements work?"""
    assert htmlentities("<") == "&lt;"
    assert htmlentities("<>") == "&lt;&gt;"
