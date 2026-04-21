"""Tests pro wiring do painel shadow com cockpit client.

Testa apenas as funcões puras (_get_cockpit_client, _is_remote_run,
_remote_run_id, _find_latest_shadow_run fallback) — nao instancia Tk.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _clear_live_view_fs_caches():
    import launcher_support.engines_live_view as evv

    evv._clear_live_fs_caches()
    evv._clear_cockpit_view_caches()
    yield
    evv._clear_live_fs_caches()
    evv._clear_cockpit_view_caches()


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
    """Sem client → le disco local como antes.
    Precisa resetar tunnel_registry tb porque um shadow_poller vazado de
    teste anterior (com cache de run real) faria _find_latest_shadow_run
    retornar o remote em vez do local-disk fallback."""
    import launcher_support.engines_live_view as evv
    from launcher_support import tunnel_registry
    tunnel_registry.reset_for_tests()
    run = tmp_path / "data" / "millennium_shadow" / "2026-04-18_0229" / "state"
    run.mkdir(parents=True)
    (run / "heartbeat.json").write_text(json.dumps({
        "run_id": "2026-04-18_0229", "status": "running",
        "ticks_ok": 1, "ticks_fail": 0, "novel_total": 5,
        "last_tick_at": "2026-04-18T03:00:00+00:00",
        "last_error": None, "tick_sec": 900,
    }))
    monkeypatch.chdir(tmp_path)
    evv._COCKPIT_CLIENT_SINGLETON = False
    try:
        result = evv._find_latest_shadow_run()
        assert result is not None
        run_dir, hb = result
        assert hb["run_id"] == "2026-04-18_0229"
        assert not str(run_dir).startswith("remote://")
    finally:
        evv._COCKPIT_CLIENT_SINGLETON = None
        tunnel_registry.reset_for_tests()


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


def test_mode_shadow_in_mode_order():
    """SHADOW e o 5o modo depois de paper/demo/testnet/live."""
    from launcher_support.engines_live_view import _MODE_ORDER, _MODE_COLORS
    assert _MODE_ORDER == ("paper", "demo", "testnet", "live", "shadow")
    # Cada modo tem cor mapeada — sem isso _refresh_header levanta KeyError.
    for mode in _MODE_ORDER:
        assert mode in _MODE_COLORS
        assert _MODE_COLORS[mode]  # nao-vazio
    # Cycle completo: shadow -> paper.
    from launcher_support.engines_live_view import cycle_mode
    assert cycle_mode("live") == "shadow"
    assert cycle_mode("shadow") == "paper"


def test_shadow_active_slugs_empty_when_no_poller():
    """Sem poller registrado, _shadow_active_slugs retorna set vazio."""
    from launcher_support.engines_live_view import _shadow_active_slugs
    from launcher_support import tunnel_registry
    tunnel_registry.reset_for_tests()
    assert _shadow_active_slugs() == set()


def test_shadow_active_slugs_includes_engine_when_cached():
    """Com poller retornando cache, slug do poller.engine entra no set."""
    from launcher_support.engines_live_view import _shadow_active_slugs
    from launcher_support import tunnel_registry
    from pathlib import Path

    class FakePoller:
        engine = "millennium"
        def get_cached(self):
            return (Path("remote://r1"), {"run_id": "r1", "status": "running"})

    try:
        tunnel_registry.set_shadow_poller(FakePoller())
        assert _shadow_active_slugs() == {"millennium"}
    finally:
        tunnel_registry.reset_for_tests()


def test_shadow_active_slugs_uses_dynamic_engine_attr():
    """_shadow_active_slugs nao hardcode 'millennium' — le poller.engine."""
    from launcher_support.engines_live_view import _shadow_active_slugs
    from launcher_support import tunnel_registry
    from pathlib import Path

    class FakePoller:
        engine = "citadel"  # hipotetico poller de outro engine
        def get_cached(self):
            return (Path("remote://rX"), {"run_id": "rX", "status": "running"})

    try:
        tunnel_registry.set_shadow_poller(FakePoller())
        assert _shadow_active_slugs() == {"citadel"}
    finally:
        tunnel_registry.reset_for_tests()


def test_tunnel_error_hint_uses_boot_error_when_manager_missing():
    import launcher_support.engines_live_view as evv
    from launcher_support import tunnel_registry

    try:
        tunnel_registry.set_tunnel_boot_error("ssh host key verification failed")
        assert evv._get_tunnel_error_hint() == "ssh host key verification failed"
    finally:
        tunnel_registry.reset_for_tests()


def test_tunnel_error_hint_uses_manager_last_error():
    import launcher_support.engines_live_view as evv
    from launcher_support import tunnel_registry

    class FakeManager:
        last_error = "ssh auth failed (missing or wrong key)"

    try:
        tunnel_registry.set_tunnel_manager(FakeManager())
        assert evv._get_tunnel_error_hint() == "ssh auth failed (missing or wrong key)"
    finally:
        tunnel_registry.reset_for_tests()


def test_shadow_active_slugs_falls_back_to_cockpit_latest_run():
    from launcher_support import engines_live_view as evv
    from launcher_support import tunnel_registry

    class FakePoller:
        engine = "millennium"

        def get_cached(self):
            return None

    class FakeClient:
        def latest_run(self, engine, mode=None):
            assert engine == "millennium"
            assert mode == "shadow"
            return {"run_id": "r1", "engine": "millennium", "mode": "shadow",
                    "status": "running"}

    try:
        tunnel_registry.set_shadow_poller(FakePoller())
        evv._COCKPIT_CLIENT_SINGLETON = FakeClient()
        assert evv._shadow_active_slugs() == {"millennium"}
    finally:
        evv._COCKPIT_CLIENT_SINGLETON = None
        tunnel_registry.reset_for_tests()


def test_fetch_shadow_snapshot_falls_back_to_cockpit_when_poller_empty():
    from launcher_support import engines_live_view as evv
    from launcher_support import tunnel_registry

    class FakePoller:
        engine = "millennium"

        def get_cached(self):
            return None

    class FakeClient:
        def latest_run(self, engine, mode=None):
            assert engine == "millennium"
            assert mode == "shadow"
            return {
                "run_id": "r1",
                "engine": "millennium",
                "mode": "shadow",
                "status": "running",
                "novel_total": 2,
                "last_tick_at": "2026-04-21T13:20:10+00:00",
            }

        def get_heartbeat(self, run_id):
            assert run_id == "r1"
            return {"run_id": "r1", "status": "running", "ticks_ok": 3}

        def get_trades(self, run_id, limit=20):
            assert run_id == "r1"
            assert limit == 20
            return {"trades": [{"strategy": "JUMP", "symbol": "BTCUSDT"}]}

    try:
        tunnel_registry.set_shadow_poller(FakePoller())
        evv._COCKPIT_CLIENT_SINGLETON = FakeClient()
        run_dir, hb, trades = evv._fetch_shadow_snapshot()
        assert str(run_dir).replace("\\", "/") == "remote:/r1"
        assert hb["ticks_ok"] == 3
        assert trades[0]["strategy"] == "JUMP"
    finally:
        evv._COCKPIT_CLIENT_SINGLETON = None
        tunnel_registry.reset_for_tests()


def test_load_shadow_snapshot_cached_uses_ttl_cache(monkeypatch):
    from pathlib import Path
    import launcher_support.engines_live_view as evv

    monkeypatch.setattr(
        evv,
        "_load_shadow_snapshot_sync",
        lambda: (
            Path("remote://r1"),
            {"run_id": "r1", "status": "running"},
            [{"strategy": "JUMP"}],
        ),
    )
    first = evv._load_shadow_snapshot_cached(allow_sync=True)

    monkeypatch.setattr(
        evv,
        "_load_shadow_snapshot_sync",
        lambda: (
            Path("remote://r2"),
            {"run_id": "r2", "status": "stopped"},
            [{"strategy": "CITADEL"}],
        ),
    )
    second = evv._load_shadow_snapshot_cached()

    assert str(first[0]).replace("\\", "/") == "remote:/r1"
    assert first[1]["run_id"] == "r1"
    assert second[1]["run_id"] == "r1"


def test_engine_registry_for_sidebar_paper_mode_forces_millennium():
    from launcher_support.engines_live_view import _engine_registry_for_sidebar

    registry = _engine_registry_for_sidebar({
        "mode": "paper",
        "selected_slug": "citadel",
        "engines_by_bucket": {
            "LIVE": [{"slug": "citadel", "display": "CITADEL"}],
            "READY": [{"slug": "millennium", "display": "MILLENNIUM"}],
        },
    })

    assert registry == [{"slug": "millennium", "display": "MILLENNIUM"}]


def test_latest_run_dir_uses_ttl_cache(tmp_path, monkeypatch):
    import launcher_support.engines_live_view as evv

    data_root = tmp_path / "data"
    run1 = data_root / "millennium_live" / "r1"
    run1.mkdir(parents=True)
    monkeypatch.setattr(evv, "__file__", str(tmp_path / "launcher_support" / "engines_live_view.py"))

    first = evv._latest_run_dir("millennium_live")
    assert first is not None
    assert first.name == "r1"

    run2 = data_root / "millennium_live" / "r2"
    run2.mkdir(parents=True)
    run2.touch()
    second = evv._latest_run_dir("millennium_live")
    assert second is not None
    assert second.name == "r1"


def test_load_positions_for_slug_uses_ttl_cache(tmp_path, monkeypatch):
    import launcher_support.engines_live_view as evv

    data_root = tmp_path / "data"
    run_dir = data_root / "millennium_live" / "r1" / "state"
    run_dir.mkdir(parents=True)
    positions_path = run_dir / "positions.json"
    positions_path.write_text(json.dumps([{"symbol": "BTCUSDT", "pnl": 1.0}]), encoding="utf-8")
    monkeypatch.setattr(evv, "__file__", str(tmp_path / "launcher_support" / "engines_live_view.py"))

    first = evv._load_positions_for_slug("millennium_live")
    positions_path.write_text(json.dumps([{"symbol": "ETHUSDT", "pnl": 2.0}]), encoding="utf-8")
    second = evv._load_positions_for_slug("millennium_live")

    assert first[0]["symbol"] == "BTCUSDT"
    assert second[0]["symbol"] == "BTCUSDT"


def test_read_log_tail_uses_ttl_cache(tmp_path):
    import launcher_support.engines_live_view as evv

    log_path = tmp_path / "engine.log"
    log_path.write_text("a\nb\n", encoding="utf-8")

    first = evv._read_log_tail(log_path, n=2)
    log_path.write_text("x\ny\n", encoding="utf-8")
    second = evv._read_log_tail(log_path, n=2)

    assert first == ["a", "b"]
    assert second == ["a", "b"]


def test_find_latest_shadow_run_local_fallback_uses_ttl_cache(tmp_path, monkeypatch):
    import launcher_support.engines_live_view as evv
    from launcher_support import tunnel_registry

    tunnel_registry.reset_for_tests()
    run1 = tmp_path / "data" / "millennium_shadow" / "r1" / "state"
    run1.mkdir(parents=True)
    (run1 / "heartbeat.json").write_text(json.dumps({"run_id": "r1"}), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    evv._COCKPIT_CLIENT_SINGLETON = False
    try:
        first = evv._find_latest_shadow_run()
        run2 = tmp_path / "data" / "millennium_shadow" / "r2" / "state"
        run2.mkdir(parents=True)
        (run2 / "heartbeat.json").write_text(json.dumps({"run_id": "r2"}), encoding="utf-8")
        second = evv._find_latest_shadow_run()

        assert first is not None
        assert second is not None
        assert first[1]["run_id"] == "r1"
        assert second[1]["run_id"] == "r1"
    finally:
        evv._COCKPIT_CLIENT_SINGLETON = None
        tunnel_registry.reset_for_tests()


def test_load_cockpit_runs_cached_uses_ttl_cache(monkeypatch):
    import launcher_support.engines_live_view as evv

    monkeypatch.setattr(
        evv,
        "_load_cockpit_runs_sync",
        lambda: [{"run_id": "r1", "mode": "paper", "status": "running"}],
    )
    first = evv._load_cockpit_runs_cached(allow_sync=True)

    monkeypatch.setattr(
        evv,
        "_load_cockpit_runs_sync",
        lambda: [{"run_id": "r2", "mode": "paper", "status": "running"}],
    )
    second = evv._load_cockpit_runs_cached()

    assert [row["run_id"] for row in first] == ["r1"]
    assert [row["run_id"] for row in second] == ["r1"]


def test_fetch_paper_extras_uses_ttl_cache(monkeypatch):
    import launcher_support.engines_live_view as evv

    monkeypatch.setattr(
        evv,
        "_fetch_paper_extras_sync",
        lambda run_id: (
            {"run_id": run_id, "status": "running"},
            [{"symbol": "BTCUSDT"}],
            [10100.0],
            {"available": 10000.0},
        ),
    )
    first = evv._fetch_paper_extras("paper_1", allow_sync=True)

    monkeypatch.setattr(
        evv,
        "_fetch_paper_extras_sync",
        lambda run_id: (
            {"run_id": run_id, "status": "stopped"},
            [{"symbol": "ETHUSDT"}],
            [9900.0],
            {"available": 9000.0},
        ),
    )
    second = evv._fetch_paper_extras("paper_1")

    assert first[0]["status"] == "running"
    assert first[1][0]["symbol"] == "BTCUSDT"
    assert second[0]["status"] == "running"
    assert second[1][0]["symbol"] == "BTCUSDT"


def test_refresh_paper_detail_skips_rerender_when_signature_unchanged(monkeypatch):
    import launcher_support.engines_live_view as evv

    calls: list[str] = []

    class _Host:
        def winfo_exists(self):
            return True

    class _Launcher:
        def after(self, _delay, fn):
            calls.append("after")
            return "aid"

        def after_cancel(self, _aid):
            return None

    monkeypatch.setattr(evv, "_paper_content_sig", lambda state, launcher=None: ("same",))
    monkeypatch.setattr(evv, "_render_detail", lambda state, launcher: calls.append("render"))

    state = {
        "mode": "paper",
        "detail_host": _Host(),
        "paper_last_render_sig": ("same",),
    }
    evv._refresh_paper_detail(_Launcher(), state)

    assert "render" not in calls
    assert "after" in calls


def test_refresh_shadow_detail_skips_rerender_when_signature_unchanged(monkeypatch):
    import launcher_support.engines_live_view as evv

    calls: list[str] = []

    class _Host:
        def winfo_exists(self):
            return True

    class _Launcher:
        def after(self, _delay, fn):
            calls.append("after")
            return "aid"

        def after_cancel(self, _aid):
            return None

    monkeypatch.setattr(evv, "_shadow_content_sig", lambda state, launcher=None: ("same",))
    monkeypatch.setattr(evv, "_render_detail", lambda state, launcher: calls.append("render"))

    state = {
        "mode": "shadow",
        "detail_host": _Host(),
        "shadow_last_render_sig": ("same",),
    }
    evv._refresh_shadow_detail(_Launcher(), state)

    assert "render" not in calls
    assert "after" in calls
