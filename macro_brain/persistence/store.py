"""SQLite persistence layer for Macro Brain.

Isolated from data/aurum.db — macro gets its own DB at data/macro/macro_brain.db.
Zero risk of contamination with trade engine runs.

Schema:
  events              news, geopolitics (categorical + numeric sentiment)
  macro_data          FRED-style time-series (CPI, DXY, yields...)
  regime_snapshots    regime classification history
  theses              generated investment theses
  positions           open/closed positions (macro book)
  pnl_ledger          append-only P&L events
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from config.macro_params import MACRO_DB_PATH


SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id           TEXT PRIMARY KEY,
    ts           TEXT NOT NULL,
    ingested_ts  TEXT NOT NULL,
    source       TEXT NOT NULL,
    category     TEXT NOT NULL,
    headline     TEXT,
    body         TEXT,
    entities     TEXT,
    sentiment    REAL,
    impact       REAL,
    raw_json     TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_category ON events(category);
CREATE INDEX IF NOT EXISTS idx_events_source ON events(source);

CREATE TABLE IF NOT EXISTS macro_data (
    id        TEXT PRIMARY KEY,
    ts        TEXT NOT NULL,
    metric    TEXT NOT NULL,
    value     REAL NOT NULL,
    prev      REAL,
    expected  REAL,
    surprise  REAL,
    source    TEXT NOT NULL,
    UNIQUE(ts, metric, source)
);
CREATE INDEX IF NOT EXISTS idx_macro_ts ON macro_data(ts);
CREATE INDEX IF NOT EXISTS idx_macro_metric ON macro_data(metric);

CREATE TABLE IF NOT EXISTS regime_snapshots (
    id             TEXT PRIMARY KEY,
    ts             TEXT NOT NULL,
    regime         TEXT NOT NULL,
    confidence     REAL NOT NULL,
    features_json  TEXT NOT NULL,
    model_version  TEXT,
    reason         TEXT
);
CREATE INDEX IF NOT EXISTS idx_regime_ts ON regime_snapshots(ts);

CREATE TABLE IF NOT EXISTS theses (
    id                   TEXT PRIMARY KEY,
    created_ts           TEXT NOT NULL,
    regime_id            TEXT,
    direction            TEXT NOT NULL,
    asset                TEXT NOT NULL,
    confidence           REAL NOT NULL,
    rationale            TEXT,
    supporting_events    TEXT,
    target_horizon_days  INTEGER,
    invalidation_json    TEXT,
    status               TEXT NOT NULL DEFAULT 'pending',
    closed_ts            TEXT,
    close_reason         TEXT,
    FOREIGN KEY (regime_id) REFERENCES regime_snapshots(id)
);
CREATE INDEX IF NOT EXISTS idx_theses_status ON theses(status);
CREATE INDEX IF NOT EXISTS idx_theses_asset ON theses(asset);

CREATE TABLE IF NOT EXISTS positions (
    id              TEXT PRIMARY KEY,
    thesis_id       TEXT NOT NULL,
    asset           TEXT NOT NULL,
    side            TEXT NOT NULL,
    size_usd        REAL NOT NULL,
    leverage        REAL DEFAULT 1.0,
    entry_ts        TEXT NOT NULL,
    entry_price     REAL NOT NULL,
    exit_ts         TEXT,
    exit_price      REAL,
    pnl_realized    REAL DEFAULT 0.0,
    pnl_unrealized  REAL DEFAULT 0.0,
    status          TEXT NOT NULL DEFAULT 'open',
    FOREIGN KEY (thesis_id) REFERENCES theses(id)
);
CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);
CREATE INDEX IF NOT EXISTS idx_positions_asset ON positions(asset);

CREATE TABLE IF NOT EXISTS pnl_ledger (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    position_id     TEXT,
    asset           TEXT,
    pnl_delta       REAL NOT NULL,
    account_equity  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pnl_ts ON pnl_ledger(ts);

CREATE TABLE IF NOT EXISTS whale_snapshots (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    venue      TEXT NOT NULL,
    address    TEXT NOT NULL,
    asset      TEXT NOT NULL,
    side       TEXT NOT NULL,
    size_usd   REAL NOT NULL,
    leverage   REAL,
    entry_px   REAL,
    mark_px    REAL,
    raw_json   TEXT
);
CREATE INDEX IF NOT EXISTS idx_whale_addr_asset
    ON whale_snapshots(venue, address, asset, ts);
CREATE INDEX IF NOT EXISTS idx_whale_ts ON whale_snapshots(ts);
"""


def _ensure_dir():
    MACRO_DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def init_db():
    """Create schema if not exists. Idempotent."""
    _ensure_dir()
    with _conn() as c:
        c.executescript(SCHEMA)


