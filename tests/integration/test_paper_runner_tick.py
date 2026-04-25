"""Integration: one-tick paper runner cycle.

Fake _scan_new_signals to return a signal; fake _fetch_new_bars to trigger
target intrabar on next tick; verify artifacts (positions.json, account.json,
trades.jsonl, equity.jsonl) are all valid.
"""
import importlib
import json
from datetime import datetime, timezone


def test_module_reload_does_not_create_run_dirs(monkeypatch):
    from pathlib import Path
    from tools.operations import millennium_paper as mp

    mkdir_calls: list[Path] = []
    original_mkdir = Path.mkdir

    def spy_mkdir(self, *args, **kwargs):
        mkdir_calls.append(self)
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", spy_mkdir)
    importlib.reload(mp)

    paper_calls = [path for path in mkdir_calls if "millennium_paper" in path.parts]
    assert paper_calls == []


def test_runner_single_tick_open_then_exit(tmp_path, monkeypatch):
    from tools.operations import millennium_paper as mp

    run_dir = tmp_path / "millennium_paper" / "TEST_RUN"
    (run_dir / "state").mkdir(parents=True)
    (run_dir / "reports").mkdir(parents=True)
    (run_dir / "logs").mkdir(parents=True)

    monkeypatch.setattr(mp, "ROOT", tmp_path)
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

    monkeypatch.setattr(mp, "ROOT", tmp_path)
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


def test_runner_first_tick_opens_on_live_signal(tmp_path, monkeypatch):
    """Paper must open on the first tick when the signal is live.

    Before 2026-04-21, priming unconditionally blocked opens on tick 1,
    forcing runs <15m (i.e. every short run) to produce zero trades. Fix
    lets is_live_signal() be the sole stale gate — historical residue is
    still filtered, but a fresh signal arriving at boot is actionable.
    """
    from tools.operations import millennium_paper as mp

    run_dir = tmp_path / "millennium_paper" / "FIRST_OPEN_TEST"
    for sub in ("state", "reports", "logs"):
        (run_dir / sub).mkdir(parents=True)

    monkeypatch.setattr(mp, "ROOT", tmp_path)
    monkeypatch.setattr(mp, "RUN_DIR", run_dir)
    monkeypatch.setattr(mp, "STATE_DIR", run_dir / "state")
    monkeypatch.setattr(mp, "REPORTS_DIR", run_dir / "reports")
    monkeypatch.setattr(mp, "LOGS_DIR", run_dir / "logs")
    monkeypatch.setattr(mp, "RUN_ID", "FIRST_OPEN_TEST")
    monkeypatch.setattr(mp, "TRADES_PATH", run_dir / "reports" / "trades.jsonl")
    monkeypatch.setattr(mp, "EQUITY_PATH", run_dir / "reports" / "equity.jsonl")
    monkeypatch.setattr(mp, "FILLS_PATH", run_dir / "reports" / "fills.jsonl")
    monkeypatch.setattr(mp, "SIGNALS_PATH", run_dir / "reports" / "signals.jsonl")
    monkeypatch.setattr(mp, "POSITIONS_PATH", run_dir / "state" / "positions.json")
    monkeypatch.setattr(mp, "ACCOUNT_PATH", run_dir / "state" / "account.json")
    monkeypatch.setattr(mp, "HEARTBEAT_PATH", run_dir / "state" / "heartbeat.json")

    live_ts = datetime.now(timezone.utc).isoformat()

    def fake_scan(notify=False):
        # Mix: one stale (must be rejected) + one live (must open).
        return [
            {"strategy": "CITADEL", "symbol": "XRPUSDT", "direction": "BEARISH",
             "entry": 1.956, "stop": 1.965, "target": 1.934, "size": 500,
             "timestamp": "2026-01-22T14:00:00Z",
             "open_ts": "2026-01-22T14:00:00Z"},
            {"strategy": "JUMP", "symbol": "BTCUSDT", "direction": "LONG",
             "entry": 100.0, "stop": 98.0, "target": 101.5, "size": 1.0,
             "timestamp": live_ts, "open_ts": live_ts},
        ]
    monkeypatch.setattr(mp, "_scan_new_signals", fake_scan)
    monkeypatch.setattr(mp, "_fetch_new_bars", lambda s, since: [])

    state = mp.RunnerState(account_size=10_000.0)
    mp.run_one_tick(state, tick_idx=1, notify=False)

    # Both signals are dedup-seen; primed becomes True after first scan.
    assert state.primed is True
    assert len(state.seen_keys) == 2
    assert state.novel_total == 1
    assert state.novel_since_prime == 1
    # Only the live signal opens. Stale one is rejected by is_live_signal.
    assert len(state.open_positions) == 1
    assert state.open_positions[0].symbol == "BTCUSDT"

    signals_path = run_dir / "reports" / "signals.jsonl"
    lines = [json.loads(ln) for ln in signals_path.read_text().splitlines() if ln.strip()]
    stale = [ln for ln in lines if ln.get("reason") == "stale_bar"]
    assert len(stale) == 1
    assert stale[0]["symbol"] == "XRPUSDT"
    heartbeat = json.loads((run_dir / "state" / "heartbeat.json").read_text())
    assert heartbeat["last_scan_scanned"] == 2
    assert heartbeat["last_scan_dedup"] == 0
    assert heartbeat["last_scan_stale"] == 1
    assert heartbeat["last_scan_live"] == 1
    assert heartbeat["last_scan_opened"] == 1


