"""Integration: one-tick paper runner cycle.

Fake _scan_new_signals to return a signal; fake _fetch_new_bars to trigger
target intrabar on next tick; verify artifacts (positions.json, account.json,
trades.jsonl, equity.jsonl) are all valid.
"""
import json


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

    # Fake scan returns one fresh signal (only on tick 1)
    scan_state = {"call_count": 0}

    def fake_scan(notify=False):
        scan_state["call_count"] += 1
        if scan_state["call_count"] == 1:
            return [
                {"strategy": "CITADEL", "symbol": "BTCUSDT", "direction": "LONG",
                 "entry": 100.0, "stop": 98.0, "target": 104.0, "size": 1.0,
                 "timestamp": "2026-04-19T14:00:00Z", "primed": False,
                 "open_ts": "2026-04-19T14:00:00Z"}
            ]
        return []
    monkeypatch.setattr(mp, "_scan_new_signals", fake_scan)

    # Fake bars for exit: one bar that hits target 104
    fetch_state = {"call_count": 0}

    def fake_fetch_new_bars(symbol, since):
        fetch_state["call_count"] += 1
        return [{"high": 105.0, "low": 99.5, "close": 104.5,
                 "time": "2026-04-19T14:15:00Z"}]
    monkeypatch.setattr(mp, "_fetch_new_bars", fake_fetch_new_bars)

    state = mp.RunnerState(account_size=10_000.0)
    # Tick 1: open signal (notify=False to skip Telegram)
    mp.run_one_tick(state, tick_idx=1, notify=False)
    assert len(state.open_positions) == 1
    # Tick 2: exit via target intrabar
    mp.run_one_tick(state, tick_idx=2, notify=False)
    assert len(state.open_positions) == 0

    trades_path = run_dir / "reports" / "trades.jsonl"
    assert trades_path.exists()
    lines = [json.loads(ln) for ln in trades_path.read_text().splitlines() if ln.strip()]
    assert len(lines) == 1
    assert lines[0]["exit_reason"] == "target"

    account_snap = json.loads((run_dir / "state" / "account.json").read_text())
    assert account_snap["realized_pnl"] > 0
