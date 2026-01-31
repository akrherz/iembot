"""Centralized Testing Stuff."""

from collections import defaultdict

import pytest
from pyiem.database import get_dbconnc

from iembot.basicbot import BasicBot


@pytest.fixture
def bot():
    """A basicbot."""
    iembot = BasicBot("iembot", None, xml_log_path="/tmp")
    iembot.config = defaultdict(str)
    return iembot


@pytest.fixture
def dbcursor(database):
    """Yield a cursor for the given database."""
    dbconn, cursor = get_dbconnc(database, user="mesonet")
    yield cursor
    dbconn.close()
