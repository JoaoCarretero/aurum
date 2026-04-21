"""Test migration 001 — live_runs table DDL."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tools.maintenance.migrations import migration_001_live_runs as m


def _schema(conn: sqlite3.Connection, table: str) -> dict[str, str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {name: typ for (_, name, typ, *_) in rows}


def test_apply_creates_live_runs_table(tmp_path: Path) -> None:
    db = tmp_path / "a.db"
    conn = sqlite3.connect(db)
    m.apply(conn)
    cols = _schema(conn, "live_runs")
    assert "run_id" in cols
    assert "engine" in cols
    assert "mode" in cols
    assert "started_at" in cols
    assert "ended_at" in cols
    assert "status" in cols
    assert "tick_count" in cols
    assert "novel_count" in cols
    assert "open_count" in cols
    assert "equity" in cols
    assert "last_tick_at" in cols
    assert "host" in cols
    assert "label" in cols
    assert "run_dir" in cols
    assert "notes" in cols
    conn.close()


def test_apply_is_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "a.db"
    conn = sqlite3.connect(db)
    m.apply(conn)
    m.apply(conn)
    # PK enforced
    conn.execute(
        "INSERT INTO live_runs(run_id, engine, mode, started_at, run_dir) "
        "VALUES ('r1', 'citadel', 'paper', '2026-04-20T00:00:00Z', 'd/r1')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO live_runs(run_id, engine, mode, started_at, run_dir) "
            "VALUES ('r1', 'citadel', 'paper', '2026-04-20T00:00:00Z', 'd/r1')"
        )
    conn.close()


def test_apply_enforces_mode_check(tmp_path: Path) -> None:
    db = tmp_path / "a.db"
    conn = sqlite3.connect(db)
    m.apply(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO live_runs(run_id, engine, mode, started_at, run_dir) "
            "VALUES ('r1', 'citadel', 'BOGUS', '2026-04-20T00:00:00Z', 'd/r1')"
        )
    conn.close()


def test_apply_creates_indexes(tmp_path: Path) -> None:
    db = tmp_path / "a.db"
    conn = sqlite3.connect(db)
    m.apply(conn)
    idx = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' "
        "AND tbl_name='live_runs'"
    ).fetchall()]
    assert "idx_live_runs_mode_started" in idx
    assert "idx_live_runs_engine_started" in idx
    conn.close()
