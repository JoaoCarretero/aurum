"""Tests pro wiring do painel shadow com cockpit client.

Testa apenas as funcões puras (_get_cockpit_client, _is_remote_run,
_remote_run_id, _find_latest_shadow_run fallback) — nao instancia Tk.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


def test_is_remote_run_detects_prefix():
    from launcher_support.engines_live_view import _is_remote_run
    assert _is_remote_run(Path("remote://2026-04-18_0229")) is True
    assert _is_remote_run(Path("data/millennium_shadow/2026-04-18_0229")) is False


def test_remote_run_id_strips_prefix():
    from launcher_support.engines_live_view import _remote_run_id
    assert _remote_run_id(Path("remote://2026-04-18_0229")) == "2026-04-18_0229"


def test_get_cockpit_client_returns_none_when_config_missing(tmp_path, monkeypatch):
    """Sem config/keys.json ou sem bloco cockpit_api → None e cacheia o negativo."""
    import launcher_support.engines_live_view as evv
    monkeypatch.chdir(tmp_path)  # pwd sem config/keys.json
    evv._COCKPIT_CLIENT_SINGLETON = None  # clear module cache
    assert evv._get_cockpit_client() is None
    assert evv._get_cockpit_client() is None  # cached, no retry
    evv._COCKPIT_CLIENT_SINGLETON = None  # cleanup pra não vazar pra outros testes


def test_get_cockpit_client_returns_none_when_block_missing(tmp_path, monkeypatch):
    """keys.json existe mas sem bloco cockpit_api → None."""
    import launcher_support.engines_live_view as evv
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "keys.json").write_text(json.dumps({"demo": {}}))
    monkeypatch.chdir(tmp_path)
    evv._COCKPIT_CLIENT_SINGLETON = None
    assert evv._get_cockpit_client() is None
    evv._COCKPIT_CLIENT_SINGLETON = None  # cleanup


def test_get_cockpit_client_builds_when_block_present(tmp_path, monkeypatch):
    import launcher_support.engines_live_view as evv
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "keys.json").write_text(json.dumps({
        "cockpit_api": {
            "base_url": "http://localhost:8787",
            "read_token": "READ",
            "admin_token": "ADMIN",
            "timeout_sec": 3.0,
        }
    }))
    monkeypatch.chdir(tmp_path)
    evv._COCKPIT_CLIENT_SINGLETON = None
    client = evv._get_cockpit_client()
    assert client is not None
    assert client.cfg.base_url == "http://localhost:8787"
    assert client.cfg.read_token == "READ"
    assert client.cfg.admin_token == "ADMIN"
    evv._COCKPIT_CLIENT_SINGLETON = None  # cleanup


def test_find_latest_shadow_run_local_fallback_when_client_none(tmp_path, monkeypatch):
    """Sem client → le disco local como antes."""
    import launcher_support.engines_live_view as evv
    # Set up local data/millennium_shadow layout
    run = tmp_path / "data" / "millennium_shadow" / "2026-04-18_0229" / "state"
    run.mkdir(parents=True)
    (run / "heartbeat.json").write_text(json.dumps({
        "run_id": "2026-04-18_0229", "status": "running",
        "ticks_ok": 1, "ticks_fail": 0, "novel_total": 5,
        "last_tick_at": "2026-04-18T03:00:00+00:00",
        "last_error": None, "tick_sec": 900,
    }))
    monkeypatch.chdir(tmp_path)
    evv._COCKPIT_CLIENT_SINGLETON = False  # force skip remote
    result = evv._find_latest_shadow_run()
    assert result is not None
    run_dir, hb = result
    assert hb["run_id"] == "2026-04-18_0229"
    assert not str(run_dir).startswith("remote://")
    evv._COCKPIT_CLIENT_SINGLETON = None  # cleanup


def test_tunnel_status_label_no_manager():
    """Sem TunnelManager registrado → badge ('—', DIM2)."""
    import launcher_support.engines_live_view as evv
    from launcher_support import tunnel_registry
    tunnel_registry.reset_for_tests()
    text, _fg = evv._get_tunnel_status_label()
    assert text == "—"


def test_tunnel_status_label_maps_enum_value():
    """TunnelStatus.UP → label 'UP'."""
    import launcher_support.engines_live_view as evv
    from launcher_support.ssh_tunnel import TunnelStatus
    from launcher_support import tunnel_registry

    class FakeManager:
        status = TunnelStatus.UP

    try:
        tunnel_registry.set_tunnel_manager(FakeManager())
        text, _fg = evv._get_tunnel_status_label()
        assert text == "UP"
    finally:
        tunnel_registry.reset_for_tests()


def test_tunnel_status_label_all_states_mapped():
    """Every TunnelStatus value has a color mapping (no KeyError)."""
    import launcher_support.engines_live_view as evv
    from launcher_support.ssh_tunnel import TunnelStatus
    from launcher_support import tunnel_registry

    class FakeManager:
        status = None

    try:
        fm = FakeManager()
        tunnel_registry.set_tunnel_manager(fm)
        for status in TunnelStatus:
            fm.status = status
            text, fg = evv._get_tunnel_status_label()
            assert text == status.value.upper()
            assert fg is not None
    finally:
        tunnel_registry.reset_for_tests()
