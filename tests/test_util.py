"""Tests, gasp"""

import os
import tempfile
from unittest import mock

import pytest
from twisted.python.failure import Failure
from twisted.words.xish.domish import Element
from twitter.error import TwitterError

import iembot.util as botutil
from iembot.bot import JabberClient
from iembot.msghandlers import process_groupchat


def test_remove_control_characters():
    """Test remove_control_characters function."""
    # Test control characters are removed
    assert botutil.remove_control_characters("hello\x00world") == "helloworld"
    assert botutil.remove_control_characters("test\x07data") == "testdata"
    assert botutil.remove_control_characters("clean text") == "clean text"
    # Tab and newline should be preserved (not in the removed range)
    assert botutil.remove_control_characters("tab\there") == "tab\there"


def test_at_send_message_unknown_user():
    """Test at_send_message with unknown user."""
    bot = mock.Mock()
    bot.tw_users = {}
    # Should not raise an error
    botutil.at_send_message(bot, "unknown_user", "test message")


def test_at_send_message_no_handle():
    """Test at_send_message with user that has no at_handle."""
    bot = mock.Mock()
    bot.tw_users = {"123": {"at_handle": None}}
    # Should not raise an error
    botutil.at_send_message(bot, "123", "test message")


def test_at_send_message_with_handle():
    """Test at_send_message with valid at_handle."""
    bot = mock.Mock()
    bot.tw_users = {"123": {"at_handle": "test.bsky.social"}}
    botutil.at_send_message(bot, "123", "test message", extra_key="value")
    bot.at_manager.submit.assert_called_once_with(
        "test.bsky.social", {"msg": "test message", "extra_key": "value"}
    )


def test_disable_twitter_user_unknown():
    """Test disable_twitter_user with unknown user."""
    bot = mock.Mock()
    bot.tw_users = {}
    assert botutil.disable_twitter_user(bot, "unknown") is False


def test_disable_twitter_user_iem_owned():
    """Test disable_twitter_user with IEM owned account."""
    bot = mock.Mock()
    bot.tw_users = {"123": {"screen_name": "iembot", "iem_owned": True}}
    assert botutil.disable_twitter_user(bot, "123") is False


def test_disable_twitter_user_success():
    """Test disable_twitter_user with valid user."""
    bot = mock.Mock()
    bot.name = "iembot"
    bot.tw_users = {"123": {"screen_name": "testuser", "iem_owned": False}}
    bot.dbpool.runOperation.return_value = mock.Mock()
    result = botutil.disable_twitter_user(bot, "123", errcode=185)
    assert result is True
    assert "123" not in bot.tw_users


def test_disable_mastodon_user_unknown():
    """Test disable_mastodon_user with unknown user."""
    bot = mock.Mock()
    bot.md_users = {}
    assert botutil.disable_mastodon_user(bot, "unknown") is False


def test_disable_mastodon_user_iem_owned():
    """Test disable_mastodon_user with IEM owned account."""
    bot = mock.Mock()
    bot.md_users = {"123": {"screen_name": "iembot", "iem_owned": True}}
    assert botutil.disable_mastodon_user(bot, "123") is False


def test_disable_mastodon_user_success():
    """Test disable_mastodon_user with valid user."""
    bot = mock.Mock()
    bot.name = "iembot"
    bot.md_users = {"123": {"screen_name": "testuser", "iem_owned": False}}
    bot.dbpool.runOperation.return_value = mock.Mock()
    result = botutil.disable_mastodon_user(bot, "123", errcode=401)
    assert result is True
    assert "123" not in bot.md_users


def test_purge_logs(tmp_path):
    """Test purge_logs function."""
    bot = mock.Mock()
    bot.config = {"bot.purge_xmllog_days": "1"}
    # Create a temporary log directory
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    # Create an old log file that should be deleted
    old_log = log_dir / "xmllog.2020_01_01"
    old_log.touch()
    # Create a recent log file that should be kept
    recent_log = log_dir / "xmllog.2099_01_01"
    recent_log.touch()

    # Change to temp directory so glob works
    orig_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        botutil.purge_logs(bot)
        assert not old_log.exists()
        assert recent_log.exists()
    finally:
        os.chdir(orig_cwd)


def test_channels_room_list():
    """Test channels_room_list."""
    bot = mock.Mock()
    bot.routingtable = {
        "ABC": ["room1", "room2"],
        "DEF": ["room1"],
        "GHI": ["room3"],
    }
    botutil.channels_room_list(bot, "room1")
    bot.send_groupchat.assert_called_once()
    call_args = bot.send_groupchat.call_args
    assert "room1" in call_args[0][0]
    assert "2 channels" in call_args[0][1]


