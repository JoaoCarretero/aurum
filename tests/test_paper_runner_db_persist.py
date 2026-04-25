"""Tests for `_persist_trade_to_db` in tools/operations/millennium_paper.py.

Verifies the new "paper close → SQL" hook:
  - happy path: trade record lands in live_trades with correct fields
  - field aliasing: engine→strategy, entry_at→ts, pnl_after_fees→pnl_usd
  - resilience: missing DB file = silent skip (does not raise)
  - resilience: corrupt DB = silent log (does not raise)
  - idempotency: double-close (re-flatten same trade) = single row
"""
from __future__ import annotations

import importlib
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def isolated_runner(tmp_path: Path, monkeypatch):
    """Return millennium_paper module bound to a tmp ROOT (via monkeypatch).

    `mp.ROOT` is computed from __file__ at import time, so chdir alone
    doesn't redirect — we patch the module attribute directly. The
    helper reads `ROOT / "data" / "aurum.db"` lazily on each call,
    so monkeypatch suffices without reload.
    """
    monkeypatch.setenv("AURUM_PAPER_LABEL", "test-runner")
    (tmp_path / "data").mkdir()

    # Apply migrations to the tmp DB.
    db = tmp_path / "data" / "aurum.db"
    conn = sqlite3.connect(str(db))
    from tools.maintenance.migrations import (
        migration_001_live_runs,
        migration_002_live_trades,
    )
    migration_001_live_runs.apply(conn)
    migration_002_live_trades.apply(conn)
    conn.close()

    import tools.operations.millennium_paper as mp
    monkeypatch.setattr(mp, "ROOT", tmp_path)
    return mp, tmp_path


def _trade_record(symbol="BTCUSDT", **overrides) -> dict:
    """Sample trade record matching what the paper runner emits."""
    base = {
        "id": "pos_1", "engine": "citadel", "symbol": symbol,
        "direction": "long",
        "entry_price": 50000.0, "exit_price": 50500.0,
        "stop": 49500.0, "target": 51000.0,
        "size": 0.001, "notional": 50.0,
        "entry_at": "2026-04-25T10:00:00Z",
        "exit_at": "2026-04-25T11:00:00Z",
        "exit_reason": "target",
        "pnl": 0.5, "pnl_after_fees": 0.45,
        "r_multiple": 1.0, "bars_held": 4,
        "primed": False,
    }
    base.update(overrides)
    return base


def test_persist_writes_to_live_trades(isolated_runner):
    """Happy path — record lands in DB with all expected fields."""
    mp, tmp_path = isolated_runner
    rec = _trade_record()
    mp._persist_trade_to_db(rec)

    conn = sqlite3.connect(str(tmp_path / "data" / "aurum.db"))
    rows = conn.execute(
        "SELECT run_id, ts, symbol, strategy, direction, entry, exit, "
        "exit_ts, pnl_usd, exit_reason, r_multiple, size_usd FROM live_trades"
    ).fetchall()
    conn.close()

    assert len(rows) == 1
    row = rows[0]
    assert row[0] == mp.RUN_ID
    assert row[1] == "2026-04-25T10:00:00Z"  # entry_at → ts
    assert row[2] == "BTCUSDT"
    assert row[3] == "citadel"  # engine → strategy
    assert row[4] == "long"
    assert row[5] == 50000.0
    assert row[6] == 50500.0
    assert row[7] == "2026-04-25T11:00:00Z"
    assert row[8] == 0.45  # pnl_after_fees -> pnl_usd
    assert row[9] == "target"
    assert row[10] == 1.0
    assert row[11] == 50.0


def test_persist_idempotent_on_double_close(isolated_runner):
    """Calling twice with same trade = single row (UPSERT behaviour)."""
    mp, tmp_path = isolated_runner
    rec = _trade_record()
    mp._persist_trade_to_db(rec)
    mp._persist_trade_to_db(rec)
    mp._persist_trade_to_db(rec)

    conn = sqlite3.connect(str(tmp_path / "data" / "aurum.db"))
    n = conn.execute("SELECT COUNT(*) FROM live_trades").fetchone()[0]
    conn.close()
    assert n == 1


