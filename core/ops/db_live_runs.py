"""CRUD API for the live_runs table in aurum.db.

Lightweight wrapper around sqlite3. Designed for single-row UPSERT
hot paths in live runners (paper/shadow/live) and bulk read from the
LiveRunsScreen UI.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from config.paths import AURUM_DB_PATH

DB_PATH: Path = AURUM_DB_PATH

_UPSERT_IMMUTABLE: set[str] = {
    "run_id", "engine", "mode", "started_at", "run_dir", "host", "label",
}
_UPSERT_MUTABLE: set[str] = {
    "ended_at", "status", "tick_count", "novel_count", "open_count",
    "equity", "last_tick_at", "notes",
}
_REQUIRED_NEW: tuple[str, ...] = ("engine", "mode", "started_at", "run_dir")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def upsert(*, run_id: str, **fields: Any) -> None:
    """Insert-or-update single live_run row.

    First call must include engine, mode, started_at, run_dir. Later calls
    can pass any subset of mutable fields (tick_count, equity, etc).
    """
    if not run_id:
        raise ValueError("run_id required")
    unknown = set(fields) - (_UPSERT_IMMUTABLE | _UPSERT_MUTABLE) - {"run_id"}
    if unknown:
        raise ValueError(f"unknown field(s): {sorted(unknown)}")
    with _connect() as conn:
        existing = conn.execute(
            "SELECT 1 FROM live_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if existing is None:
            missing = [k for k in _REQUIRED_NEW if k not in fields]
            if missing:
                raise ValueError(
                    f"new row {run_id!r} missing required fields: {missing}"
                )
            cols = ["run_id"] + list(fields.keys())
            placeholders = ",".join(["?"] * len(cols))
            vals = [run_id] + [fields[k] for k in fields]
            conn.execute(
                f"INSERT INTO live_runs({','.join(cols)}) VALUES ({placeholders})",
                vals,
            )
        else:
            mutable = {k: v for k, v in fields.items() if k in _UPSERT_MUTABLE}
            if not mutable:
                return
            set_clause = ",".join(f"{k} = ?" for k in mutable)
            vals = list(mutable.values()) + [run_id]
            conn.execute(
                f"UPDATE live_runs SET {set_clause} WHERE run_id = ?", vals
            )


def list_live_runs(
    *,
    mode: str | None = None,
    engine: str | None = None,
    since: str | None = None,  # ISO 8601
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Query live_runs newest-first. All filters optional."""
    where: list[str] = []
    params: list[Any] = []
    if mode is not None:
        where.append("mode = ?")
        params.append(mode)
    if engine is not None:
        where.append("engine = ?")
        params.append(engine)
    if since is not None:
        where.append("started_at >= ?")
        params.append(since)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    sql = (
        f"SELECT * FROM live_runs {where_sql} "
        f"ORDER BY started_at DESC LIMIT ?"
    )
    params.append(limit)
    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def get_live_run(run_id: str) -> dict[str, Any] | None:
    """Single row fetch for detail panel."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM live_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
    return dict(row) if row else None
