"""Migration 002 — create live_trades + live_signals tables.

Adds the missing piece of the live-engine data model: until now,
`live_runs` carried metadata only (tick_count, equity, status), and
the actual trades/signals lived ONLY in JSONL files inside run_dirs.
This made it impossible to query "all paper trades for citadel today"
or "every shadow signal across the engine fleet" in SQL.

Two new tables:

  live_trades   — paper trade lifecycle (entry → exit + cost decomp)
                  Source: <run_dir>/reports/trades.jsonl on disk OR
                          GET /v1/runs/{id}/trades on cockpit
                  Engines that write here: paper runners (millennium_paper
                  + per-engine paper). Shadow does NOT — it has no exit
                  lifecycle. UNIQUE(run_id, ts, symbol) prevents dupes.

  live_signals  — shadow signal emissions (no exit lifecycle)
                  Source: <run_dir>/reports/shadow_trades.jsonl
                  (despite the name, shadow_trades.jsonl is signal records,
                  not trade outcomes — shadow only EMITS, never closes)
                  UNIQUE(run_id, observed_at, symbol) prevents dupes.

Both FK on live_runs.run_id (informal — SQLite doesn't enforce by
default, but the column is the right shape for joins). Indexed on
(symbol, ts) for "show last 50 trades on AVAXUSDT across all engines"
queries and (strategy, ts) for per-engine slicing.

Idempotent. Safe to re-run.
"""
from __future__ import annotations

import sqlite3

DDL = """
CREATE TABLE IF NOT EXISTS live_trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL,
    ts              TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    strategy        TEXT,
    direction       TEXT NOT NULL,
    entry           REAL NOT NULL,
    exit            REAL,
    exit_ts         TEXT,
    exit_reason     TEXT,
    pnl_usd         REAL,
    pnl_pct         REAL,
    r_multiple      REAL,
    size_usd        REAL,
    stop            REAL,
    target          REAL,
    slippage_usd    REAL,
    commission_usd  REAL,
    funding_usd     REAL,
    score           REAL,
    macro_bias      TEXT,
    vol_regime      TEXT,
    details_json    TEXT,
    UNIQUE(run_id, ts, symbol)
);
CREATE INDEX IF NOT EXISTS idx_live_trades_run
    ON live_trades(run_id);
CREATE INDEX IF NOT EXISTS idx_live_trades_symbol_ts
    ON live_trades(symbol, ts DESC);
CREATE INDEX IF NOT EXISTS idx_live_trades_strategy_ts
    ON live_trades(strategy, ts DESC);

CREATE TABLE IF NOT EXISTS live_signals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL,
    observed_at     TEXT NOT NULL,
    signal_ts       TEXT,
    symbol          TEXT NOT NULL,
    strategy        TEXT NOT NULL,
    pattern         TEXT,
    direction       TEXT NOT NULL,
    entry           REAL,
    stop            REAL,
    target          REAL,
    rr              REAL,
    score           REAL,
    entropy_norm    REAL,
    hurst           TEXT,
    macro_bias      TEXT,
    vol_regime      TEXT,
    primed          INTEGER NOT NULL DEFAULT 0,
    details_json    TEXT,
    UNIQUE(run_id, observed_at, symbol)
);
CREATE INDEX IF NOT EXISTS idx_live_signals_run
    ON live_signals(run_id);
CREATE INDEX IF NOT EXISTS idx_live_signals_symbol_obs
    ON live_signals(symbol, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_live_signals_strategy_obs
    ON live_signals(strategy, observed_at DESC);
"""


def apply(conn: sqlite3.Connection) -> None:
    """Apply migration 002 to an open connection. Idempotent.

    executescript() issues an implicit COMMIT before running; the
    explicit commit at the end is a belt-and-suspenders guard.
    """
    conn.executescript(DDL)
    conn.commit()
