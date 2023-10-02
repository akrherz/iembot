"""Centralized Testing Stuff."""

# third party
import pytest
from iembot.basicbot import basicbot
from pyiem.database import get_dbconnc


@pytest.fixture()
def bot():
    """A basicbot."""
    return basicbot("iembot", None, xml_log_path="/tmp")


@pytest.fixture()
def dbcursor(database):
    """Yield a cursor for the given database."""
    dbconn, cursor = get_dbconnc(database)
    yield cursor
    dbconn.close()
