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
        "size": 0.001,
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
        "exit_reason, pnl_usd, r_multiple FROM live_trades"
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
    assert row[7] == "target"
    assert row[8] == 0.45  # pnl_after_fees → pnl_usd
    assert row[9] == 1.0


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