def test_runner_rejects_opposing_direction_same_symbol(tmp_path, monkeypatch):
    """Portfolio gate V2 — no hedge acidental cross-engine.

    When two engines fire opposite-direction signals on the same symbol
    in the same tick (e.g. JUMP SHORT LINKUSDT + RENAISSANCE LONG
    LINKUSDT), the second one must be skipped. Policy is first-come-
    first-served — whoever opens first keeps the slot. Prevents paying
    entry+exit costs on a net-zero-exposure hedge (real 2026-04-21
    scenario reported via Telegram).
    """
    from tools.operations import millennium_paper as mp

    run_dir = tmp_path / "millennium_paper" / "OPP_TEST"
    for sub in ("state", "reports", "logs"):
        (run_dir / sub).mkdir(parents=True)

    monkeypatch.setattr(mp, "ROOT", tmp_path)
    monkeypatch.setattr(mp, "RUN_DIR", run_dir)
    monkeypatch.setattr(mp, "STATE_DIR", run_dir / "state")
    monkeypatch.setattr(mp, "REPORTS_DIR", run_dir / "reports")
    monkeypatch.setattr(mp, "LOGS_DIR", run_dir / "logs")
    monkeypatch.setattr(mp, "RUN_ID", "OPP_TEST")
    monkeypatch.setattr(mp, "TRADES_PATH", run_dir / "reports" / "trades.jsonl")
    monkeypatch.setattr(mp, "EQUITY_PATH", run_dir / "reports" / "equity.jsonl")
    monkeypatch.setattr(mp, "FILLS_PATH", run_dir / "reports" / "fills.jsonl")
    monkeypatch.setattr(mp, "SIGNALS_PATH", run_dir / "reports" / "signals.jsonl")
    monkeypatch.setattr(mp, "POSITIONS_PATH", run_dir / "state" / "positions.json")
    monkeypatch.setattr(mp, "ACCOUNT_PATH", run_dir / "state" / "account.json")
    monkeypatch.setattr(mp, "HEARTBEAT_PATH", run_dir / "state" / "heartbeat.json")

    from datetime import timedelta
    now = datetime.now(timezone.utc)
    ts1 = now.isoformat()
    ts2 = (now + timedelta(seconds=60)).isoformat()

    def fake_scan(notify=False):
        return [
            {"strategy": "JUMP", "symbol": "LINKUSDT", "direction": "SHORT",
             "entry": 9.35, "stop": 9.50, "target": 8.90, "size": 30.0,
             "timestamp": ts1, "open_ts": ts1},
            {"strategy": "RENAISSANCE", "symbol": "LINKUSDT", "direction": "LONG",
             "entry": 9.36, "stop": 9.30, "target": 9.43, "size": 57.0,
             "timestamp": ts2, "open_ts": ts2},
        ]
    monkeypatch.setattr(mp, "_scan_new_signals", fake_scan)
    monkeypatch.setattr(mp, "_fetch_new_bars", lambda s, since: [])

    state = mp.RunnerState(account_size=10_000.0)
    mp.run_one_tick(state, tick_idx=1, notify=False)

    # First-come-first-served: JUMP SHORT wins, RENAISSANCE LONG is skipped.
    assert len(state.open_positions) == 1
    assert state.open_positions[0].engine == "JUMP"
    assert state.open_positions[0].direction == "SHORT"

    signals_path = run_dir / "reports" / "signals.jsonl"
    lines = [json.loads(ln) for ln in signals_path.read_text().splitlines() if ln.strip()]
    rejected = [ln for ln in lines if ln.get("reason") == "direction_conflict"]
    assert len(rejected) == 1
    assert rejected[0]["engine"] == "RENAISSANCE"


