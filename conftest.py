"""Centralized Testing Stuff."""

from collections import defaultdict

import pytest
from pyiem.database import get_dbconnc

from iembot.bot import JabberClient


@pytest.fixture
def bot():
    """A bot."""
    iembot = JabberClient("iembot", None, xml_log_path="/tmp")
    iembot.config = defaultdict(str)
    return iembot


@pytest.fixture
def dbcursor(database):
    """Yield a cursor for the given database."""
    dbconn, cursor = get_dbconnc(database, user="mesonet")
    yield cursor
    dbconn.close()