def test_persist_silent_when_db_missing(tmp_path, monkeypatch):
    """No DB file = silent skip. Trade close path must not raise."""
    # tmp_path has no data/aurum.db
    import tools.operations.millennium_paper as mp
    monkeypatch.setattr(mp, "ROOT", tmp_path)
    # Must NOT raise
    mp._persist_trade_to_db(_trade_record())


def test_persist_silent_when_corrupt_db(tmp_path, monkeypatch):
    """Corrupted DB file = silent log, never raise."""
    (tmp_path / "data").mkdir()
    bad_db = tmp_path / "data" / "aurum.db"
    bad_db.write_bytes(b"not a sqlite file at all")

    import tools.operations.millennium_paper as mp
    monkeypatch.setattr(mp, "ROOT", tmp_path)
    # Must NOT raise
    mp._persist_trade_to_db(_trade_record())


def test_persist_skips_invalid_record(isolated_runner):
    """Missing required fields = upsert returns False, no row added."""
    mp, tmp_path = isolated_runner
    bad_rec = {"engine": "citadel"}  # no symbol, no direction, no entry
    mp._persist_trade_to_db(bad_rec)

    conn = sqlite3.connect(str(tmp_path / "data" / "aurum.db"))
    n = conn.execute("SELECT COUNT(*) FROM live_trades").fetchone()[0]
    conn.close()
    assert n == 0


def test_persist_multi_trade_distinct_run_ids(isolated_runner):
    """Two trades in same run end up in DB as 2 rows (different ts)."""
    mp, tmp_path = isolated_runner
    mp._persist_trade_to_db(_trade_record(symbol="BTCUSDT",
                                            entry_at="2026-04-25T10:00:00Z"))
    mp._persist_trade_to_db(_trade_record(symbol="ETHUSDT",
                                            entry_at="2026-04-25T11:00:00Z"))
    mp._persist_trade_to_db(_trade_record(symbol="AVAXUSDT",
                                            entry_at="2026-04-25T12:00:00Z"))

    conn = sqlite3.connect(str(tmp_path / "data" / "aurum.db"))
    syms = [r[0] for r in conn.execute(
        "SELECT symbol FROM live_trades ORDER BY ts").fetchall()]
    conn.close()
    assert syms == ["BTCUSDT", "ETHUSDT", "AVAXUSDT"]


def test_persist_does_not_modify_input_record(isolated_runner):
    """Helper must not mutate the caller's dict (paranoid contract)."""
    mp, tmp_path = isolated_runner
    rec = _trade_record()
    snapshot = dict(rec)
    mp._persist_trade_to_db(rec)
    assert rec == snapshot, "_persist_trade_to_db mutated input dict"


# ─── _persist_signal_to_db ──────────────────────────────────────────


def _signal_record(symbol="XRPUSDT", **overrides) -> dict:
    """Sample signal dict — matches what _collect_live_signals emits.

    JUMP/CITADEL/RENAISSANCE all share the canonical keys (timestamp,
    symbol, direction, entry, stop, target) plus engine-specific extras.
    """
    base = {
        "timestamp": "2026-04-25 16:00:00",
        "symbol": symbol,
        "strategy": "JUMP",
        "direction": "LONG",
        "entry": 1.4285, "stop": 1.4239, "target": 1.4407,
        "rr": 2.65, "score": 0.801,
        "macro_bias": "BULL", "vol_regime": "NORMAL",
        "primed": False,
        # engine-specific extras land in details_json
        "trade_type": "ORDER-FLOW", "struct": "DOWN", "cascade_n": 0,
    }
    base.update(overrides)
    return base


def test_persist_signal_writes_to_live_signals(isolated_runner):
    """Happy path — signal lands in live_signals with canonical fields."""
    mp, tmp_path = isolated_runner
    rec = _signal_record()
    observed_at = "2026-04-25T16:16:40Z"
    mp._persist_signal_to_db(rec, observed_at=observed_at)

    conn = sqlite3.connect(str(tmp_path / "data" / "aurum.db"))
    rows = conn.execute(
        "SELECT run_id, observed_at, signal_ts, symbol, strategy, "
        "direction, entry, stop, target, score, primed FROM live_signals"
    ).fetchall()
    conn.close()

    assert len(rows) == 1
    row = rows[0]
    assert row[0] == mp.RUN_ID
    assert row[1] == observed_at
    assert row[2] == "2026-04-25 16:00:00"  # timestamp → signal_ts
    assert row[3] == "XRPUSDT"
    assert row[4] == "JUMP"
    assert row[5] == "LONG"
    assert row[6] == 1.4285
    assert row[7] == 1.4239
    assert row[8] == 1.4407
    assert row[9] == 0.801
    assert row[10] == 0  # primed=False → 0


