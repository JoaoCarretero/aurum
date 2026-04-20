"""Integration: one-tick paper runner cycle.

Fake _scan_new_signals to return a signal; fake _fetch_new_bars to trigger
target intrabar on next tick; verify artifacts (positions.json, account.json,
trades.jsonl, equity.jsonl) are all valid.
"""
import json
from datetime import datetime, timezone


def test_runner_single_tick_open_then_exit(tmp_path, monkeypatch):
    from tools.operations import millennium_paper as mp

    run_dir = tmp_path / "millennium_paper" / "TEST_RUN"
    (run_dir / "state").mkdir(parents=True)
    (run_dir / "reports").mkdir(parents=True)
    (run_dir / "logs").mkdir(parents=True)

    monkeypatch.setattr(mp, "RUN_DIR", run_dir)
    monkeypatch.setattr(mp, "STATE_DIR", run_dir / "state")
    monkeypatch.setattr(mp, "REPORTS_DIR", run_dir / "reports")
    monkeypatch.setattr(mp, "LOGS_DIR", run_dir / "logs")
    monkeypatch.setattr(mp, "RUN_ID", "TEST_RUN")
    monkeypatch.setattr(mp, "TRADES_PATH", run_dir / "reports" / "trades.jsonl")
    monkeypatch.setattr(mp, "EQUITY_PATH", run_dir / "reports" / "equity.jsonl")
    monkeypatch.setattr(mp, "FILLS_PATH", run_dir / "reports" / "fills.jsonl")
    monkeypatch.setattr(mp, "SIGNALS_PATH", run_dir / "reports" / "signals.jsonl")
    monkeypatch.setattr(mp, "POSITIONS_PATH", run_dir / "state" / "positions.json")
    monkeypatch.setattr(mp, "ACCOUNT_PATH", run_dir / "state" / "account.json")
    monkeypatch.setattr(mp, "HEARTBEAT_PATH", run_dir / "state" / "heartbeat.json")

    live_ts = datetime.now(timezone.utc).isoformat()

    # Fake scan returns one fresh signal (only on post-prime tick)
    scan_state = {"call_count": 0}

    def fake_scan(notify=False):
        scan_state["call_count"] += 1
        if scan_state["call_count"] == 2:
            # Tight target inside BE envelope (target < entry + BE*risk = 102)
            # so the exit path is unambiguously "target" — trail/BE don't fire.
            return [
                {"strategy": "CITADEL", "symbol": "BTCUSDT", "direction": "LONG",
                 "entry": 100.0, "stop": 98.0, "target": 101.5, "size": 1.0,
                 "timestamp": live_ts, "primed": False,
                 "open_ts": live_ts}
            ]
        return []
    monkeypatch.setattr(mp, "_scan_new_signals", fake_scan)

    # Fake bars for exit: one bar that hits target 101.5 without arming BE/trail
    def fake_fetch_new_bars(symbol, since):
        return [{"high": 101.8, "low": 99.5, "close": 101.6,
                 "time": live_ts}]
    monkeypatch.setattr(mp, "_fetch_new_bars", fake_fetch_new_bars)

    state = mp.RunnerState(account_size=10_000.0)
    # Tick 1: prime (no opens, even though scan returns empty here)
    mp.run_one_tick(state, tick_idx=1, notify=False)
    assert state.primed is True
    assert len(state.open_positions) == 0
    # Tick 2: live signal arrives → open
    mp.run_one_tick(state, tick_idx=2, notify=False)
    assert len(state.open_positions) == 1
    # Tick 3: exit via target intrabar
    mp.run_one_tick(state, tick_idx=3, notify=False)
    assert len(state.open_positions) == 0

    trades_path = run_dir / "reports" / "trades.jsonl"
    assert trades_path.exists()
    lines = [json.loads(ln) for ln in trades_path.read_text().splitlines() if ln.strip()]
    assert len(lines) == 1
    assert lines[0]["exit_reason"] == "target"

    account_snap = json.loads((run_dir / "state" / "account.json").read_text())
    assert account_snap["realized_pnl"] > 0


