"""Tests do ShadowPoller — cache, polling, failure handling."""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock


def test_none_client_keeps_cache_none():
    from launcher_support.shadow_poller import ShadowPoller
    poller = ShadowPoller(client_factory=lambda: None)
    poller._poll_once()
    assert poller.get_cached() is None
    assert poller.last_error is None  # nao e erro, e config ausente


def test_poll_populates_cache_on_success():
    from launcher_support.shadow_poller import ShadowPoller
    client = MagicMock()
    client.latest_run.return_value = {
        "run_id": "r1", "engine": "millennium", "status": "running",
        "novel_total": 100, "last_tick_at": "2026-04-18T03:00:00+00:00",
    }
    client.get_heartbeat.return_value = {
        "run_id": "r1", "status": "running",
        "ticks_ok": 5, "ticks_fail": 0, "novel_total": 100,
        "last_tick_at": "2026-04-18T03:00:00+00:00",
        "last_error": None, "tick_sec": 900,
    }
    poller = ShadowPoller(client_factory=lambda: client)
    poller._poll_once()
    cached = poller.get_cached()
    assert cached is not None
    virtual_dir, hb = cached
    assert str(virtual_dir).replace("\\", "/") in ("remote://r1", "remote:/r1")
    assert hb["ticks_ok"] == 5


def test_poll_stubs_heartbeat_on_failure():
    """latest_run OK, get_heartbeat raises → mantem REMOTE com stub."""
    from launcher_support.shadow_poller import ShadowPoller
    client = MagicMock()
    client.latest_run.return_value = {
        "run_id": "r2", "status": "running", "novel_total": 42,
        "last_tick_at": None,
    }
    client.get_heartbeat.side_effect = OSError("conn refused")
    poller = ShadowPoller(client_factory=lambda: client)
    poller._poll_once()
    cached = poller.get_cached()
    assert cached is not None
    _, hb = cached
    assert hb["run_id"] == "r2"
    assert hb["novel_total"] == 42
    assert "heartbeat" in (hb.get("last_error") or "").lower()
    assert poller.last_error is not None


def test_poll_handles_latest_run_failure():
    """latest_run raises → cache intocado, error registrado."""
    from launcher_support.shadow_poller import ShadowPoller
    client = MagicMock()
    client.latest_run.side_effect = OSError("tunnel down")
    poller = ShadowPoller(client_factory=lambda: client)
    poller._poll_once()
    assert poller.get_cached() is None
    assert "latest_run" in (poller.last_error or "")


def test_start_stop_idempotent():
    from launcher_support.shadow_poller import ShadowPoller
    poller = ShadowPoller(client_factory=lambda: None, poll_sec=10.0)
    poller.start()
    poller.start()  # idempotent
    poller.stop(timeout_sec=0.5)
    poller.stop(timeout_sec=0.5)  # idempotent


def test_empty_runs_zeros_cache():
    """Client retorna lista vazia → cache None, sem erro."""
    from launcher_support.shadow_poller import ShadowPoller
    client = MagicMock()
    client.latest_run.return_value = None  # sem run pro engine
    poller = ShadowPoller(client_factory=lambda: client)
    poller._poll_once()
    assert poller.get_cached() is None
    assert poller.last_error is None


def test_poller_thread_stays_alive_on_client_exception():
    """Se client_factory levanta, poller loga mas nao morre."""
    from launcher_support.shadow_poller import ShadowPoller

    def bad_factory():
        raise RuntimeError("factory broken")

    poller = ShadowPoller(client_factory=bad_factory, poll_sec=0.05)
    poller.start()
    time.sleep(0.15)  # deixa rodar algumas iteracoes
    assert poller._thread is not None
    assert poller._thread.is_alive()
    poller.stop(timeout_sec=0.5)
    assert poller.last_error is not None


def test_poll_caches_trades():
    """Poll com sucesso popula o cache de trades alem do heartbeat."""
    from launcher_support.shadow_poller import ShadowPoller
    client = MagicMock()
    client.latest_run.return_value = {
        "run_id": "r3", "status": "running", "novel_total": 3,
        "last_tick_at": None,
    }
    client.get_heartbeat.return_value = {
        "run_id": "r3", "status": "running",
        "ticks_ok": 1, "ticks_fail": 0, "novel_total": 3,
        "last_tick_at": None, "last_error": None, "tick_sec": 900,
    }
    client.get_trades.return_value = {
        "run_id": "r3", "count": 2,
        "trades": [
            {"timestamp": "2026-04-18T03:00:00", "symbol": "BTCUSDT",
             "strategy": "citadel", "direction": "long", "entry": 50000.0},
            {"timestamp": "2026-04-18T03:05:00", "symbol": "ETHUSDT",
             "strategy": "jump", "direction": "short", "entry": 3200.5},
        ],
    }
    poller = ShadowPoller(client_factory=lambda: client)
    poller._poll_once()

    trades = poller.get_trades_cached()
    assert len(trades) == 2
    assert trades[0]["symbol"] == "BTCUSDT"
    assert trades[1]["direction"] == "short"

    # get_cached mantem a tupla (virtual_dir, heartbeat) pra compat.
    cached = poller.get_cached()
    assert cached is not None
    virtual_dir, hb = cached
    assert hb["run_id"] == "r3"
    assert "r3" in str(virtual_dir).replace("\\", "/")

    # snapshot retorna tudo junto.
    snap = poller.get_snapshot()
    assert snap is not None
    assert snap.heartbeat["run_id"] == "r3"
    assert len(snap.trades) == 2

    # get_trades foi chamado com limit padrao (20).
    client.get_trades.assert_called_once()
    assert client.get_trades.call_args.kwargs.get("limit") == 20


def test_poll_trades_failure_keeps_heartbeat():
    """Se get_trades levanta, heartbeat persiste e trades_cached = []."""
    from launcher_support.shadow_poller import ShadowPoller
    client = MagicMock()
    client.latest_run.return_value = {
        "run_id": "r4", "status": "running", "novel_total": 0,
        "last_tick_at": None,
    }
    client.get_heartbeat.return_value = {
        "run_id": "r4", "status": "running",
        "ticks_ok": 7, "ticks_fail": 0, "novel_total": 0,
        "last_tick_at": "2026-04-18T03:10:00",
        "last_error": None, "tick_sec": 900,
    }
    client.get_trades.side_effect = OSError("trades endpoint down")
    poller = ShadowPoller(client_factory=lambda: client)
    poller._poll_once()

    # heartbeat foi cacheado com sucesso.
    cached = poller.get_cached()
    assert cached is not None
    _, hb = cached
    assert hb["ticks_ok"] == 7
    assert hb["run_id"] == "r4"
    # trades vira lista vazia, nao trava o poll.
    assert poller.get_trades_cached() == []
    # last_error fica limpo porque heartbeat deu certo — trades e bonus.
    assert poller.last_error is None
