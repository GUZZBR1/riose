"""Vertical demo is deterministic, offline, and always cleans temporary data."""

from __future__ import annotations

import shutil
import socket
import tempfile
import urllib.request

import pytest

from riose.products.livestock_tracking import cli
from riose.products.livestock_tracking.simulation import blockchain_demo


class TemporaryScope:
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        self.path.mkdir()
        return str(self.path)

    def __exit__(self, *_args):
        shutil.rmtree(self.path)


def test_offline_demo_is_deterministic_and_detects_tampering(tmp_path, monkeypatch, capsys):
    scope_paths = iter((tmp_path / "first", tmp_path / "second"))
    monkeypatch.setattr(tempfile, "TemporaryDirectory", lambda **_: TemporaryScope(next(scope_paths)))

    def no_external_io(*_args, **_kwargs):
        raise AssertionError("offline vertical demo attempted external network I/O")

    monkeypatch.setattr(socket, "socket", no_external_io)
    monkeypatch.setattr(urllib.request, "urlopen", no_external_io)
    assert cli.main(["blockchain-demo"]) == 0
    first = capsys.readouterr().out
    assert cli.main(["blockchain-demo"]) == 0
    second = capsys.readouterr().out
    assert first == second
    assert '"evidence":"SIMULATED"' in first
    assert '"local_chain_before_tamper":"VALID"' in first
    assert '"publication_submit":{"evidence":"SIMULATED","status":"SUBMITTED"}' in first
    assert '"publication_observation":{"evidence":"SIMULATED","status":"CONFIRMED"}' in first
    assert '"receipt":{"evidence":"SIMULATED","status":"CONFIRMED"}' in first
    assert '"status":"UNAVAILABLE"' in first
    assert '"reason":"SIMULATED_ONLY"' in first
    assert '"local_chain_after_tamper":"INVALID"' in first
    assert '"reason":"LOCAL_CHAIN_INVALID"' in first
    assert '"real_adapter_capability":"FUTURE"' in first
    assert '"network_used":false' in first
    assert not (tmp_path / "first").exists()
    assert not (tmp_path / "second").exists()
    assert "demo-animal" not in first and "HEALTH_EVENT" not in first


def test_demo_cleans_temporary_storage_when_scenario_fails(tmp_path, monkeypatch):
    path = tmp_path / "failure"
    monkeypatch.setattr(tempfile, "TemporaryDirectory", lambda **_: TemporaryScope(path))

    def fail(_database_path):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(blockchain_demo, "_run_scenario", fail)
    with pytest.raises(RuntimeError, match="synthetic failure"):
        blockchain_demo.run_blockchain_demo()
    assert not path.exists()
