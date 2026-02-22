"""Test iembot.webhooks"""

import pytest
import responses
from requests import HTTPError
from twisted.words.xish.domish import Element

from iembot.bot import JabberClient
from iembot.webhooks import (
    load_webhooks_from_db,
    really_hook,
    route,
)


@pytest.mark.parametrize("database", ["iembot"])
def test_load_webhooks_from_db(dbcursor, bot: JabberClient):
    """Test loading config."""
    load_webhooks_from_db(dbcursor, bot)


def test_route(bot: JabberClient):
    """Can we route a message?"""
    bot.webhooks_routingtable["XXX"] = ["http://localhost", "http://localhost"]
    elem = Element(("jabber:client", "message"))
    elem["body"] = "Test Message"
    route(
        bot,
        ["XXX", "YYY"],
        elem,
        sleep=0,
    )


def test_route_no_subs(bot: JabberClient):
    """Can we route a message without any subscriptions?"""
    elem = Element(("jabber:client", "message"))
    elem["body"] = "Test Message"
    route(
        bot,
        ["QQQ"],
        elem,
        sleep=0,
    )


def test_really_hook():
    """Can we route a message?"""
    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, "http://localhost", status=200)
        # Le Sigh
        really_hook(
            "http://localhost",
            b"Test Message",
            sleep=0,
        )


def test_really_hook_failures():
    """Can we route a message?"""
    with responses.RequestsMock() as rsps:
        rsps.add(responses.POST, "http://localhost", status=500)
        # Le Sigh
        with pytest.raises(HTTPError):
            really_hook(
                "http://localhost",
                b"Test Message",
                sleep=0,
            )
