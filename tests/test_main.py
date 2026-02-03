"""Tests for src/iembot/main.py"""

import json
import os
import sys
import types
from unittest import mock

from click.testing import CliRunner

import iembot.main as main_mod


def test_load_settings_reads_json(tmp_path):
    d = {"foo": "bar"}
    f = tmp_path / "settings.json"
    f.write_text(json.dumps(d))
    assert main_mod._load_config(str(f)) == d


def test_write_and_remove_pidfile(tmp_path):
    pidfile = tmp_path / "pid"
    main_mod._write_pidfile(str(pidfile))
    assert pidfile.read_text().strip() == str(os.getpid())
    main_mod._remove_pidfile(str(pidfile))
    assert not pidfile.exists()
    # Should not raise if already gone
    main_mod._remove_pidfile(str(pidfile))


def test_start_logging_stdout(monkeypatch):
    called = {}
    monkeypatch.setattr(
        main_mod.log,
        "startLogging",
        lambda arg: called.setdefault("stdout", arg),
    )
    main_mod._start_logging("-")
    assert called["stdout"] is sys.stdout


def test_start_logging_file(monkeypatch, tmp_path):
    called = {}

    class DummyDLF:
        def __init__(self, name, _dir):
            called["name"] = name
            called["dir"] = _dir

    monkeypatch.setattr(main_mod, "DailyLogFile", DummyDLF)
    monkeypatch.setattr(
        main_mod.log,
        "startLogging",
        lambda arg: called.setdefault("file", arg),
    )
    logfile = tmp_path / "foo" / "bar.log"
    main_mod._start_logging(str(logfile))
    assert called["name"] == "bar.log"
    assert os.path.basename(str(logfile)) == "bar.log"
    assert called["dir"] == str(tmp_path / "foo")


def test_build_dbpool(monkeypatch):
    fakepool = object()

    def fakepool_ctor(*_a, **_k):
        return fakepool

    monkeypatch.setattr(
        main_mod, "adbapi", types.SimpleNamespace(ConnectionPool=fakepool_ctor)
    )
    settings = {
        "databaserw": {
            "openfire": "db",
            "host": "h",
            "password": "p",
            "user": "u",
        }
    }
    assert main_mod._build_dbpool(settings) is fakepool


def test_build_memcache_client(monkeypatch):
    fake = mock.Mock()
    monkeypatch.setattr(main_mod, "YamClient", lambda _reactor, _addrs: fake)
    fake.connect = mock.Mock()
    result = main_mod._build_memcache_client("tcp:foo:1234")
    assert result is fake
    fake.connect.assert_called_once()


def test_fatal_stops_reactor(monkeypatch):
    called = {}
    monkeypatch.setattr(
        main_mod,
        "reactor",
        types.SimpleNamespace(stop=lambda: called.setdefault("stopped", True)),
    )
    main_mod._fatal()
    assert called["stopped"]


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(main_mod.main, ["--help"])
    assert result.exit_code == 0
    assert "IEMBot command line interface" in result.output


def test_cli_run_help():
    runner = CliRunner()
    result = runner.invoke(main_mod.main, ["run", "--help"])
    assert result.exit_code == 0
    assert "Run the IEMBot service" in result.output
