"""Integration: KS gate triggers flatten + stop."""
import json


def test_ks_fast_halt_flattens_and_stops(tmp_path, monkeypatch):
    from tools.operations import millennium_paper as mp

    run_dir = tmp_path / "millennium_paper" / "KS_TEST"
    for sub in ("state", "reports", "logs"):
        (run_dir / sub).mkdir(parents=True)
    monkeypatch.setattr(mp, "RUN_DIR", run_dir)
    monkeypatch.setattr(mp, "STATE_DIR", run_dir / "state")
    monkeypatch.setattr(mp, "REPORTS_DIR", run_dir / "reports")
    monkeypatch.setattr(mp, "LOGS_DIR", run_dir / "logs")
    monkeypatch.setattr(mp, "RUN_ID", "KS_TEST")
    monkeypatch.setattr(mp, "TRADES_PATH", run_dir / "reports" / "trades.jsonl")
    monkeypatch.setattr(mp, "EQUITY_PATH", run_dir / "reports" / "equity.jsonl")
    monkeypatch.setattr(mp, "FILLS_PATH", run_dir / "reports" / "fills.jsonl")
    monkeypatch.setattr(mp, "SIGNALS_PATH", run_dir / "reports" / "signals.jsonl")
    monkeypatch.setattr(mp, "POSITIONS_PATH", run_dir / "state" / "positions.json")
    monkeypatch.setattr(mp, "ACCOUNT_PATH", run_dir / "state" / "account.json")
    monkeypatch.setattr(mp, "HEARTBEAT_PATH", run_dir / "state" / "heartbeat.json")

    state = mp.RunnerState(account_size=10_000.0)

    # Signal on tick 1 (one-shot): size=30 at entry=100 => notional=3000
    scan_state = {"call_count": 0}

    def fake_scan(notify=False):
        scan_state["call_count"] += 1
        if scan_state["call_count"] == 1:
            return [
                {"strategy": "CITADEL", "symbol": "BTCUSDT", "direction": "LONG",
                 "entry": 100.0, "stop": 95.0, "target": 110.0, "size": 30.0,
                 "timestamp": "2026-04-19T14:00:00Z", "primed": False,
                 "open_ts": "2026-04-19T14:00:00Z"}
            ]
        return []
    monkeypatch.setattr(mp, "_scan_new_signals", fake_scan)

    # Bar plunge on tick 2: close at 96 => MTM = (96-100)*30 = -120 < -100 fast thr
    monkeypatch.setattr(mp, "_fetch_new_bars",
                        lambda s, since: [
                            {"high": 100.5, "low": 96.0, "close": 96.0,
                             "time": "2026-04-19T14:15:00Z"}
                        ])

    mp.run_one_tick(state, tick_idx=1, notify=False)
    assert len(state.open_positions) == 1
    mp.run_one_tick(state, tick_idx=2, notify=False)
    # KS fast_threshold @10k = -100; unrealized ~= (96-100)*30 = -120 < -100 => FAST_HALT
    assert state.ks.state.value == "FAST_HALT"
    assert len(state.open_positions) == 0
    account_snap = json.loads((run_dir / "state" / "account.json").read_text())
    assert account_snap["ks_state"] == "FAST_HALT"