@contextmanager
def _conn():
    """Context-managed connection with dict row factory + auto-commit."""
    _ensure_dir()
    conn = sqlite3.connect(str(MACRO_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _now() -> str:
    return datetime.utcnow().isoformat()


# ── EVENTS ───────────────────────────────────────────────────

def insert_event(
    ts: str, source: str, category: str,
    headline: str | None = None, body: str | None = None,
    entities: list[str] | None = None, sentiment: float | None = None,
    impact: float | None = None, raw: dict | None = None,
) -> str:
    eid = str(uuid.uuid4())
    with _conn() as c:
        c.execute(
            "INSERT INTO events (id, ts, ingested_ts, source, category, headline, "
            "body, entities, sentiment, impact, raw_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (eid, ts, _now(), source, category, headline, body,
             json.dumps(entities or []), sentiment, impact,
             json.dumps(raw or {})),
        )
    return eid


def recent_events(
    category: str | None = None, source: str | None = None, limit: int = 100,
) -> list[dict]:
    q = "SELECT * FROM events WHERE 1=1"
    params: list = []
    if category:
        q += " AND category = ?"; params.append(category)
    if source:
        q += " AND source = ?"; params.append(source)
    q += " ORDER BY ts DESC LIMIT ?"
    params.append(limit)
    with _conn() as c:
        rows = c.execute(q, params).fetchall()
    return [dict(r) for r in rows]


# ── MACRO DATA (FRED-like) ───────────────────────────────────

def insert_macro(
    ts: str, metric: str, value: float, source: str,
    prev: float | None = None, expected: float | None = None,
) -> str | None:
    """Returns id if inserted, None if duplicate (uniqueness on ts+metric+source)."""
    mid = str(uuid.uuid4())
    surprise = (value - expected) if expected is not None else None
    try:
        with _conn() as c:
            c.execute(
                "INSERT INTO macro_data (id, ts, metric, value, prev, expected, surprise, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (mid, ts, metric, value, prev, expected, surprise, source),
            )
        return mid
    except sqlite3.IntegrityError:
        return None  # dedupe


def latest_macro(metric: str, n: int = 1) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM macro_data WHERE metric = ? ORDER BY ts DESC LIMIT ?",
            (metric, n),
        ).fetchall()
    return [dict(r) for r in rows]


def latest_macro_many(
    metrics: list[str] | tuple[str, ...], n: int = 1,
) -> dict[str, list[dict]]:
    """Fetch latest rows for multiple metrics, capped per metric."""
    ordered_metrics = [str(metric) for metric in metrics if str(metric)]
    if not ordered_metrics:
        return {}
    placeholders = ", ".join("?" for _ in ordered_metrics)
    q = f"""
        SELECT * FROM (
            SELECT
                macro_data.*,
                ROW_NUMBER() OVER (
                    PARTITION BY metric
                    ORDER BY ts DESC
                ) AS rn
            FROM macro_data
            WHERE metric IN ({placeholders})
        )
        WHERE rn <= ?
        ORDER BY metric ASC, ts DESC
    """
    grouped: dict[str, list[dict]] = {metric: [] for metric in ordered_metrics}
    with _conn() as c:
        rows = c.execute(q, [*ordered_metrics, int(n)]).fetchall()
    for row in rows:
        payload = dict(row)
        metric = str(payload["metric"])
        payload.pop("rn", None)
        grouped.setdefault(metric, []).append(payload)
    return grouped


# ── WHALE SNAPSHOTS (bot watchers) ───────────────────────────

def insert_whale_snapshot(
    venue: str, address: str, asset: str, side: str, size_usd: float,
    leverage: float | None = None, entry_px: float | None = None,
    mark_px: float | None = None, raw: dict | None = None,
) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO whale_snapshots (ts, venue, address, asset, side, "
            "size_usd, leverage, entry_px, mark_px, raw_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (_now(), venue, address, asset, side, size_usd,
             leverage, entry_px, mark_px, json.dumps(raw or {})),
        )


def latest_whale_snapshot(
    venue: str, address: str, asset: str,
) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM whale_snapshots WHERE venue = ? AND address = ? "
            "AND asset = ? ORDER BY ts DESC LIMIT 1",
            (venue, address, asset),
        ).fetchone()
    return dict(row) if row else None


def macro_series(metric: str, since: str | None = None) -> list[dict]:
    q = "SELECT ts, value FROM macro_data WHERE metric = ?"
    params: list = [metric]
    if since:
        q += " AND ts >= ?"; params.append(since)
    q += " ORDER BY ts ASC"
    with _conn() as c:
        rows = c.execute(q, params).fetchall()
    return [dict(r) for r in rows]


