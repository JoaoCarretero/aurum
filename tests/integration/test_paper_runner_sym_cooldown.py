"""Integration: SYMBOL cooldown after loss in paper runtime.

Today (2026-04-25) MILLENNIUM-paper opened a JUMP XRPUSDT LONG, was
stopped within 13min, and **re-entered the same symbol/direction 17min
later** with size scaled by Kelly-from-fresh-equity. JUMP's backtest scan
loop applies SYM_LOSS_COOLDOWN at scan time, but the runtime layer
(millennium_paper.run_one_tick) never replicated that gate — so live
trading can re-enter the very bar the previous trade stopped.

Fix: track ``sym_loss_cooldown_until`` per RunnerState, populated when a
position closes with exit_reason indicating a stop loss. Block opens on
the same symbol until the cooldown lifts.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone


def _isolate_runner_db(mp, tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(mp, "ROOT", tmp_path)
    monkeypatch.setattr(mp.db_live_runs, "DB_PATH", data_dir / "aurum.db")


def _wire_run_dir(mp, tmp_path, monkeypatch, name):
    run_dir = tmp_path / "millennium_paper" / name
    for sub in ("state", "reports", "logs"):
        (run_dir / sub).mkdir(parents=True)
    _isolate_runner_db(mp, tmp_path, monkeypatch)
    monkeypatch.setattr(mp, "RUN_DIR", run_dir)
    monkeypatch.setattr(mp, "STATE_DIR", run_dir / "state")
    monkeypatch.setattr(mp, "REPORTS_DIR", run_dir / "reports")
    monkeypatch.setattr(mp, "LOGS_DIR", run_dir / "logs")
    monkeypatch.setattr(mp, "RUN_ID", name)
    monkeypatch.setattr(mp, "TRADES_PATH", run_dir / "reports" / "trades.jsonl")
    monkeypatch.setattr(mp, "EQUITY_PATH", run_dir / "reports" / "equity.jsonl")
    monkeypatch.setattr(mp, "FILLS_PATH", run_dir / "reports" / "fills.jsonl")
    monkeypatch.setattr(mp, "SIGNALS_PATH", run_dir / "reports" / "signals.jsonl")
    monkeypatch.setattr(mp, "POSITIONS_PATH", run_dir / "state" / "positions.json")
    monkeypatch.setattr(mp, "ACCOUNT_PATH", run_dir / "state" / "account.json")
    monkeypatch.setattr(mp, "HEARTBEAT_PATH", run_dir / "state" / "heartbeat.json")
    return run_dir


def test_sym_loss_cooldown_blocks_immediate_reentry(tmp_path, monkeypatch):
    """Stop-out + same-symbol re-signal next tick → skipped with cooldown reason."""
    from tools.operations import millennium_paper as mp

    run_dir = _wire_run_dir(mp, tmp_path, monkeypatch, "COOLDOWN_TEST")

    live_ts = datetime.now(timezone.utc).isoformat()

    scan_state = {"calls": 0}

    def fake_scan(notify=False):
        scan_state["calls"] += 1
        # Tick 2: emit fresh JUMP LONG that will stop on tick 3.
        if scan_state["calls"] == 2:
            return [{
                "strategy": "JUMP", "symbol": "XRPUSDT", "direction": "LONG",
                "entry": 1.4285, "stop": 1.4239, "target": 1.4407, "size": 3000,
                "timestamp": live_ts, "open_ts": live_ts,
            }]
        # Tick 4: SAME signal returns (live runtime would scan a fresh bar
        # and JUMP could fire again on identical setup). Use a different
        # open_ts so it dedups as novel through seen_keys.
        if scan_state["calls"] == 4:
            ts = datetime.now(timezone.utc).isoformat()
            return [{
                "strategy": "JUMP", "symbol": "XRPUSDT", "direction": "LONG",
                "entry": 1.4242, "stop": 1.4210, "target": 1.4324, "size": 1900,
                "timestamp": ts, "open_ts": ts,
            }]
        return []
    monkeypatch.setattr(mp, "_scan_new_signals", fake_scan)

    fetch_state = {"call": 0}

    def fake_fetch_new_bars(symbol, since):
        fetch_state["call"] += 1
        # Tick 3 fetches bars for the open position; emit one that hits the stop.
        if fetch_state["call"] == 1:
            return [{"high": 1.43, "low": 1.42, "close": 1.4239,
                     "time": datetime.now(timezone.utc).isoformat()}]
        return []
    monkeypatch.setattr(mp, "_fetch_new_bars", fake_fetch_new_bars)

    state = mp.RunnerState(account_size=10_000.0)
    # Tick 1: prime
    mp.run_one_tick(state, tick_idx=1, notify=False)
    assert state.primed is True
    # Tick 2: open
    mp.run_one_tick(state, tick_idx=2, notify=False)
    assert len(state.open_positions) == 1
    assert state.open_positions[0].symbol == "XRPUSDT"
    # Tick 3: stop hits → close
    mp.run_one_tick(state, tick_idx=3, notify=False)
    assert len(state.open_positions) == 0
    # Cooldown should be armed for XRPUSDT
    assert "XRPUSDT" in state.sym_loss_cooldown_until
    # Tick 4: same-symbol same-direction re-signal arrives → blocked
    mp.run_one_tick(state, tick_idx=4, notify=False)
    assert len(state.open_positions) == 0, (
        "XRPUSDT re-entry must be blocked by sym_loss_cooldown after a stop"
    )

    sigs_path = run_dir / "reports" / "signals.jsonl"
    assert sigs_path.exists()
    sigs = [json.loads(ln) for ln in sigs_path.read_text().splitlines() if ln.strip()]
    skips = [s for s in sigs if s.get("reason") == "sym_loss_cooldown"]
    assert len(skips) == 1, f"expected 1 sym_loss_cooldown skip, got {skips}"
    assert skips[0]["symbol"] == "XRPUSDT"


def test_sym_loss_cooldown_does_not_block_other_symbols(tmp_path, monkeypatch):
    """Cooldown is per-symbol — other symbols still open normally."""
    from tools.operations import millennium_paper as mp

    run_dir = _wire_run_dir(mp, tmp_path, monkeypatch, "COOLDOWN_OTHER_TEST")
    live_ts = datetime.now(timezone.utc).isoformat()

    scan_state = {"calls": 0}

    def fake_scan(notify=False):
        scan_state["calls"] += 1
        if scan_state["calls"] == 2:
            return [{
                "strategy": "JUMP", "symbol": "XRPUSDT", "direction": "LONG",
                "entry": 1.4285, "stop": 1.4239, "target": 1.4407, "size": 3000,
                "timestamp": live_ts, "open_ts": live_ts,
            }]
        if scan_state["calls"] == 4:
            ts = datetime.now(timezone.utc).isoformat()
            return [{
                "strategy": "CITADEL", "symbol": "BTCUSDT", "direction": "LONG",
                "entry": 100.0, "stop": 98.0, "target": 105.0, "size": 1.0,
                "timestamp": ts, "open_ts": ts,
            }]
        return []
    monkeypatch.setattr(mp, "_scan_new_signals", fake_scan)

    fetch_state = {"call": 0}

    def fake_fetch_new_bars(symbol, since):
        fetch_state["call"] += 1
        if symbol == "XRPUSDT" and fetch_state["call"] == 1:
            return [{"high": 1.43, "low": 1.42, "close": 1.4239,
                     "time": datetime.now(timezone.utc).isoformat()}]
        return []
    monkeypatch.setattr(mp, "_fetch_new_bars", fake_fetch_new_bars)

    state = mp.RunnerState(account_size=10_000.0)
    mp.run_one_tick(state, tick_idx=1, notify=False)  # prime
    mp.run_one_tick(state, tick_idx=2, notify=False)  # open XRP
    mp.run_one_tick(state, tick_idx=3, notify=False)  # XRP stops out
    assert "XRPUSDT" in state.sym_loss_cooldown_until
    mp.run_one_tick(state, tick_idx=4, notify=False)  # BTC opens despite XRP cooldown
    assert len(state.open_positions) == 1
    assert state.open_positions[0].symbol == "BTCUSDT"


def test_sym_loss_cooldown_only_arms_on_stop_exit(tmp_path, monkeypatch):
    """Target-hit (WIN) does not arm cooldown; only stop-out does."""
    from tools.operations import millennium_paper as mp

    _wire_run_dir(mp, tmp_path, monkeypatch, "COOLDOWN_WIN_TEST")
    live_ts = datetime.now(timezone.utc).isoformat()

    scan_state = {"calls": 0}

    def fake_scan(notify=False):
        scan_state["calls"] += 1
        if scan_state["calls"] == 2:
            # Tight target so a 101.6 bar hits target before any stop logic.
            return [{
                "strategy": "JUMP", "symbol": "XRPUSDT", "direction": "LONG",
                "entry": 100.0, "stop": 98.0, "target": 101.5, "size": 1.0,
                "timestamp": live_ts, "open_ts": live_ts,
            }]
        return []
    monkeypatch.setattr(mp, "_scan_new_signals", fake_scan)

    def fake_fetch_new_bars(symbol, since):
        return [{"high": 101.8, "low": 99.5, "close": 101.6, "time": live_ts}]
    monkeypatch.setattr(mp, "_fetch_new_bars", fake_fetch_new_bars)

    state = mp.RunnerState(account_size=10_000.0)
    mp.run_one_tick(state, tick_idx=1, notify=False)
    mp.run_one_tick(state, tick_idx=2, notify=False)
    assert len(state.open_positions) == 1
    mp.run_one_tick(state, tick_idx=3, notify=False)
    assert len(state.open_positions) == 0
    # Target win must NOT arm cooldown
    assert "XRPUSDT" not in state.sym_loss_cooldown_until
