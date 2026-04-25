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
import threading
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


# SQLite binds only str/int/float/bytes/None natively. Engine records
# arrive with pandas Timestamps (df-index values) and datetime objects.
# Coerce to ISO strings on the way in so the upsert never raises
# "Error binding parameter X: type 'Timestamp' is not supported" — that
# silent WARNING dropped every shadow signal from live_signals on VPS
# until 2026-04-25.
_TS_FIELDS_TRADE = ("ts", "exit_ts")
_TS_FIELDS_SIGNAL = ("observed_at", "signal_ts")


def _coerce_ts(value):
    """Best-effort cast of pandas Timestamp / datetime to ISO string.
    Strings/None pass through unchanged."""
    if value is None or isinstance(value, str):
        return value
    iso = getattr(value, "isoformat", None)
    if callable(iso):
        try:
            return iso()
        except Exception:  # noqa: BLE001
            pass
    return str(value)


_MIGRATION_LOCK = threading.Lock()
_MIGRATED_DBS: set[str] = set()


def _db_key(conn: sqlite3.Connection) -> str:
    try:
        row = conn.execute("PRAGMA database_list").fetchone()
        if row is not None and len(row) >= 3 and row[2]:
            return str(row[2])
    except sqlite3.Error:
        pass
    return f"<connection:{id(conn)}>"


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Ensure live_trades/live_signals exist on an open connection."""
    key = _db_key(conn)
    if key in _MIGRATED_DBS:
        return
    with _MIGRATION_LOCK:
        if key in _MIGRATED_DBS:
            return
        from tools.maintenance.migrations import migration_002_live_trades
        migration_002_live_trades.apply(conn)
        _MIGRATED_DBS.add(key)


def _norm_trade(payload: dict) -> dict:
    """Map various JSONL/cockpit field names to canonical column names.

    Paper trades.jsonl tends to use 'entry'/'exit'/'pnl_usd'.
    Older variants used 'entry_price'/'exit_price'/'pnl'.
    Cockpit endpoint mirrors the JSONL shape.
    """
    p = dict(payload)
    # Aliases — if canonical missing, try alternatives. Order matters:
    # the first alias key present in the payload wins. Cockpit
    # /v1/runs/{id}/trades emits entry_at / exit_at / pnl_after_fees,
    # so those go first to win over JSONL-canonical names that may
    # also be present.
    aliases = {
        "ts": ("ts", "entry_at", "open_ts", "open_time", "timestamp"),
        "entry": ("entry", "entry_price"),
        "exit": ("exit", "exit_price"),
        "exit_ts": ("exit_ts", "exit_at", "close_ts", "exit_time", "closed_at"),
        # pnl_after_fees is the net pnl the user sees in the UI; prefer it
        # over the gross 'pnl' so backfilled rows match cockpit numbers.
        "pnl_usd": ("pnl_after_fees", "pnl_usd", "pnl"),
        "size_usd": ("notional", "size_usd", "size"),
        # Cockpit emits 'engine' (=sub-engine name); JSONL emits 'strategy'.
        "strategy": ("strategy", "engine"),
    }
    # Existing details_json (sync round-trip): pop early so it doesn't
    # leak into `extras` and get re-serialised into a {"details_json": ...}
    # double-wrap. Merge with novel extras at the end if both exist.
    existing_dj = p.pop("details_json", None)
    out: dict = {}
    consumed_aliases: set[str] = set()
    for canon, alts in aliases.items():
        for alt in alts:
            if alt in p and p[alt] is not None:
                out[canon] = p[alt]
                consumed_aliases.add(alt)
                break
    # Direct copy for fields without aliases.
    for col in _TRADE_COLS:
        if col not in out and col in p and p[col] is not None:
            out[col] = p[col]
    # Coerce timestamp-shaped fields to ISO strings (SQLite can't bind
    # pandas.Timestamp / datetime — see _coerce_ts module note).
    for f in _TS_FIELDS_TRADE:
        if f in out:
            out[f] = _coerce_ts(out[f])
    # Stash the rest for completeness.
    extras = {k: v for k, v in p.items()
              if k not in out and k not in consumed_aliases}
    out["details_json"] = _merge_details_json(existing_dj, extras)
    return out


def _merge_details_json(existing: str | dict | None, extras: dict) -> str | None:
    """Combine an existing details_json blob with novel extras.

    - Round-trip case (existing present, no extras): pass through unchanged.
    - Backfill case (no existing, extras present): serialise extras.
    - Mixed case: parse existing as dict, layer extras on top, re-serialise.
      Extras win on key collision (treats existing as base, novel as patch).
    - Pathological existing (non-JSON, non-dict): keep extras only,
      preserving existing as a sub-key under "_legacy_details" so nothing
      is silently dropped.
    """
    if existing is None and not extras:
        return None
    if existing is None:
        return json.dumps(extras)
    base: dict | None = None
    if isinstance(existing, dict):
        base = dict(existing)
    elif isinstance(existing, str):
        try:
            parsed = json.loads(existing)
            if isinstance(parsed, dict):
                base = parsed
        except (ValueError, TypeError):
            base = None
    if base is None:
        # Existing isn't a parseable dict — preserve verbatim.
        if not extras:
            return existing if isinstance(existing, str) else json.dumps(existing)
        merged = {"_legacy_details": existing, **extras}
        return json.dumps(merged)
    if not extras:
        return json.dumps(base)
    base.update(extras)
    return json.dumps(base)


def _norm_signal(payload: dict) -> dict:
    """Map shadow_trades.jsonl fields to live_signals columns.

    Shadow records use 'shadow_observed_at' for the canonical
    observed_at field, and 'timestamp' for the candle-time signal_ts.
    'direction' is BULLISH/BEARISH (renaissance vocab).
    """
    p = dict(payload)
    # Pop existing details_json early — same round-trip rationale as
    # _norm_trade. Without this, sync_vps_db would double-wrap shadow
    # signals on every mirror cycle.
    existing_dj = p.pop("details_json", None)
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
    # Coerce timestamp-shaped fields (see _coerce_ts module note).
    for f in _TS_FIELDS_SIGNAL:
        if f in out:
            out[f] = _coerce_ts(out[f])
    extras = {k: v for k, v in p.items()
              if k not in out
              and k not in ("shadow_observed_at", "timestamp",
                            "shadow_run_id")}
    out["details_json"] = _merge_details_json(existing_dj, extras)
    return out


# ─── Public API ─────────────────────────────────────────────────────


def upsert_trade(conn: sqlite3.Connection, run_id: str, payload: dict) -> bool:
    """Insert or update a live paper trade. Returns True if inserted."""
    ensure_schema(conn)
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
    ensure_schema(conn)
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
    ensure_schema(conn)
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
    ensure_schema(conn)
    cur = conn.execute(
        "SELECT * FROM live_signals WHERE run_id = ? "
        "ORDER BY observed_at DESC LIMIT ?",
        (run_id, limit),
    )
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]