def macro_series_many(
    metrics: list[str] | tuple[str, ...], since: str | None = None,
) -> dict[str, list[dict]]:
    """Fetch multiple macro series in one query, grouped by metric."""
    ordered_metrics = [str(metric) for metric in metrics if str(metric)]
    if not ordered_metrics:
        return {}
    placeholders = ", ".join("?" for _ in ordered_metrics)
    q = (
        "SELECT metric, ts, value FROM macro_data "
        f"WHERE metric IN ({placeholders})"
    )
    params: list[Any] = list(ordered_metrics)
    if since:
        q += " AND ts >= ?"
        params.append(since)
    q += " ORDER BY metric ASC, ts ASC"
    grouped: dict[str, list[dict]] = {metric: [] for metric in ordered_metrics}
    with _conn() as c:
        rows = c.execute(q, params).fetchall()
    for row in rows:
        payload = dict(row)
        metric = str(payload.pop("metric"))
        grouped.setdefault(metric, []).append(payload)
    return grouped


# ── REGIME ───────────────────────────────────────────────────

def insert_regime(
    regime: str, confidence: float, features: dict,
    model_version: str = "v1.0", reason: str = "",
) -> str:
    rid = str(uuid.uuid4())
    with _conn() as c:
        c.execute(
            "INSERT INTO regime_snapshots (id, ts, regime, confidence, features_json, "
            "model_version, reason) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (rid, _now(), regime, confidence, json.dumps(features),
             model_version, reason),
        )
    return rid


def latest_regime() -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM regime_snapshots ORDER BY ts DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


# ── THESES ───────────────────────────────────────────────────

def insert_thesis(
    direction: str, asset: str, confidence: float,
    regime_id: str | None = None, rationale: str = "",
    supporting_events: list[str] | None = None,
    target_horizon_days: int = 30,
    invalidation: list[dict] | None = None,
) -> str:
    tid = str(uuid.uuid4())
    with _conn() as c:
        c.execute(
            "INSERT INTO theses (id, created_ts, regime_id, direction, asset, "
            "confidence, rationale, supporting_events, target_horizon_days, "
            "invalidation_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (tid, _now(), regime_id, direction, asset, confidence, rationale,
             json.dumps(supporting_events or []), target_horizon_days,
             json.dumps(invalidation or [])),
        )
    return tid


def active_theses() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM theses WHERE status IN ('pending','active') "
            "ORDER BY created_ts DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def update_thesis_status(thesis_id: str, status: str, reason: str = ""):
    with _conn() as c:
        c.execute(
            "UPDATE theses SET status = ?, closed_ts = ?, close_reason = ? "
            "WHERE id = ?",
            (status, _now() if status in ("closed", "invalidated") else None,
             reason, thesis_id),
        )


# ── POSITIONS ────────────────────────────────────────────────

def insert_position(
    thesis_id: str, asset: str, side: str,
    size_usd: float, entry_price: float, leverage: float = 1.0,
) -> str:
    pid = str(uuid.uuid4())
    with _conn() as c:
        c.execute(
            "INSERT INTO positions (id, thesis_id, asset, side, size_usd, "
            "leverage, entry_ts, entry_price) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (pid, thesis_id, asset, side, size_usd, leverage, _now(), entry_price),
        )
    return pid


def open_positions() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM positions WHERE status = 'open' ORDER BY entry_ts DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def close_position(position_id: str, exit_price: float, pnl: float):
    with _conn() as c:
        c.execute(
            "UPDATE positions SET exit_ts = ?, exit_price = ?, pnl_realized = ?, "
            "status = 'closed' WHERE id = ?",
            (_now(), exit_price, pnl, position_id),
        )


# ── PNL ──────────────────────────────────────────────────────

def log_pnl(event_type: str, pnl_delta: float, account_equity: float,
            position_id: str | None = None, asset: str | None = None):
    with _conn() as c:
        c.execute(
            "INSERT INTO pnl_ledger (ts, event_type, position_id, asset, "
            "pnl_delta, account_equity) VALUES (?, ?, ?, ?, ?, ?)",
            (_now(), event_type, position_id, asset, pnl_delta, account_equity),
        )


def pnl_summary() -> dict:
    with _conn() as c:
        total = c.execute(
            "SELECT COALESCE(SUM(pnl_delta), 0) FROM pnl_ledger"
        ).fetchone()[0]
        equity_row = c.execute(
            "SELECT account_equity FROM pnl_ledger ORDER BY ts DESC LIMIT 1"
        ).fetchone()
    from config.macro_params import MACRO_ACCOUNT_SIZE
    return {
        "total_pnl": total,
        "equity": equity_row[0] if equity_row else MACRO_ACCOUNT_SIZE,
        "initial": MACRO_ACCOUNT_SIZE,
    }


if __name__ == "__main__":
    init_db()
    print(f"DB initialized at {MACRO_DB_PATH}")