def test_runner_allows_same_direction_same_symbol(tmp_path, monkeypatch):
    """V2 gate only blocks OPPOSITE directions. Same direction passes.

    Two engines concurring on the same direction is signal confluence,
    not conflict. Accumulation/averaging in is a legitimate strategy in
    live — let the operator decide via MAX_OPEN_POSITIONS.
    """
    from tools.operations import millennium_paper as mp

    run_dir = tmp_path / "millennium_paper" / "SAME_DIR_TEST"
    for sub in ("state", "reports", "logs"):
        (run_dir / sub).mkdir(parents=True)

    monkeypatch.setattr(mp, "ROOT", tmp_path)
    monkeypatch.setattr(mp, "RUN_DIR", run_dir)
    monkeypatch.setattr(mp, "STATE_DIR", run_dir / "state")
    monkeypatch.setattr(mp, "REPORTS_DIR", run_dir / "reports")
    monkeypatch.setattr(mp, "LOGS_DIR", run_dir / "logs")
    monkeypatch.setattr(mp, "RUN_ID", "SAME_DIR_TEST")
    monkeypatch.setattr(mp, "TRADES_PATH", run_dir / "reports" / "trades.jsonl")
    monkeypatch.setattr(mp, "EQUITY_PATH", run_dir / "reports" / "equity.jsonl")
    monkeypatch.setattr(mp, "FILLS_PATH", run_dir / "reports" / "fills.jsonl")
    monkeypatch.setattr(mp, "SIGNALS_PATH", run_dir / "reports" / "signals.jsonl")
    monkeypatch.setattr(mp, "POSITIONS_PATH", run_dir / "state" / "positions.json")
    monkeypatch.setattr(mp, "ACCOUNT_PATH", run_dir / "state" / "account.json")
    monkeypatch.setattr(mp, "HEARTBEAT_PATH", run_dir / "state" / "heartbeat.json")

    from datetime import timedelta
    now = datetime.now(timezone.utc)
    ts1 = now.isoformat()
    ts2 = (now + timedelta(seconds=60)).isoformat()

    def fake_scan(notify=False):
        return [
            {"strategy": "JUMP", "symbol": "LINKUSDT", "direction": "SHORT",
             "entry": 9.35, "stop": 9.50, "target": 8.90, "size": 30.0,
             "timestamp": ts1, "open_ts": ts1},
            {"strategy": "CITADEL", "symbol": "LINKUSDT", "direction": "SHORT",
             "entry": 9.36, "stop": 9.52, "target": 8.85, "size": 25.0,
             "timestamp": ts2, "open_ts": ts2},
        ]
    monkeypatch.setattr(mp, "_scan_new_signals", fake_scan)
    monkeypatch.setattr(mp, "_fetch_new_bars", lambda s, since: [])

    state = mp.RunnerState(account_size=10_000.0)
    mp.run_one_tick(state, tick_idx=1, notify=False)

    # Both SHORT LINKUSDT from different engines → both open (confluence).
    assert len(state.open_positions) == 2