def test_persist_signal_preserves_engine_extras(isolated_runner):
    """Engine-specific fields (trade_type, struct, cascade_n) survive
    in details_json — operator can SQL-query JUMP signals by struct."""
    import json
    mp, tmp_path = isolated_runner
    mp._persist_signal_to_db(_signal_record(),
                              observed_at="2026-04-25T16:16:40Z")

    conn = sqlite3.connect(str(tmp_path / "data" / "aurum.db"))
    raw = conn.execute(
        "SELECT details_json FROM live_signals").fetchone()[0]
    conn.close()
    parsed = json.loads(raw)
    assert parsed["trade_type"] == "ORDER-FLOW"
    assert parsed["struct"] == "DOWN"
    assert parsed["cascade_n"] == 0
    # No double-wrap — defends fix #1 at the integration level
    assert "details_json" not in parsed


def test_persist_signal_aliases_engine_to_strategy(isolated_runner):
    """Engine writers use 'engine' (paper-runner term); table column
    is 'strategy'. Hook should map engine→strategy if strategy missing."""
    mp, tmp_path = isolated_runner
    rec = _signal_record()
    rec.pop("strategy")
    rec["engine"] = "JUMP"
    mp._persist_signal_to_db(rec, observed_at="2026-04-25T16:16:40Z")

    conn = sqlite3.connect(str(tmp_path / "data" / "aurum.db"))
    row = conn.execute(
        "SELECT strategy FROM live_signals").fetchone()
    conn.close()
    assert row[0] == "JUMP"


def test_persist_signal_idempotent(isolated_runner):
    """Same (run_id, observed_at, symbol) = single row."""
    mp, tmp_path = isolated_runner
    rec = _signal_record()
    obs = "2026-04-25T16:16:40Z"
    mp._persist_signal_to_db(rec, observed_at=obs)
    mp._persist_signal_to_db(rec, observed_at=obs)
    mp._persist_signal_to_db(rec, observed_at=obs)

    conn = sqlite3.connect(str(tmp_path / "data" / "aurum.db"))
    n = conn.execute("SELECT COUNT(*) FROM live_signals").fetchone()[0]
    conn.close()
    assert n == 1


def test_persist_signal_silent_when_db_missing(tmp_path, monkeypatch):
    """No DB file = silent skip. Tick loop must not depend on DB."""
    import tools.operations.millennium_paper as mp
    monkeypatch.setattr(mp, "ROOT", tmp_path)
    mp._persist_signal_to_db(_signal_record(),
                              observed_at="2026-04-25T16:16:40Z")


def test_persist_signal_silent_when_corrupt_db(tmp_path, monkeypatch):
    """Corrupt DB = silent log, never raise."""
    (tmp_path / "data").mkdir()
    bad = tmp_path / "data" / "aurum.db"
    bad.write_bytes(b"not a sqlite file")
    import tools.operations.millennium_paper as mp
    monkeypatch.setattr(mp, "ROOT", tmp_path)
    mp._persist_signal_to_db(_signal_record(),
                              observed_at="2026-04-25T16:16:40Z")


def test_persist_signal_does_not_mutate_input(isolated_runner):
    """Hook must not mutate caller's dict (signal is reused downstream)."""
    mp, tmp_path = isolated_runner
    rec = _signal_record()
    snapshot = dict(rec)
    mp._persist_signal_to_db(rec, observed_at="2026-04-25T16:16:40Z")
    assert rec == snapshot, "_persist_signal_to_db mutated input dict"


def test_persist_signal_skips_when_required_missing(isolated_runner):
    """Without (symbol, direction, strategy) upsert returns False — no row."""
    mp, tmp_path = isolated_runner
    bad = {"timestamp": "2026-04-25 16:00:00"}
    mp._persist_signal_to_db(bad, observed_at="2026-04-25T16:16:40Z")

    conn = sqlite3.connect(str(tmp_path / "data" / "aurum.db"))
    n = conn.execute("SELECT COUNT(*) FROM live_signals").fetchone()[0]
    conn.close()
    assert n == 0
