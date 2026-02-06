"""Memcache client helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pymemcache.client.base import Client as MemcacheClient
from twisted.internet import threads
from twisted.python import log

if TYPE_CHECKING:
    from twisted.internet.defer import Deferred


def parse_memcache_addr(memcache: str) -> tuple[str, int]:
    """Glean things from user provided string into memcache addressing."""
    memcache = memcache.removeprefix("tcp:")
    host = memcache
    port = 11211
    if ":" in memcache:
        host, port_str = memcache.rsplit(":", 1)
        try:
            port = int(port_str)
        except ValueError:
            log.msg("Failed to parse memcache port, using default 11211")
    if not host:
        host = "localhost"
    return host, port


class ThreadedMemcacheClient:
    """A memcache client that runs in a thread."""

    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port

    def get(self, key: bytes) -> Deferred:
        """Return a deferred for the memcache fetch."""

        def _get() -> bytes | None:
            client = MemcacheClient((self._host, self._port))
            try:
                return client.get(key)
            finally:
                try:
                    client.close()
                except Exception as exp:
                    log.err(exp)

        return threads.deferToThread(_get)


def build_memcache_client(memcache: str = "") -> ThreadedMemcacheClient:
    """Create a memcache client from user provided conn string."""
    host, port = parse_memcache_addr(memcache)
    return ThreadedMemcacheClient(host, port)
