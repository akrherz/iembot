"""Memcache client helpers."""

from __future__ import annotations

from pymemcache.client.base import Client as MemcacheClient
from twisted.internet import threads


def parse_memcache_addr(memcache: str) -> tuple[str, int]:
    """."""
    memcache = memcache.removeprefix("tcp:")
    host = memcache
    port = 11211
    if ":" in memcache:
        host, port_str = memcache.rsplit(":", 1)
        try:
            port = int(port_str)
        except ValueError:
            host = memcache
    if not host:
        host = "localhost"
    return host, port


class ThreadedMemcacheClient:
    def __init__(self, host: str, port: int) -> None:
        self._client = MemcacheClient((host, port))

    def get(self, key: bytes):
        def _get():
            data = self._client.get(key)
            return (0, data)

        return threads.deferToThread(_get)

    def disconnect(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass


def build_memcache_client(memcache: str) -> ThreadedMemcacheClient:
    host, port = parse_memcache_addr(memcache)
    return ThreadedMemcacheClient(host, port)
