"""Test iembot.webhooks"""

import pytest
import pytest_twisted
from twisted.words.xish.domish import Element

from iembot.bot import JabberClient
from iembot.webhooks import (
    load_webhooks_from_db,
    route,
)


@pytest.mark.parametrize("database", ["iembot"])
def test_load_webhooks_from_db(dbcursor, bot: JabberClient):
    """Test loading config."""
    load_webhooks_from_db(dbcursor, bot)


@pytest_twisted.inlineCallbacks
def test_route(bot: JabberClient):
    """Can we route a message?"""
    bot.webhooks_routingtable["XXX"] = "http://localhost"
    elem = Element(("jabber:client", "message"))
    elem["body"] = "Test Message"

    # Le Sigh
    yield route(
        bot,
        [
            "XXX",
        ],
        elem,
    )
