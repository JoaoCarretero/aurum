"""Regression: trade-record ``primed`` must reflect ``state.primed``.

Pre-fix: 4 write sites in both ``_paper_runner.py`` and
``millennium_paper.py`` hardcoded ``"primed": False`` in ``trades.jsonl``
and ``metrics.record_closed`` — so downstream audits filtering "primed
only" dropped every trade even after prime completed, and OOS stats
silently excluded legitimate trades.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone


def _setup_paths(monkeypatch, mod, run_dir):
    for sub in ("state", "reports", "logs"):
        (run_dir / sub).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(mod, "RUN_DIR", run_dir)
    monkeypatch.setattr(mod, "STATE_DIR", run_dir / "state")
    monkeypatch.setattr(mod, "REPORTS_DIR", run_dir / "reports")
    monkeypatch.setattr(mod, "LOGS_DIR", run_dir / "logs")
    monkeypatch.setattr(mod, "RUN_ID", run_dir.name)
    monkeypatch.setattr(mod, "TRADES_PATH", run_dir / "reports" / "trades.jsonl")
    monkeypatch.setattr(mod, "EQUITY_PATH", run_dir / "reports" / "equity.jsonl")
    monkeypatch.setattr(mod, "FILLS_PATH", run_dir / "reports" / "fills.jsonl")
    monkeypatch.setattr(mod, "SIGNALS_PATH", run_dir / "reports" / "signals.jsonl")
    monkeypatch.setattr(mod, "POSITIONS_PATH", run_dir / "state" / "positions.json")
    monkeypatch.setattr(mod, "ACCOUNT_PATH", run_dir / "state" / "account.json")
    monkeypatch.setattr(mod, "HEARTBEAT_PATH", run_dir / "state" / "heartbeat.json")


def test_primed_flag_true_after_prime_tick(tmp_path, monkeypatch):
    """After tick 1 primes the runner, any subsequent close must record
    ``primed=true`` in trades.jsonl — not False (pre-fix hardcode)."""
    from tools.operations import millennium_paper as mp
    _setup_paths(monkeypatch, mp, tmp_path / "millennium_paper" / "PRIMED_TRUE")

    live_ts = datetime.now(timezone.utc).isoformat()

    scan_state = {"n": 0}
    def fake_scan(notify=False):
        scan_state["n"] += 1
        if scan_state["n"] == 2:
            return [{
                "strategy": "CITADEL", "symbol": "BTCUSDT", "direction": "LONG",
                "entry": 100.0, "stop": 98.0, "target": 101.5, "size": 1.0,
                "timestamp": live_ts, "open_ts": live_ts, "primed": False,
            }]
        return []
    monkeypatch.setattr(mp, "_scan_new_signals", fake_scan)
    monkeypatch.setattr(mp, "_fetch_new_bars",
                        lambda s, since: [{"high": 101.8, "low": 99.5,
                                           "close": 101.6, "time": live_ts}])

    state = mp.RunnerState(account_size=10_000.0)
    mp.run_one_tick(state, tick_idx=1, notify=False)  # primes
    assert state.primed is True

    mp.run_one_tick(state, tick_idx=2, notify=False)  # opens
    mp.run_one_tick(state, tick_idx=3, notify=False)  # closes via target

    trades_path = mp.TRADES_PATH
    lines = [json.loads(ln) for ln in trades_path.read_text().splitlines() if ln.strip()]
    assert len(lines) == 1
    assert lines[0]["primed"] is True, (
        f"trade recorded primed={lines[0]['primed']!r}, expected True. "
        f"Regression of the 2026-04-24 hardcoded primed:False bug."
    )


def test_primed_flag_matches_state_standalone(tmp_path, monkeypatch):
    """Same check for the standalone per-engine paper runner."""
    from tools.operations import _paper_runner as pr
    _setup_paths(monkeypatch, pr, tmp_path / "renaissance_paper" / "PRIMED_TRUE_STD")

    live_ts = datetime.now(timezone.utc).isoformat()

    scan_state = {"n": 0}
    def fake_scan(notify=False):
        scan_state["n"] += 1
        if scan_state["n"] == 2:
            return [{
                "strategy": "RENAISSANCE", "symbol": "OPUSDT", "direction": "LONG",
                "entry": 0.1226, "stop": 0.1208, "target": 0.1227, "size": 1000.0,
                "timestamp": live_ts, "open_ts": live_ts, "primed": False,
            }]
        return []
    monkeypatch.setattr(pr, "_scan_new_signals", fake_scan)
    monkeypatch.setattr(pr, "_fetch_new_bars",
                        lambda s, since: [{"high": 0.1228, "low": 0.1225,
                                           "close": 0.1227, "time": live_ts}])

    state = pr.RunnerState(account_size=10_000.0)
    pr.run_one_tick(state, tick_idx=1, notify=False)  # primes
    pr.run_one_tick(state, tick_idx=2, notify=False)  # opens
    pr.run_one_tick(state, tick_idx=3, notify=False)  # closes

    lines = [json.loads(ln) for ln in pr.TRADES_PATH.read_text().splitlines() if ln.strip()]
    assert len(lines) == 1
    assert lines[0]["primed"] is True
