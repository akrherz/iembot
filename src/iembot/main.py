"""Entry point for the iembot CLI.

This module replaces the historical `iembot.tac` twistd application file
with a Click-driven CLI while keeping the same Twisted service wiring.
"""

from __future__ import annotations

import json
import os
import sys

import click
from psycopg.rows import dict_row
from twisted.application import internet, service
from twisted.enterprise import adbapi
from twisted.internet import reactor
from twisted.python import log
from twisted.python.logfile import DailyLogFile
from twisted.web import server

from iembot import webservices
from iembot.bot import JabberClient
from iembot.memcache import build_memcache_client
from iembot.msghandlers import register_handler


def _load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _build_dbpool(config: dict) -> adbapi.ConnectionPool:
    # Password should be set via .pgpass or environment.
    return adbapi.ConnectionPool(
        "psycopg",
        cp_reconnect=True,
        dbname=config.get("bot.dbname", "iembot"),
        host=config.get("bot.dbhost", "localhost"),
        user=config.get("bot.dbuser", "iembot"),
        gssencmode="disable",
        row_factory=dict_row,
    )


def _build_memcache_client(memcache: str):
    return build_memcache_client(memcache)


def _start_logging(logfile: str | None) -> None:
    if logfile in (None, "", "-"):
        log.startLogging(sys.stdout)
        return
    logdir = os.path.dirname(logfile) or "."
    os.makedirs(logdir, exist_ok=True)
    logname = os.path.basename(logfile)
    log.startLogging(DailyLogFile(logname, logdir))


def _write_pidfile(pidfile: str | None) -> None:
    if not pidfile:
        return
    with open(pidfile, "w", encoding="utf-8") as fh:
        fh.write(f"{os.getpid()}\n")


def _remove_pidfile(pidfile: str) -> None:
    try:
        os.remove(pidfile)
    except FileNotFoundError:
        return


def _fatal():
    # If initial bootstrap fails, stop cleanly.
    log.msg("FATAL: Stopping reactor...")
    try:
        reactor.stop()
    except Exception:
        pass


@click.group()
def main() -> None:
    """IEMBot command line interface."""


@main.command()
@click.option(
    "--config",
    "-c",
    type=click.Path(exists=True, dir_okay=False),
    default="settings.json",
    show_default=True,
    help="Path to settings.json",
)
@click.option(
    "--json-port",
    type=int,
    default=9003,
    show_default=True,
    help="Port for JSON channel requests",
)
@click.option(
    "--rss-port",
    type=int,
    default=9004,
    show_default=True,
    help="Port for RSS feed requests",
)
@click.option(
    "--memcache",
    type=str,
    default="tcp:iem-memcached:11211",
    show_default=True,
    help="Memcache server URI",
)
@click.option(
    "--maxthreads",
    type=int,
    default=512,
    show_default=True,
    help="Max Twisted threadpool size",
)
@click.option(
    "--logfile",
    "-l",
    type=str,
    default="logs/iembot.log",
    show_default=True,
    help="Twisted log file path (use '-' for stdout)",
)
@click.option(
    "--pidfile",
    "-p",
    type=str,
    default="iembot.pid",
    show_default=True,
    help="PID file path (empty to disable)",
)
@click.option(
    "--disable-slack",
    is_flag=True,
    default=False,
    help="Disable Slack message handler",
)
@click.option(
    "--disable-twitter",
    is_flag=True,
    default=False,
    help="Disable Twitter/X message handler",
)
@click.option(
    "--disable-atmosphere",
    is_flag=True,
    default=False,
    help="Disable ATmosphere(Bluesky) message handler",
)
@click.option(
    "--disable-mastodon",
    is_flag=True,
    default=False,
    help="Disable Mastodon message handler",
)
def run(
    config: str,
    json_port: int,
    rss_port: int,
    memcache: str,
    maxthreads: int,
    logfile: str,
    pidfile: str,
    disable_slack: bool,
    disable_twitter: bool,
    disable_atmosphere: bool,
    disable_mastodon: bool,
) -> None:
    """Run the IEMBot service (Twisted reactor)."""

    _start_logging(logfile)
    _write_pidfile(pidfile)

    handlers = [
        (not disable_slack, "iembot.slack", "route"),
        (not disable_twitter, "iembot.twitter", "route"),
        (not disable_atmosphere, "iembot.atmosphere", "route"),
        (not disable_mastodon, "iembot.mastodon", "route"),
        (True, "iembot.xmpp", "route"),  # Required at the moment
    ]
    for enabled, module, attr in handlers:
        if enabled:
            log.msg(f"Enabling handler: {module}.{attr}")
            mod = __import__(module, fromlist=[attr])
            register_handler(getattr(mod, attr))

    # Keep the classic Twisted Application pattern from iembot.tac.
    application = service.Application("Public IEMBOT")
    service_collection = service.IServiceCollection(application)

    settings = _load_config(config)
    dbpool = _build_dbpool(settings)
    memcache_client = _build_memcache_client(memcache)

    jabber = JabberClient("iembot", dbpool, settings, memcache_client)

    # Lame means to ensure the database is reachable before starting.
    d = dbpool.runQuery("select 1")
    d.addCallback(jabber.fire_client, service_collection)
    d.addErrback(lambda failure: (log.err(failure), _fatal()))

    # Web services (same as tac: TCPServer + setServiceParent)
    json_site = server.Site(
        webservices.JSONRootResource(jabber),
        logPath="/dev/null",
    )
    json_service = internet.TCPServer(json_port, json_site)
    json_service.setServiceParent(service_collection)

    rss_site = server.Site(
        webservices.RSSRootResource(jabber),
        logPath="/dev/null",
    )
    rss_service = internet.TCPServer(rss_port, rss_site)
    rss_service.setServiceParent(service_collection)

    # Threadpool tuning (kept from tac)
    reactor.getThreadPool().adjustPoolsize(maxthreads=maxthreads)

    # Ensure services stop on shutdown.
    reactor.addSystemEventTrigger(
        "before",
        "shutdown",
        service_collection.stopService,
    )
    reactor.addSystemEventTrigger("before", "shutdown", dbpool.close)
    if pidfile:
        reactor.addSystemEventTrigger(
            "before",
            "shutdown",
            _remove_pidfile,
            pidfile,
        )
    if hasattr(memcache_client, "disconnect"):
        reactor.addSystemEventTrigger(
            "before",
            "shutdown",
            memcache_client.disconnect,
        )

    # Start services and run the reactor.
    service_collection.startService()
    if not reactor.running:
        reactor.run()


if __name__ == "__main__":
    main()
