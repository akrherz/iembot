"""Centralized Testing Stuff."""

import random
import sys
from collections import defaultdict
from unittest import mock

import pytest
from pyiem.database import get_dbconnc
from twisted.python import log

from iembot.bot import JabberClient

log.startLogging(sys.stdout)


@pytest.fixture
def bot():
    """A bot."""
    iembot = JabberClient(f"iembot_{random.randint(0, 1000000)}", mock.Mock())
    # Mastodon Stuff
    iembot.md_routingtable = {
        "XXX": [123],
    }
    iembot.md_users = {
        123: {
            "screen_name": "testuser",
            "access_token": "123",
            "api_base_url": "https://localhost",
            "iem_owned": False,
        }
    }

    iembot.config = defaultdict(str)
    iembot.xmlstream = mock.Mock()
    return iembot


@pytest.fixture
def dbcursor(database):
    """Yield a cursor for the given database."""
    dbconn, cursor = get_dbconnc(database, user="mesonet")
    yield cursor
    dbconn.close()
