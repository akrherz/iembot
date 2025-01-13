"""Centralized Testing Stuff."""

# third party
import pytest
from pyiem.database import get_dbconnc

from iembot.basicbot import basicbot


@pytest.fixture()
def bot():
    """A basicbot."""
    return basicbot("iembot", None, xml_log_path="/tmp")


@pytest.fixture()
def dbcursor(database):
    """Yield a cursor for the given database."""
    dbconn, cursor = get_dbconnc(database, user="mesonet")
    yield cursor
    dbconn.close()