def test_runner_rejects_stale_signal_post_prime(tmp_path, monkeypatch):
    """Even after prime, signals with historical timestamps must not open.

    Protects against residual backscan history leaking through on later
    ticks (e.g. a bar that flickered out of the DF and came back).
    """
    from tools.operations import millennium_paper as mp

    run_dir = tmp_path / "millennium_paper" / "STALE_TEST"
    for sub in ("state", "reports", "logs"):
        (run_dir / sub).mkdir(parents=True)

    monkeypatch.setattr(mp, "ROOT", tmp_path)
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
    assert state.novel_total == 0
    assert state.novel_since_prime == 0
    assert state.last_novel_at is None

    signals_path = run_dir / "reports" / "signals.jsonl"
    lines = [json.loads(ln) for ln in signals_path.read_text().splitlines() if ln.strip()]
    stale = [ln for ln in lines if ln.get("reason") == "stale_bar"]
    assert len(stale) == 1
    heartbeat = json.loads((run_dir / "state" / "heartbeat.json").read_text())
    assert heartbeat["last_scan_scanned"] == 1
    assert heartbeat["last_scan_dedup"] == 0
    assert heartbeat["last_scan_stale"] == 1
    assert heartbeat["last_scan_live"] == 0
    assert heartbeat["last_scan_opened"] == 0


def test_fetch_new_bars_filters_historical_when_since_is_tz_aware(monkeypatch):
    """Ghost-exit repro (2026-04-23 ARBUSDT RENAISSANCE).

    run_one_tick stores ``last_bar_ts_by_symbol[sym] = now_iso`` with an
    aware datetime. On the next tick _fetch_new_bars compared that aware
    cursor to df['time'] (naive from pd.to_datetime of Binance ms), which
    raised TypeError. The bare except: pass swallowed it and returned all
    20 candles — including the ~5h of history before the position opened.
    _walk_bars then triggered target/stop on a historical candle, forging
    a trade that never existed live.
    """
    import pandas as pd
    from tools.operations import millennium_paper as mp

    opened_at = datetime(2026, 4, 23, 0, 1, 23, tzinfo=timezone.utc)
    bars_naive_utc = pd.to_datetime([
        int((opened_at.timestamp() - 3600) * 1000),  # 1h before open
        int((opened_at.timestamp() - 60) * 1000),    # 1min before open
        int((opened_at.timestamp() + 900) * 1000),   # 15m after open
        int((opened_at.timestamp() + 1800) * 1000),  # 30m after open
    ], unit="ms")
    df = pd.DataFrame({
        "time": bars_naive_utc,
        "open":  [1.0, 1.0, 1.0, 1.0],
        "high":  [10.0, 10.0, 1.1, 1.2],
        "low":   [0.1, 0.1, 0.9, 0.9],
        "close": [1.0, 1.0, 1.0, 1.0],
        "vol":   [0.0, 0.0, 0.0, 0.0],
        "tbb":   [0.0, 0.0, 0.0, 0.0],
    })
    monkeypatch.setattr("core.data.fetch", lambda *a, **k: df)

    new_bars = mp._fetch_new_bars("ARBUSDT", opened_at.isoformat())

    assert len(new_bars) == 2, (
        f"expected 2 bars strictly after open, got {len(new_bars)}: "
        f"{[b['time'] for b in new_bars]}"
    )
    for b in new_bars:
        ts = datetime.fromisoformat(b["time"].replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        assert ts > opened_at
