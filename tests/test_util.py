"""Tests, gasp"""

import tempfile
from unittest import mock

# Third party modules
import pytest
from twisted.python.failure import Failure
from twisted.words.xish.domish import Element
from twitter.error import TwitterError

# local
import iembot.util as botutil
from iembot.basicbot import BasicBot
from iembot.iemchatbot import JabberClient


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
    bot = BasicBot(None, None, xml_log_path="/tmp")
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
