"""Tests, gasp"""
import tempfile
from unittest import mock

# local
import iembot.util as botutil

# Third party modules
import psycopg2
from iembot.basicbot import basicbot
from iembot.iemchatbot import JabberClient
from psycopg2.extras import RealDictCursor
from twisted.python.failure import Failure
from twisted.words.xish.domish import Element
from twitter.error import TwitterError


def test_load_chatlog():
    """Test our pickling fun."""
    bot = JabberClient(None, None, xml_log_path="/tmp")
    bot.PICKLEFILE = tempfile.mkstemp()[1]
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
    bot.processMessageGC(message)
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


def test_load_chatrooms_fromdb():
    """Can we load up chatroom details?"""
    dbconn = psycopg2.connect("dbname=mesosite host=localhost")
    cursor = dbconn.cursor(cursor_factory=RealDictCursor)
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
