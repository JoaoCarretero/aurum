"""Unwrap double-encoded details_json in live_trades / live_signals.

Closes the regression where sync_vps_db's round-trip + db_live_trades
_norm_trade re-serialised an already-string details_json into a
{"details_json": "<original>"} singleton wrap. After the fix in
core/ops/db_live_trades, new rows land canonical — this script flattens
the legacy rows already in the DB.

Idempotent. Safe to run multiple times. Only unwraps EXACT singleton
wraps (`{"details_json": "<json string>"}` and nothing else); any other
shape is left alone, so legitimate `details_json` fields inside rich
objects survive.

Usage:
    python -m tools.maintenance.normalize_live_trades_details          # dry-run
    python -m tools.maintenance.normalize_live_trades_details --apply  # write
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

DB_PATH = Path("data/aurum.db")


def _try_unwrap(raw: str | None) -> str | None:
    """Return canonical inner JSON string if `raw` is the exact singleton
    wrap shape; None otherwise.
    """
    if not raw:
        return None
    try:
        outer = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(outer, dict):
        return None
    if list(outer.keys()) != ["details_json"]:
        return None
    inner = outer["details_json"]
    if not isinstance(inner, str):
        return None
    try:
        json.loads(inner)
    except (ValueError, TypeError):
        return None
    return inner


def _normalize_table(conn: sqlite3.Connection, table: str, key_cols: tuple,
                     *, dry_run: bool) -> int:
    """Walk one table, unwrap matching rows. Returns count touched (or
    counted, in dry_run)."""
    cur = conn.execute(
        f"SELECT id, details_json FROM {table} WHERE details_json IS NOT NULL"
    )
    n = 0
    updates: list[tuple[str, int]] = []
    for row_id, raw in cur.fetchall():
        canonical = _try_unwrap(raw)
        if canonical is None:
            continue
        n += 1
        if not dry_run:
            updates.append((canonical, row_id))
    if not dry_run and updates:
        conn.executemany(
            f"UPDATE {table} SET details_json = ? WHERE id = ?", updates,
        )
    return n


def normalize(conn: sqlite3.Connection, *, dry_run: bool = False) -> tuple[int, int]:
    """Return (trades_touched, signals_touched)."""
    n_t = _normalize_table(conn, "live_trades", ("run_id", "ts", "symbol"),
                            dry_run=dry_run)
    n_s = _normalize_table(conn, "live_signals", ("run_id", "observed_at", "symbol"),
                            dry_run=dry_run)
    return n_t, n_s


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="actually write (default is dry-run)")
    ap.add_argument("--db", type=str, default=str(DB_PATH),
                    help="path to aurum.db (default: %(default)s)")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    try:
        n_t, n_s = normalize(conn, dry_run=not args.apply)
        if args.apply:
            conn.commit()
            verb = "unwrapped"
        else:
            verb = "would unwrap"
        print(f"{verb} {n_t} live_trades + {n_s} live_signals "
              f"({'apply' if args.apply else 'dry-run'})")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
