"""Type definitions for iembot."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from datetime import datetime


class JabberClient(Protocol):
    """Structural type for JabberClient to avoid import cycles."""

    startup_time: datetime
    picklefile: str
    name: str
    dbpool: Any
    memcache_client: Any | None
    config: dict[str, Any]
    outstanding_pings: list
    rooms: dict[str, dict[str, Any]]
    chatlog: dict[str, Any]
    seqnum: int
    routingtable: dict[str, list[str]]
    at_manager: Any
    at_users: dict[str, dict[str, Any]]
    at_routingtable: dict[str, list[str]]
    tw_users: dict[str, dict[str, Any]]
    tw_routingtable: dict[str, list[str]]
    md_users: dict[str, dict[str, Any]]
    md_routingtable: dict[str, list[str]]
    slack_teams: dict[str, str]
    slack_routingtable: dict[str, list[str]]
    webhooks_routingtable: dict[str, list[str]]
    xmlstream: Any | None
    firstlogin: bool
    xmllog: Any
    myjid: Any | None
    ingestjid: Any | None
    conference: str | None
    email_timestamps: list[datetime]
    keepalive_lc: Any | None
    fortunes: list[str]
