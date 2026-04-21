"""Migration 001 — create live_runs table + indexes.

Idempotent: uses IF NOT EXISTS. Safe to apply multiple times.
"""
from __future__ import annotations

import sqlite3

DDL = """
CREATE TABLE IF NOT EXISTS live_runs (
    run_id       TEXT PRIMARY KEY,
    engine       TEXT NOT NULL,
    mode         TEXT NOT NULL
        CHECK(mode IN ('live','paper','shadow','demo','testnet')),
    started_at   TEXT NOT NULL,
    ended_at     TEXT,
    status       TEXT NOT NULL DEFAULT 'unknown',
    tick_count   INTEGER NOT NULL DEFAULT 0,
    novel_count  INTEGER NOT NULL DEFAULT 0,
    open_count   INTEGER NOT NULL DEFAULT 0,
    equity       REAL,
    last_tick_at TEXT,
    host         TEXT,
    label        TEXT,
    run_dir      TEXT NOT NULL,
    notes        TEXT
);
CREATE INDEX IF NOT EXISTS idx_live_runs_mode_started
    ON live_runs(mode, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_live_runs_engine_started
    ON live_runs(engine, started_at DESC);
"""


def apply(conn: sqlite3.Connection) -> None:
    """Apply migration 001 to an open connection. Idempotent."""
    conn.executescript(DDL)
    conn.commit()
