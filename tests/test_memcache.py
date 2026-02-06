"""Test things in iembot.memcache."""

import random

import pytest_twisted

from iembot.memcache import (
    build_memcache_client,
    parse_memcache_addr,
)


@pytest_twisted.inlineCallbacks
def test_client_disconnect_failure(monkeypatch):
    """Test the logic around handling a disconnect failure."""
    client = build_memcache_client("")
    errors: list[Exception] = []

    def _log_err(exp):
        errors.append(exp)

    class FakeClient:
        def __init__(self, _addr):
            pass

        def get(self, _key):
            return None

        def close(self):
            raise RuntimeError("Failed to close memcache client")

    monkeypatch.setattr("iembot.memcache.MemcacheClient", FakeClient)
    monkeypatch.setattr("iembot.memcache.log.err", _log_err)

    result = yield client.get(b"dontmatter")
    assert result is None
    assert errors


@pytest_twisted.inlineCallbacks
def test_e2e():
    """Test our lifecycle of memcache client."""
    client = build_memcache_client()
    result = yield client.get(
        f"shouldnt_exist_{random.randint(0, 100000)}".encode("ascii")
    )
    assert result is None


def test_parse_memcache_addr():
    """Test parse_memcache_addr."""
    assert parse_memcache_addr("tcp:localhost") == ("localhost", 11211)
    assert parse_memcache_addr("tcp:localhost:12345") == ("localhost", 12345)
    assert parse_memcache_addr("tcp:") == ("localhost", 11211)
    assert parse_memcache_addr("tcp:exa.com:abc") == ("exa.com", 11211)
    assert parse_memcache_addr("tcp:exa.com:abc") == ("exa.com", 11211)
