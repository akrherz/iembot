"""Centralized Testing Stuff."""

import random
from collections import defaultdict
from unittest import mock

import pytest
from pyiem.database import get_dbconnc

from iembot.bot import JabberClient


@pytest.fixture
def bot():
    """A bot."""
    iembot = JabberClient(f"iembot_{random.randint(0, 1000000)}", mock.Mock())
    iembot.config = defaultdict(str)
    iembot.xmlstream = mock.Mock()
    return iembot


@pytest.fixture
def dbcursor(database):
    """Yield a cursor for the given database."""
    dbconn, cursor = get_dbconnc(database, user="mesonet")
    yield cursor
    dbconn.close()