def test_safe_twitter_text_long_with_url():
    """Test safe_twitter_text with long text and URL."""
    url = "https://example.com/very/long/path"
    # Create a message that's over the limit
    msg = "A" * 300 + " " + url
    result = botutil.safe_twitter_text(msg)
    assert url in result
    assert "..." in result


def test_safe_twitter_text_sections():
    """Test safe_twitter_text with for/till pattern."""
    url = "https://example.com/alert"
    msg = (
        "Tornado Warning for Very Long County Name and Another County Name "
        "till 3:00 PM CDT " + url
    )
    result = botutil.safe_twitter_text(msg)
    assert url in result


def test_safe_twitter_text_double_spaces():
    """Test safe_twitter_text removes double spaces."""
    msg = "Hello  World   Test"
    result = botutil.safe_twitter_text(msg)
    assert result == "Hello World Test"


def test_safe_twitter_text_no_url():
    """Test safe_twitter_text with no URL and under limit."""
    msg = "Short message without URL"
    result = botutil.safe_twitter_text(msg)
    assert result == msg


def test_safe_twitter_text_url_only_counts_25():
    """Test that URL counts as 25 chars for limit calculation."""
    # 250 chars + 25 for URL = 275, under 280
    msg = "A" * 250 + " https://example.com"
    result = botutil.safe_twitter_text(msg)
    assert result == msg


def test_twitter_errback_disable_code():
    """Test twitter_errback with disable code."""
    bot = mock.Mock()
    bot.tw_users = {"123": {"screen_name": "test", "iem_owned": False}}
    bot.dbpool.runOperation.return_value = mock.Mock()
    err = TwitterError("[{'code': 89, 'message': 'Expired token'}]")
    botutil.twitter_errback(err, bot, "123", "test tweet")
    # User should be disabled
    assert "123" not in bot.tw_users


def test_twitter_errback_other_error():
    """Test twitter_errback with non-disable error."""
    bot = mock.Mock()
    bot.tw_users = {"456": {"screen_name": "test", "iem_owned": False}}
    err = TwitterError("Some other error")
    with mock.patch.object(botutil, "email_error") as mock_email:
        botutil.twitter_errback(err, bot, "456", "test tweet")
    # User should still exist
    assert "456" in bot.tw_users
    # email_error should have been called
    mock_email.assert_called_once()


def test_mastodon_errback_not_found():
    """Test mastodon_errback with 404 error."""
    import mastodon

    bot = mock.Mock()
    bot.md_users = {"123": {"screen_name": "test", "iem_owned": False}}
    bot.dbpool.runOperation.return_value = mock.Mock()
    err = mastodon.errors.MastodonNotFoundError("Not found")
    botutil.mastodon_errback(err, bot, "123", "test toot")
    # User should be disabled
    assert "123" not in bot.md_users


def test_mastodon_errback_unauthorized():
    """Test mastodon_errback with 401 error."""
    import mastodon

    bot = mock.Mock()
    bot.md_users = {"123": {"screen_name": "test", "iem_owned": False}}
    bot.dbpool.runOperation.return_value = mock.Mock()
    err = mastodon.errors.MastodonUnauthorizedError("Unauthorized")
    botutil.mastodon_errback(err, bot, "123", "test toot")
    # User should be disabled
    assert "123" not in bot.md_users


def test_tweet_cb_no_response():
    """Test tweet_cb with None response."""
    bot = mock.Mock()
    result = botutil.tweet_cb(None, bot, "text", "room", "jid", "123")
    assert result is None


def test_tweet_cb_no_user():
    """Test tweet_cb with unknown user."""
    bot = mock.Mock()
    bot.tw_users = {}
    result = botutil.tweet_cb(
        {"data": {"id": "123"}}, bot, "text", "room", "jid", "999"
    )
    assert result == {"data": {"id": "123"}}


def test_tweet_cb_no_data():
    """Test tweet_cb with response missing data."""
    bot = mock.Mock()
    bot.tw_users = {"123": {"screen_name": "test"}}
    result = botutil.tweet_cb(
        {"error": "bad"}, bot, "text", "room", "jid", "123"
    )
    assert result is None


def test_tweet_cb_success():
    """Test tweet_cb with successful response."""
    bot = mock.Mock()
    bot.name = "iembot"
    bot.tw_users = {"123": {"screen_name": "testuser"}}
    bot.dbpool.runOperation.return_value = mock.Mock()
    response = {"data": {"id": "tweet123"}}
    result = botutil.tweet_cb(response, bot, "text", "room", "jid", "123")
    assert result == response
    bot.dbpool.runOperation.assert_called_once()


def test_toot_cb_no_response():
    """Test toot_cb with None response."""
    bot = mock.Mock()
    result = botutil.toot_cb(None, bot, "text", "room", "jid", "123")
    assert result is None


