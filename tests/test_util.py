"""Tests, gasp"""
from unittest import mock

# Third party modules
import psycopg2
from twitter.error import TwitterError

# local
import iembot.util as botutil
from iembot.basicbot import basicbot


def test_error_conversion():
    """Test that we can convert errors."""
    err = TwitterError("BLAH")
    assert botutil.twittererror_exp_to_code(err) is None
    err = TwitterError(
        "[{'code': 185, 'message': 'User is over daily status update limit.'}]"
    )
    assert botutil.twittererror_exp_to_code(err) == 185


def test_load_chatrooms_fromdb():
    """Can we load up chatroom details?"""
    dbconn = psycopg2.connect("dbname=mesosite host=localhost")
    cursor = dbconn.cursor()
    bot = mock.Mock()
    bot.name = "iembot"
    bot.rooms = {}
    botutil.load_chatrooms_from_db(cursor, bot, True)
    assert bot


def test_daily_timestamp():
    """Does the daily timestamp algo return a deferred."""
    bot = basicbot(None, None, xml_log_path="/tmp")
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
