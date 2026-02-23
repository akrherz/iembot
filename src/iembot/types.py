"""Type definitions for iembot."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from datetime import datetime

    from twisted.internet.defer import Deferred


class JabberClient(Protocol):
    """Structural type for JabberClient to avoid import cycles."""

    startup_time: datetime
    picklefile: str
    name: str
    dbpool: Any
    memcache_client: Any | None
    config: dict[str, Any]
    outstanding_pings: list
    chatlog: dict[str, Any]
    seqnum: int
    # XMPP
    rooms: dict[str, dict[str, Any]]
    # channel -> [room, room, ...]
    routingtable: dict[str, list[str]]

    # Atmosphere
    at_manager: Any
    at_users: dict[str, dict[str, Any]]
    at_routingtable: dict[str, list[str]]

    # Twitter/X
    tw_users: dict[int, dict[str, Any]]
    tw_routingtable: dict[str, list[int]]

    # Mastodon
    md_users: dict[int, dict[str, Any]]
    md_routingtable: dict[str, list[int]]

    # Slack
    slack_teams: dict[str, dict[str, str]]
    slack_routingtable: dict[str, list[str]]

    # Webhooks
    webhooks_routingtable: dict[str, list[dict[str, Any]]]

    xmlstream: Any | None
    firstlogin: bool
    xmllog: Any
    myjid: Any | None
    ingestjid: Any | None
    conference: str | None
    email_timestamps: list[datetime]
    keepalive_lc: Any | None
    fortunes: list[str]

    def fire_client(self, xs: Any, service_collection: Any) -> None:
        """Fire up the client."""

    def log_iembot_social_log(
        self,
        iembot_account_id: int,
        response: str,
    ) -> Deferred:
        """Persist social response."""