def test_toot_cb_no_user():
    """Test toot_cb with unknown user."""
    bot = mock.Mock()
    bot.md_users = {}
    result = botutil.toot_cb(
        {"content": "test"}, bot, "text", "room", "jid", "999"
    )
    assert result == {"content": "test"}


def test_toot_cb_no_content():
    """Test toot_cb with response missing content."""
    bot = mock.Mock()
    bot.md_users = {"123": {"screen_name": "test"}}
    result = botutil.toot_cb(
        {"error": "bad"}, bot, "text", "room", "jid", "123"
    )
    assert result is None


def test_toot_cb_success():
    """Test toot_cb with successful response."""
    bot = mock.Mock()
    bot.name = "iembot"
    bot.md_users = {"123": {"screen_name": "testuser"}}
    bot.dbpool.runOperation.return_value = mock.Mock()
    response = {
        "content": "test",
        "url": "https://mastodon.social/@test/123",
        "account": {},
    }
    result = botutil.toot_cb(response, bot, "text", "room", "jid", "123")
    assert result == {
        "content": "test",
        "url": "https://mastodon.social/@test/123",
    }
    bot.dbpool.runOperation.assert_called_once()


@pytest.mark.parametrize("database", ["mesosite"])
def test_load_mastodon_from_db(dbcursor):
    """Test the method."""
    # create some faked entries
    dbcursor.execute(
        """
        insert into iembot_mastodon_apps(server, client_id, client_secret)
        values('localhost', '123', '123') RETURNING id
        """
    )
    appid = dbcursor.fetchone()["id"]
    dbcursor.execute(
        """
        insert into iembot_mastodon_oauth(appid, screen_name, access_token,
        iem_owned, disabled) values (%s, 'iembot', '123', 't', 'f')
        returning id
        """,
        (appid,),
    )
    userid = dbcursor.fetchone()["id"]
    dbcursor.execute(
        """
        insert into iembot_mastodon_subs(user_id, channel) values (%s, 'ABC')
        """,
        (userid,),
    )
    bot = JabberClient(None, None, xml_log_path="/tmp")
    botutil.load_mastodon_from_db(dbcursor, bot)
    assert bot.md_users[userid]["screen_name"] == "iembot"

    # Now disable the user
    dbcursor.execute(
        """
        update iembot_mastodon_oauth SET disabled = 't' where id = %s
        """,
        (userid,),
    )
    botutil.load_mastodon_from_db(dbcursor, bot)
    assert userid not in bot.md_users


def test_util_toot():
    """Test the method."""
    bot = JabberClient(None, None, xml_log_path="/tmp")
    bot.md_users = {
        "123": {
            "screen_name": "iembot",
            "access_token": "123",
            "api_base_url": "https://localhost",
        }
    }
    botutil.toot(bot, "123", "test", sleep=0)


def test_load_chatlog():
    """Test our pickling fun."""
    bot = JabberClient("test", None, xml_log_path="/tmp")
    bot.picklefile = tempfile.mkstemp()[1]
    bot.save_chatlog()
    botutil.load_chatlog(bot)
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
    botutil.load_chatlog(bot)
    assert bot.seqnum == 1


def test_error_conversion():
    """Test that we can convert errors."""
    err = TwitterError("BLAH")
    assert botutil.twittererror_exp_to_code(err) is None
    err = TwitterError(
        "[{'code': 185, 'message': 'User is over daily status update limit.'}]"
    )
    assert botutil.twittererror_exp_to_code(err) == 185
    assert botutil.twittererror_exp_to_code(Failure(err)) == 185


@pytest.mark.parametrize("database", ["mesosite"])
def test_load_chatrooms_fromdb(dbcursor):
    """Can we load up chatroom details?"""
    bot = mock.Mock()
    bot.name = "iembot"
    bot.rooms = {}
    botutil.load_chatrooms_from_db(dbcursor, bot, True)
    assert bot


def test_daily_timestamp():
    """Does the daily timestamp algo return a deferred."""
    bot = JabberClient(None, None, xml_log_path="/tmp")
    assert botutil.daily_timestamp(bot) is not None


def test_htmlentites():
    """Do replacements work?"""
    assert botutil.htmlentities("<") == "&lt;"
    assert botutil.htmlentities("<>") == "&lt;&gt;"


def test_tweet_unescape():
    """Test that we remove html entities from string."""
    msg = "Hail &gt; 2.0 INCHES"
    ans = "Hail > 2.0 INCHES"
    assert botutil.safe_twitter_text(msg) == ans


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
    msgout = botutil.safe_twitter_text(msgin)
    assert msgout == msgin
