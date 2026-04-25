"""Helpers for live_trades + live_signals SQLite tables.

Mirror of `db_live_runs.py` — separates DB I/O from the runners and
sync tools that produce/consume these rows.

Both tables use UPSERT-by-natural-key semantics so rerunning a sync
is idempotent (no dupes if the same trade/signal is fed twice from
JSONL OR cockpit endpoint).

  live_trades   key: (run_id, ts, symbol)
  live_signals  key: (run_id, observed_at, symbol)
"""
from __future__ import annotations

import json
import sqlite3
from typing import Iterable

# ─── Field whitelists ──────────────────────────────────────────────
# Columns we recognize and persist to typed columns. Anything else in
# the source dict is preserved in `details_json`.

_TRADE_COLS = (
    "ts", "symbol", "strategy", "direction",
    "entry", "exit", "exit_ts", "exit_reason",
    "pnl_usd", "pnl_pct", "r_multiple",
    "size_usd", "stop", "target",
    "slippage_usd", "commission_usd", "funding_usd",
    "score", "macro_bias", "vol_regime",
)

_SIGNAL_COLS = (
    "observed_at", "signal_ts", "symbol", "strategy", "pattern",
    "direction", "entry", "stop", "target", "rr",
    "score", "entropy_norm", "hurst", "macro_bias", "vol_regime",
    "primed",
)


# ─── Field normalisation ───────────────────────────────────────────


def _norm_trade(payload: dict) -> dict:
    """Map various JSONL/cockpit field names to canonical column names.

    Paper trades.jsonl tends to use 'entry'/'exit'/'pnl_usd'.
    Older variants used 'entry_price'/'exit_price'/'pnl'.
    Cockpit endpoint mirrors the JSONL shape.
    """
    p = dict(payload)
    # Aliases — if canonical missing, try alternatives.
    aliases = {
        "ts": ("ts", "open_ts", "open_time", "timestamp"),
        "entry": ("entry", "entry_price"),
        "exit": ("exit", "exit_price"),
        "exit_ts": ("exit_ts", "close_ts", "exit_time"),
        "pnl_usd": ("pnl_usd", "pnl"),
        "size_usd": ("size_usd", "size", "notional"),
    }
    out: dict = {}
    for canon, alts in aliases.items():
        for alt in alts:
            if alt in p and p[alt] is not None:
                out[canon] = p[alt]
                break
    # Direct copy for fields without aliases.
    for col in _TRADE_COLS:
        if col not in out and col in p and p[col] is not None:
            out[col] = p[col]
    # Stash the rest for completeness.
    extras = {k: v for k, v in p.items()
              if k not in out and k not in aliases}
    out["details_json"] = json.dumps(extras) if extras else None
    return out


def _norm_signal(payload: dict) -> dict:
    """Map shadow_trades.jsonl fields to live_signals columns.

    Shadow records use 'shadow_observed_at' for the canonical
    observed_at field, and 'timestamp' for the candle-time signal_ts.
    'direction' is BULLISH/BEARISH (renaissance vocab).
    """
    p = dict(payload)
    out: dict = {}
    if p.get("shadow_observed_at"):
        out["observed_at"] = p["shadow_observed_at"]
    elif p.get("observed_at"):
        out["observed_at"] = p["observed_at"]
    if p.get("timestamp"):
        out["signal_ts"] = p["timestamp"]
    # `primed` is bool in JSONL; normalise to 0/1 for SQLite.
    if "primed" in p:
        out["primed"] = 1 if p["primed"] else 0
    # Direct copy.
    for col in _SIGNAL_COLS:
        if col not in out and col in p and p[col] is not None:
            out[col] = p[col]
    extras = {k: v for k, v in p.items()
              if k not in out
              and k not in ("shadow_observed_at", "timestamp",
                            "shadow_run_id")}
    out["details_json"] = json.dumps(extras) if extras else None
    return out


# ─── Public API ─────────────────────────────────────────────────────


def upsert_trade(conn: sqlite3.Connection, run_id: str, payload: dict) -> bool:
    """Insert or update a live paper trade. Returns True if inserted."""
    norm = _norm_trade(payload)
    if "ts" not in norm or "symbol" not in norm or "direction" not in norm:
        return False
    if "entry" not in norm:
        return False
    cols = ["run_id"] + list(norm.keys())
    placeholders = ",".join("?" * len(cols))
    updates = ",".join(f"{c}=excluded.{c}" for c in norm.keys())
    sql = (
        f"INSERT INTO live_trades ({','.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(run_id, ts, symbol) DO UPDATE SET {updates}"
    )
    values = [run_id] + [norm[c] for c in norm.keys()]
    cur = conn.execute(sql, values)
    return cur.rowcount > 0


def upsert_signal(conn: sqlite3.Connection, run_id: str, payload: dict) -> bool:
    """Insert or update a live shadow signal. Returns True if inserted."""
    norm = _norm_signal(payload)
    if ("observed_at" not in norm or "symbol" not in norm
            or "direction" not in norm or "strategy" not in norm):
        return False
    cols = ["run_id"] + list(norm.keys())
    placeholders = ",".join("?" * len(cols))
    updates = ",".join(f"{c}=excluded.{c}" for c in norm.keys())
    sql = (
        f"INSERT INTO live_signals ({','.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(run_id, observed_at, symbol) "
        f"DO UPDATE SET {updates}"
    )
    values = [run_id] + [norm[c] for c in norm.keys()]
    cur = conn.execute(sql, values)
    return cur.rowcount > 0


def upsert_trades_bulk(conn: sqlite3.Connection,
                       run_id: str,
                       payloads: Iterable[dict]) -> int:
    """Bulk upsert. Returns number of rows touched."""
    n = 0
    for p in payloads:
        if upsert_trade(conn, run_id, p):
            n += 1
    return n


def upsert_signals_bulk(conn: sqlite3.Connection,
                         run_id: str,
                         payloads: Iterable[dict]) -> int:
    """Bulk upsert. Returns number of rows touched."""
    n = 0
    for p in payloads:
        if upsert_signal(conn, run_id, p):
            n += 1
    return n


def list_trades_for_run(conn: sqlite3.Connection,
                         run_id: str,
                         limit: int = 200) -> list[dict]:
    """Return live_trades for a run, ordered by ts DESC."""
    cur = conn.execute(
        "SELECT * FROM live_trades WHERE run_id = ? "
        "ORDER BY ts DESC LIMIT ?",
        (run_id, limit),
    )
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def list_signals_for_run(conn: sqlite3.Connection,
                           run_id: str,
                           limit: int = 200) -> list[dict]:
    """Return live_signals for a run, ordered by observed_at DESC."""
    cur = conn.execute(
        "SELECT * FROM live_signals WHERE run_id = ? "
        "ORDER BY observed_at DESC LIMIT ?",
        (run_id, limit),
    )
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]
