"""Tests for tools.maintenance.sync_vps_db — SSH-based mirror of
VPS sqlite live_trades + live_signals into local aurum.db.

Cockpit /trades works (after the alias fix), but /signals isn't on
the VPS deploy yet. SSH+sqlite dump is the robust fallback that
mirrors both tables via upsert (idempotent).
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest


@pytest.fixture
def vps_db(tmp_path):
    """A fake VPS DB populated with sample live_trades + live_signals."""
    db = tmp_path / "vps_aurum.db"
    conn = sqlite3.connect(str(db))
    from tools.maintenance.migrations import (
        migration_001_live_runs,
        migration_002_live_trades,
    )
    migration_001_live_runs.apply(conn)
    migration_002_live_trades.apply(conn)
    # one trade
    conn.execute(
        "INSERT INTO live_trades (run_id, ts, symbol, strategy, direction, "
        "entry, exit, exit_reason, pnl_usd) VALUES (?,?,?,?,?,?,?,?,?)",
        ("vps-run-1", "2026-04-25T16:16:40+00:00", "XRPUSDT",
         "JUMP", "LONG", 1.4285, 1.4239, "stop_initial", -17.85),
    )
    # one signal
    conn.execute(
        "INSERT INTO live_signals (run_id, observed_at, symbol, strategy, "
        "direction, entry, stop, target, score, primed) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("vps-run-2", "2026-04-25T17:00:00+00:00", "BTCUSDT",
         "CITADEL", "BULLISH", 100.0, 98.0, 105.0, 0.7, 0),
    )
    conn.commit()
    conn.close()
    return db


@pytest.fixture
def local_db(tmp_path):
    """Empty local aurum.db with schema applied."""
    db = tmp_path / "local_aurum.db"
    conn = sqlite3.connect(str(db))
    from tools.maintenance.migrations import (
        migration_001_live_runs,
        migration_002_live_trades,
    )
    migration_001_live_runs.apply(conn)
    migration_002_live_trades.apply(conn)
    conn.commit()
    conn.close()
    return db


def test_mirror_copies_trades_and_signals(vps_db, local_db):
    """End-to-end: vps_db → local_db gets the trade + signal."""
    from tools.maintenance.sync_vps_db import mirror_db_file

    n_trades, n_signals = mirror_db_file(str(vps_db), str(local_db))
    assert n_trades == 1
    assert n_signals == 1

    conn = sqlite3.connect(str(local_db))
    trades = list(conn.execute(
        "SELECT run_id, symbol, strategy, direction, exit_reason, pnl_usd "
        "FROM live_trades"
    ))
    assert trades == [("vps-run-1", "XRPUSDT", "JUMP", "LONG",
                       "stop_initial", -17.85)]

    signals = list(conn.execute(
        "SELECT run_id, symbol, strategy, direction, score "
        "FROM live_signals"
    ))
    assert signals == [("vps-run-2", "BTCUSDT", "CITADEL", "BULLISH", 0.7)]


def test_mirror_is_idempotent(vps_db, local_db):
    """Re-running mirror = same row count, no duplicates."""
    from tools.maintenance.sync_vps_db import mirror_db_file

    mirror_db_file(str(vps_db), str(local_db))
    mirror_db_file(str(vps_db), str(local_db))

    conn = sqlite3.connect(str(local_db))
    assert conn.execute("SELECT COUNT(*) FROM live_trades").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM live_signals").fetchone()[0] == 1


def test_mirror_does_not_clobber_local_only_rows(vps_db, local_db):
    """Local rows that don't exist on VPS stay intact after mirror."""
    from tools.maintenance.sync_vps_db import mirror_db_file

    # Insert a local-only row
    conn = sqlite3.connect(str(local_db))
    conn.execute(
        "INSERT INTO live_trades (run_id, ts, symbol, strategy, direction, "
        "entry, exit_reason, pnl_usd) VALUES (?,?,?,?,?,?,?,?)",
        ("local-only-run", "2026-04-24T10:00:00+00:00", "ETHUSDT",
         "RENAISSANCE", "LONG", 3000.0, "target", 25.0),
    )
    conn.commit()
    conn.close()

    mirror_db_file(str(vps_db), str(local_db))

    conn = sqlite3.connect(str(local_db))
    n = conn.execute("SELECT COUNT(*) FROM live_trades").fetchone()[0]
    assert n == 2  # local-only + vps-run-1


def test_mirror_handles_missing_vps_tables(tmp_path, local_db):
    """If VPS DB exists but tables don't, mirror returns (0,0) cleanly."""
    from tools.maintenance.sync_vps_db import mirror_db_file

    empty_vps = tmp_path / "empty_vps.db"
    sqlite3.connect(str(empty_vps)).close()

    n_trades, n_signals = mirror_db_file(str(empty_vps), str(local_db))
    assert n_trades == 0
    assert n_signals == 0