def test_runner_first_tick_primes_without_opening(tmp_path, monkeypatch):
    """Paper must prime seen_keys on first tick (bug 2026-04-19 repro).

    A fresh RunnerState facing 3 historical signals should NOT open any
    position on tick 1 — those signals are backscan noise, not live.
    """
    from tools.operations import millennium_paper as mp

    run_dir = tmp_path / "millennium_paper" / "PRIME_TEST"
    for sub in ("state", "reports", "logs"):
        (run_dir / sub).mkdir(parents=True)

    monkeypatch.setattr(mp, "RUN_DIR", run_dir)
    monkeypatch.setattr(mp, "STATE_DIR", run_dir / "state")
    monkeypatch.setattr(mp, "REPORTS_DIR", run_dir / "reports")
    monkeypatch.setattr(mp, "LOGS_DIR", run_dir / "logs")
    monkeypatch.setattr(mp, "RUN_ID", "PRIME_TEST")
    monkeypatch.setattr(mp, "TRADES_PATH", run_dir / "reports" / "trades.jsonl")
    monkeypatch.setattr(mp, "EQUITY_PATH", run_dir / "reports" / "equity.jsonl")
    monkeypatch.setattr(mp, "FILLS_PATH", run_dir / "reports" / "fills.jsonl")
    monkeypatch.setattr(mp, "SIGNALS_PATH", run_dir / "reports" / "signals.jsonl")
    monkeypatch.setattr(mp, "POSITIONS_PATH", run_dir / "state" / "positions.json")
    monkeypatch.setattr(mp, "ACCOUNT_PATH", run_dir / "state" / "account.json")
    monkeypatch.setattr(mp, "HEARTBEAT_PATH", run_dir / "state" / "heartbeat.json")

    def fake_scan(notify=False):
        return [
            {"strategy": "CITADEL", "symbol": "XRPUSDT", "direction": "BEARISH",
             "entry": 1.956, "stop": 1.965, "target": 1.934, "size": 500,
             "timestamp": "2026-01-22T14:00:00Z", "open_ts": "2026-01-22T14:00:00Z"},
            {"strategy": "JUMP", "symbol": "SANDUSDT", "direction": "BEARISH",
             "entry": 0.161, "stop": 0.162, "target": 0.160, "size": 3000,
             "timestamp": "2026-01-22T12:00:00Z", "open_ts": "2026-01-22T12:00:00Z"},
        ]
    monkeypatch.setattr(mp, "_scan_new_signals", fake_scan)
    monkeypatch.setattr(mp, "_fetch_new_bars", lambda s, since: [])

    state = mp.RunnerState(account_size=10_000.0)
    mp.run_one_tick(state, tick_idx=1, notify=False)
    assert state.primed is True
    assert len(state.open_positions) == 0
    assert len(state.seen_keys) == 2


def test_runner_rejects_stale_signal_post_prime(tmp_path, monkeypatch):
    """Even after prime, signals with historical timestamps must not open.

    Protects against residual backscan history leaking through on later
    ticks (e.g. a bar that flickered out of the DF and came back).
    """
    from tools.operations import millennium_paper as mp

    run_dir = tmp_path / "millennium_paper" / "STALE_TEST"
    for sub in ("state", "reports", "logs"):
        (run_dir / sub).mkdir(parents=True)

    monkeypatch.setattr(mp, "RUN_DIR", run_dir)
    monkeypatch.setattr(mp, "STATE_DIR", run_dir / "state")
    monkeypatch.setattr(mp, "REPORTS_DIR", run_dir / "reports")
    monkeypatch.setattr(mp, "LOGS_DIR", run_dir / "logs")
    monkeypatch.setattr(mp, "RUN_ID", "STALE_TEST")
    monkeypatch.setattr(mp, "TRADES_PATH", run_dir / "reports" / "trades.jsonl")
    monkeypatch.setattr(mp, "EQUITY_PATH", run_dir / "reports" / "equity.jsonl")
    monkeypatch.setattr(mp, "FILLS_PATH", run_dir / "reports" / "fills.jsonl")
    monkeypatch.setattr(mp, "SIGNALS_PATH", run_dir / "reports" / "signals.jsonl")
    monkeypatch.setattr(mp, "POSITIONS_PATH", run_dir / "state" / "positions.json")
    monkeypatch.setattr(mp, "ACCOUNT_PATH", run_dir / "state" / "account.json")
    monkeypatch.setattr(mp, "HEARTBEAT_PATH", run_dir / "state" / "heartbeat.json")

    # Tick 1 scan returns nothing (fresh prime); tick 2 returns one stale signal
    scan_state = {"call_count": 0}

    def fake_scan(notify=False):
        scan_state["call_count"] += 1
        if scan_state["call_count"] == 2:
            return [{
                "strategy": "CITADEL", "symbol": "XRPUSDT", "direction": "BEARISH",
                "entry": 1.956, "stop": 1.965, "target": 1.934, "size": 500,
                "timestamp": "2026-01-22T14:00:00Z",
                "open_ts": "2026-01-22T14:00:00Z",
            }]
        return []
    monkeypatch.setattr(mp, "_scan_new_signals", fake_scan)
    monkeypatch.setattr(mp, "_fetch_new_bars", lambda s, since: [])

    state = mp.RunnerState(account_size=10_000.0)
    mp.run_one_tick(state, tick_idx=1, notify=False)
    mp.run_one_tick(state, tick_idx=2, notify=False)
    assert len(state.open_positions) == 0

    signals_path = run_dir / "reports" / "signals.jsonl"
    lines = [json.loads(ln) for ln in signals_path.read_text().splitlines() if ln.strip()]
    stale = [ln for ln in lines if ln.get("reason") == "stale_bar"]
    assert len(stale) == 1
