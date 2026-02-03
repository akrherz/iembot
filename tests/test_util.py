"""Tests, gasp"""

import os
import tempfile
from unittest import mock

import pytest
from twisted.words.xish.domish import Element

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


@pytest.mark.parametrize("database", ["iembot"])
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
