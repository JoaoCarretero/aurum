"""CRUD API for the live_runs table in aurum.db.

Lightweight wrapper around sqlite3. Designed for single-row UPSERT
hot paths in live runners (paper/shadow/live) and bulk read from the
LiveRunsScreen UI.
"""
from __future__ import annotations

import sqlite3
import threading
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

_MIGRATION_LOCK = threading.Lock()
_MIGRATED_PATHS: set[str] = set()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Apply migration_001 once per process per DB path. Idempotent.

    Prevents "no such table: live_runs" crashes on a fresh aurum.db
    (e.g. new VPS install, CI tmpdir). Safe to call on every connect:
    schema DDL is `CREATE TABLE IF NOT EXISTS`, and the per-path set
    short-circuits after first apply.
    """
    db_key = str(DB_PATH)
    if db_key in _MIGRATED_PATHS:
        return
    with _MIGRATION_LOCK:
        if db_key in _MIGRATED_PATHS:
            return
        from tools.maintenance.migrations import migration_001_live_runs as _mig
        _mig.apply(conn)
        _MIGRATED_PATHS.add(db_key)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    _ensure_schema(conn)
    return conn


def upsert(*, run_id: str, **fields: Any) -> None:
    """Insert-or-update single live_run row.

    First call must include engine, mode, started_at, run_dir. Later calls
    can pass any subset of mutable fields (tick_count, equity, etc).
    """
    if not run_id:
        raise ValueError("run_id required")
    unknown = set(fields) - (_UPSERT_IMMUTABLE | _UPSERT_MUTABLE)
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
            immutable_passed = {
                k for k in fields if k in _UPSERT_IMMUTABLE
            }
            if immutable_passed:
                raise ValueError(
                    f"upsert({run_id!r}): cannot change immutable field(s) "
                    f"on existing row: {sorted(immutable_passed)}"
                )
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


def cleanup_stale_rows(stale_minutes: int = 30) -> int:
    """Marca como 'stopped' rows com status='running' sem heartbeat > N min.

    Mitiga bug do paper runner (nao marca status='stopped' ao SIGTERM);
    sem isso, restarts acumulam phantom rows que poluem o cockpit picker
    e fazem a UI mostrar "runs travadas" que nao existem mais.

    Safe pra services vivos: eles upsertam last_tick_at a cada tick
    (tick_sec=900=15min default); 30min = 2x margem antes de considerar
    orfao. Retorna count de rows afetadas. Tagga notes com
    'auto_cleanup_stale_YYYYMMDD_HHMM' pra facilitar debug posterior.
    """
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE live_runs "
            "SET status='stopped', ended_at=datetime('now'), "
            "    notes=COALESCE(notes,'') || "
            "         CASE WHEN COALESCE(notes,'')='' "
            "              THEN 'auto_cleanup_stale_' || strftime('%Y%m%d_%H%M','now') "
            "              ELSE '' END "
            "WHERE status='running' "
            "  AND datetime(last_tick_at) < datetime('now', ?)",
            (f"-{int(stale_minutes)} minutes",),
        )
        return cur.rowcount or 0
