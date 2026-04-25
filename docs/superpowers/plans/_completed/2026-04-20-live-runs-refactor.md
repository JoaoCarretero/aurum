# LIVE RUNS Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor ENGINE LOGS into a LIVE RUNS screen (histórico de runs
live/paper/shadow/demo/testnet) that mirrors BACKTESTS visually and reads
from a new `live_runs` table in `aurum.db` instead of scanning the filesystem
on every render.

**Architecture:** Three sequential phases. Phase 1 ships DB + cleanup
infra independently. Phase 2 builds the UI on top. Zero changes to CORE
PROTEGIDO (`core/indicators.py`, `core/signals.py`, `core/portfolio.py`,
`config/params.py`). Runners gain one cheap `upsert` call per tick.

**Tech Stack:** Python 3.14, SQLite (WAL), tkinter, pytest. Existing
`core/ops/db.py` module pattern (shim at `core/db.py` redirects
via sys.modules). Existing `launcher_support/screens/` + `ScreenManager`
infra.

**Spec:** `docs/superpowers/specs/2026-04-20-live-runs-refactor-design.md`.

---

## File structure

### Phase 1 — Infra

Created:
- `core/ops/db_live_runs.py` — upsert/list/get API targeting `live_runs` table
- `core/db_live_runs.py` — sys.modules shim (mirror of `core/db.py` pattern)
- `tools/maintenance/migrations/__init__.py`
- `tools/maintenance/migrations/migration_001_live_runs.py` — DDL migration
- `tools/maintenance/backfill_live_runs.py` — one-shot backfill script
- `tools/maintenance/cleanup_data_layout.py` — mv reversível, dry-run default
- `tests/core/test_db_live_runs.py`
- `tests/tools/test_migration_001.py`
- `tests/tools/test_backfill_live_runs.py`
- `tests/tools/test_cleanup_data_layout.py`

Modified:
- `tools/operations/millennium_paper.py` — upsert call after each `_write_heartbeat`
- `tools/maintenance/millennium_shadow.py` — upsert call after each `_write_heartbeat`

### Phase 2 — UI

Created:
- `launcher_support/screens/live_runs.py` — `LiveRunsScreen(Screen)`
- `tests/launcher/test_live_runs_screen.py`
- `tests/integration/test_launcher_live_runs.py`

Modified:
- `launcher_support/screens/registry.py` — register `"live_runs"`
- `launcher_support/screens/data_center.py` — add LIVE RUNS entry (key `L`),
  keep ENGINE LOGS entry but redirect to LIVE RUNS
- `launcher.py` — new `_data_live_runs()` method that flips to ScreenManager

---

## Task 1 — Migration: create `live_runs` table

**Files:**
- Create: `tools/maintenance/migrations/__init__.py`
- Create: `tools/maintenance/migrations/001_live_runs.py`
- Create: `tests/tools/test_migration_001.py`

- [ ] **Step 1.1 — Scaffold migrations package**

Create `tools/maintenance/migrations/__init__.py`:

```python
"""Schema migrations for aurum.db. Each migration is idempotent."""
```

- [ ] **Step 1.2 — Write failing test**

Create `tests/tools/test_migration_001.py`:

```python
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
```

- [ ] **Step 1.3 — Run test, confirm FAIL**

Run: `python -m pytest tests/tools/test_migration_001.py -v`
Expected: `ModuleNotFoundError: No module named 'tools.maintenance.migrations.migration_001_live_runs'`

- [ ] **Step 1.4 — Implement migration**

Create `tools/maintenance/migrations/migration_001_live_runs.py`:

```python
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
```

The file is named `migration_001_live_runs.py` (not `001_live_runs.py`)
because Python import machinery rejects module names starting with a
digit. The `__init__.py` from Step 1.1 stays as a simple package marker.

- [ ] **Step 1.5 — Run test, confirm PASS**

Run: `python -m pytest tests/tools/test_migration_001.py -v`
Expected: 4 passed.

- [ ] **Step 1.6 — Commit**

```bash
git add tools/maintenance/migrations/ tests/tools/test_migration_001.py
git commit -m "feat(db): migration 001 — live_runs table with mode check + indexes"
```

---

## Task 2 — `core/ops/db_live_runs.py` API (upsert/list/get)

**Files:**
- Create: `core/ops/db_live_runs.py`
- Create: `core/db_live_runs.py` (sys.modules shim)
- Create: `tests/core/test_db_live_runs.py`

- [ ] **Step 2.1 — Write failing test**

Create `tests/core/test_db_live_runs.py`:

```python
"""Tests for core.ops.db_live_runs upsert/list/get API."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from core.ops import db_live_runs as m
from tools.maintenance.migrations import migration_001_live_runs as mig


@pytest.fixture
def fake_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "a.db"
    conn = sqlite3.connect(db)
    mig.apply(conn)
    conn.close()
    monkeypatch.setattr(m, "DB_PATH", db)
    return db


def test_upsert_inserts_first_call(fake_db: Path) -> None:
    m.upsert(
        run_id="citadel_paper_2026-04-20_1200",
        engine="citadel",
        mode="paper",
        started_at="2026-04-20T12:00:00Z",
        run_dir="data/millennium_paper/2026-04-20_1200",
    )
    rows = m.list_live_runs()
    assert len(rows) == 1
    assert rows[0]["run_id"] == "citadel_paper_2026-04-20_1200"
    assert rows[0]["tick_count"] == 0


def test_upsert_updates_existing(fake_db: Path) -> None:
    m.upsert(
        run_id="r1", engine="citadel", mode="paper",
        started_at="2026-04-20T12:00:00Z", run_dir="d/r1",
    )
    m.upsert(run_id="r1", tick_count=42, novel_count=3, equity=10123.45)
    row = m.get_live_run("r1")
    assert row is not None
    assert row["tick_count"] == 42
    assert row["novel_count"] == 3
    assert row["equity"] == 10123.45
    # Immutable fields preserved
    assert row["engine"] == "citadel"
    assert row["mode"] == "paper"


def test_list_filters_by_mode(fake_db: Path) -> None:
    for run_id, mode in [("r1", "paper"), ("r2", "shadow"), ("r3", "paper")]:
        m.upsert(
            run_id=run_id, engine="citadel", mode=mode,
            started_at="2026-04-20T12:00:00Z", run_dir=f"d/{run_id}",
        )
    paper = m.list_live_runs(mode="paper")
    assert len(paper) == 2
    assert {r["run_id"] for r in paper} == {"r1", "r3"}


def test_list_filters_by_engine(fake_db: Path) -> None:
    m.upsert(run_id="r1", engine="citadel", mode="paper",
             started_at="2026-04-20T12:00:00Z", run_dir="d/r1")
    m.upsert(run_id="r2", engine="jump", mode="paper",
             started_at="2026-04-20T13:00:00Z", run_dir="d/r2")
    jump = m.list_live_runs(engine="jump")
    assert len(jump) == 1
    assert jump[0]["run_id"] == "r2"


def test_list_sorts_newest_first(fake_db: Path) -> None:
    m.upsert(run_id="old", engine="citadel", mode="paper",
             started_at="2026-04-19T00:00:00Z", run_dir="d/old")
    m.upsert(run_id="new", engine="citadel", mode="paper",
             started_at="2026-04-20T00:00:00Z", run_dir="d/new")
    rows = m.list_live_runs()
    assert [r["run_id"] for r in rows] == ["new", "old"]


def test_get_returns_none_if_missing(fake_db: Path) -> None:
    assert m.get_live_run("does_not_exist") is None


def test_upsert_rejects_new_row_without_required(fake_db: Path) -> None:
    # Can't upsert a fresh row missing engine/mode/started_at/run_dir.
    with pytest.raises(ValueError):
        m.upsert(run_id="incomplete", tick_count=1)
```

- [ ] **Step 2.2 — Run test, confirm FAIL**

Run: `python -m pytest tests/core/test_db_live_runs.py -v`
Expected: `ModuleNotFoundError: No module named 'core.ops.db_live_runs'`

- [ ] **Step 2.3 — Implement API**

Create `core/ops/db_live_runs.py`:

```python
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
```

Create shim `core/db_live_runs.py`:

```python
"""Compatibility shim — redirects core.db_live_runs to core.ops.db_live_runs.
Mirrors the pattern in core/db.py so monkey-patching works in tests.
"""
import sys
from core.ops import db_live_runs as _impl
sys.modules[__name__] = _impl
```

- [ ] **Step 2.4 — Run test, confirm PASS**

Run: `python -m pytest tests/core/test_db_live_runs.py -v`
Expected: 7 passed.

- [ ] **Step 2.5 — Commit**

```bash
git add core/ops/db_live_runs.py core/db_live_runs.py tests/core/test_db_live_runs.py
git commit -m "feat(db): core.ops.db_live_runs — upsert/list/get API for live runs"
```

---

## Task 3 — Backfill script: populate `live_runs` from existing dirs

**Files:**
- Create: `tools/maintenance/backfill_live_runs.py`
- Create: `tests/tools/test_backfill_live_runs.py`

- [ ] **Step 3.1 — Write failing test**

Create `tests/tools/test_backfill_live_runs.py`:

```python
"""Tests for backfill_live_runs script."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.ops import db_live_runs
from tools.maintenance import backfill_live_runs as bf
from tools.maintenance.migrations import migration_001_live_runs as mig


@pytest.fixture
def fake_data_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    db = tmp_path / "a.db"
    conn = sqlite3.connect(db)
    mig.apply(conn)
    conn.close()
    monkeypatch.setattr(db_live_runs, "DB_PATH", db)
    monkeypatch.setattr(bf, "DATA_ROOT", tmp_path)
    return tmp_path


def _make_run(root: Path, parent: str, ts: str, heartbeat: dict | None) -> Path:
    run_dir = root / parent / ts
    run_dir.mkdir(parents=True)
    state = run_dir / "state"
    state.mkdir()
    if heartbeat is not None:
        (state / "heartbeat.json").write_text(json.dumps(heartbeat))
    return run_dir


def test_backfill_paper_run_with_heartbeat(fake_data_root: Path) -> None:
    _make_run(
        fake_data_root, "millennium_paper", "2026-04-20_1200",
        heartbeat={
            "run_id": "paper_2026-04-20_1200",
            "started_at": "2026-04-20T12:00:00+00:00",
            "last_tick_at": "2026-04-20T12:05:00+00:00",
            "ticks_ok": 20, "novel_total": 3,
            "equity": 10123.45, "status": "running", "mode": "paper",
        },
    )
    n = bf.run(dry_run=False)
    assert n == 1
    rows = db_live_runs.list_live_runs()
    assert len(rows) == 1
    r = rows[0]
    assert r["engine"] == "millennium"
    assert r["mode"] == "paper"
    assert r["tick_count"] == 20
    assert r["novel_count"] == 3
    assert r["equity"] == 10123.45


def test_backfill_dir_without_heartbeat_marked_stopped(
    fake_data_root: Path,
) -> None:
    _make_run(
        fake_data_root, "millennium_shadow", "2026-04-18_0900",
        heartbeat=None,
    )
    n = bf.run(dry_run=False)
    assert n == 1
    rows = db_live_runs.list_live_runs()
    assert rows[0]["status"] == "stopped"
    assert rows[0]["mode"] == "shadow"


def test_backfill_dry_run_does_not_write(fake_data_root: Path) -> None:
    _make_run(
        fake_data_root, "millennium_paper", "2026-04-20_1200",
        heartbeat={
            "started_at": "2026-04-20T12:00:00+00:00",
            "last_tick_at": "2026-04-20T12:00:05+00:00",
            "ticks_ok": 1, "novel_total": 0, "equity": 10000.0,
            "status": "running", "mode": "paper",
        },
    )
    n = bf.run(dry_run=True)
    assert n == 1
    assert db_live_runs.list_live_runs() == []


def test_backfill_idempotent(fake_data_root: Path) -> None:
    _make_run(
        fake_data_root, "millennium_paper", "2026-04-20_1200",
        heartbeat={
            "started_at": "2026-04-20T12:00:00+00:00",
            "last_tick_at": "2026-04-20T12:00:05+00:00",
            "ticks_ok": 1, "novel_total": 0, "equity": 10000.0,
            "status": "running", "mode": "paper",
        },
    )
    bf.run(dry_run=False)
    bf.run(dry_run=False)
    rows = db_live_runs.list_live_runs()
    assert len(rows) == 1
```

- [ ] **Step 3.2 — Run test, confirm FAIL**

Run: `python -m pytest tests/tools/test_backfill_live_runs.py -v`
Expected: `ModuleNotFoundError: No module named 'tools.maintenance.backfill_live_runs'`

- [ ] **Step 3.3 — Implement backfill**

Create `tools/maintenance/backfill_live_runs.py`:

```python
"""Backfill the aurum.db live_runs table from existing run dirs.

Scans data/millennium_{live,paper,shadow}/ and data/live/ and inserts
one row per dir into live_runs. Reads heartbeat.json if present for
accurate status/metrics; otherwise marks as stopped with zero counters.

Idempotent via INSERT OR REPLACE — safe to re-run.
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path
from typing import Any

from config.paths import DATA_DIR
from core.ops import db_live_runs

DATA_ROOT: Path = DATA_DIR

_PARENT_TO_MODE = {
    "millennium_live": "live",
    "millennium_paper": "paper",
    "millennium_shadow": "shadow",
    "live": "live",
}


def _parent_to_engine_mode(parent_name: str) -> tuple[str, str]:
    """Map parent dir name to (engine, mode).

    millennium_{paper,shadow,live} -> engine=millennium, mode=<suffix>
    live/                          -> engine=unknown,    mode=live
    """
    if parent_name.startswith("millennium_"):
        return "millennium", parent_name.split("_", 1)[1]
    if parent_name == "live":
        return "unknown", "live"
    return "unknown", "unknown"


def _parse_dir(run_dir: Path) -> dict[str, Any] | None:
    parent = run_dir.parent.name
    if parent not in _PARENT_TO_MODE:
        return None
    engine, mode = _parent_to_engine_mode(parent)
    heartbeat_path = run_dir / "state" / "heartbeat.json"
    hb: dict[str, Any] = {}
    if heartbeat_path.exists():
        try:
            hb = json.loads(heartbeat_path.read_text())
        except (json.JSONDecodeError, OSError):
            hb = {}
    # run_id: prefer heartbeat's, else fallback to <parent>_<dirname>.
    run_id = hb.get("run_id") or f"{parent}_{run_dir.name}"
    started_at = hb.get("started_at") or f"{run_dir.name}T00:00:00+00:00"
    last_tick_at = hb.get("last_tick_at")
    status = hb.get("status") or ("stopped" if not hb else "unknown")
    if hb and not last_tick_at:
        status = "stopped"
    return {
        "run_id": run_id,
        "engine": engine,
        "mode": mode,
        "started_at": started_at,
        "status": status,
        "tick_count": int(hb.get("ticks_ok") or 0),
        "novel_count": int(hb.get("novel_total") or 0),
        "open_count": int(hb.get("open_count") or 0),
        "equity": hb.get("equity"),
        "last_tick_at": last_tick_at,
        "host": hb.get("host") or socket.gethostname(),
        "label": hb.get("label"),
        "run_dir": str(run_dir.relative_to(DATA_ROOT.parent)),
    }


def _iter_run_dirs() -> list[Path]:
    dirs: list[Path] = []
    for parent_name in _PARENT_TO_MODE:
        parent = DATA_ROOT / parent_name
        if not parent.exists():
            continue
        dirs.extend(d for d in parent.iterdir() if d.is_dir())
    return dirs


def run(*, dry_run: bool) -> int:
    """Returns number of dirs processed."""
    n = 0
    for run_dir in _iter_run_dirs():
        parsed = _parse_dir(run_dir)
        if parsed is None:
            continue
        n += 1
        if dry_run:
            continue
        db_live_runs.upsert(**parsed)
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="Actually write to DB. Default is dry-run.")
    args = ap.parse_args(argv)
    n = run(dry_run=not args.apply)
    verb = "would backfill" if not args.apply else "backfilled"
    print(f"{verb} {n} run dirs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3.4 — Run test, confirm PASS**

Run: `python -m pytest tests/tools/test_backfill_live_runs.py -v`
Expected: 4 passed.

- [ ] **Step 3.5 — Commit**

```bash
git add tools/maintenance/backfill_live_runs.py tests/tools/test_backfill_live_runs.py
git commit -m "feat(db): backfill live_runs table from existing millennium_{live,paper,shadow} dirs"
```

---

## Task 4 — Runtime hook: `millennium_paper` upserts on each tick

**Files:**
- Modify: `tools/operations/millennium_paper.py`

- [ ] **Step 4.1 — Write failing test**

Append to `tests/integration/test_paper_runner_tick.py` (or create
`tests/integration/test_paper_runner_db_hook.py` if cleaner):

```python
"""Verify millennium_paper upserts a live_runs row per tick."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from core.ops import db_live_runs
from tools.maintenance.migrations import migration_001_live_runs as mig


def test_paper_upsert_hook_exists() -> None:
    """Import the paper runner and confirm _upsert_live_run is called
    from the heartbeat path."""
    import tools.operations.millennium_paper as paper
    source = Path(paper.__file__).read_text()
    # Hook lives next to _write_heartbeat calls.
    assert "db_live_runs.upsert" in source, \
        "millennium_paper must call db_live_runs.upsert per tick"
```

This is a smoke-level structural test — the real integration test runs
via the existing `test_paper_runner_tick.py` path which already spawns a
fake tick.

- [ ] **Step 4.2 — Run test, confirm FAIL**

Run: `python -m pytest tests/integration/test_paper_runner_db_hook.py -v`
Expected: FAIL, "millennium_paper must call db_live_runs.upsert per tick".

- [ ] **Step 4.3 — Add hook to `millennium_paper.py`**

Find the tick heartbeat block (around line 574, inside the tick loop,
right after `_write_heartbeat({...})`):

```python
    _write_heartbeat({
        "run_id": RUN_ID, "status": "running",
        ...
        "ks_state": state.ks.state.value,
    })
```

Immediately after the closing `})`, add:

```python
    try:
        db_live_runs.upsert(
            run_id=RUN_ID,
            engine="millennium",
            mode="paper",
            started_at=RUN_TS.isoformat(),
            run_dir=str(RUN_DIR.relative_to(ROOT)),
            host=socket.gethostname(),
            label=LABEL,
            status="running",
            tick_count=state.ticks_ok,
            novel_count=state.novel_total,
            open_count=len(state.open_positions),
            equity=round(state.account.equity, 2),
            last_tick_at=now_iso,
        )
    except Exception:
        # DB hook must never crash the runner — log and move on.
        log.exception("db_live_runs upsert failed (tick continues)")
```

At the top of the file, add import alongside existing imports:

```python
import socket

from core.ops import db_live_runs
```

At the final shutdown block (find `_write_run_summary` call in the
stop handler, around line 594-614), add after the summary write:

```python
    try:
        db_live_runs.upsert(
            run_id=RUN_ID,
            ended_at=datetime.now(timezone.utc).isoformat(),
            status="stopped",
        )
    except Exception:
        log.exception("db_live_runs final upsert failed")
```

- [ ] **Step 4.4 — Run test, confirm PASS**

Run: `python -m pytest tests/integration/test_paper_runner_db_hook.py -v`
Expected: PASS.

Run existing tick integration: `python -m pytest tests/integration/test_paper_runner_tick.py -v`
Expected: existing tests still pass (the hook is wrapped in try/except).

- [ ] **Step 4.5 — Commit**

```bash
git add tools/operations/millennium_paper.py tests/integration/test_paper_runner_db_hook.py
git commit -m "feat(paper): upsert live_runs row per tick + on stop"
```

---

## Task 5 — Runtime hook: `millennium_shadow` upserts on each tick

**Files:**
- Modify: `tools/maintenance/millennium_shadow.py`

- [ ] **Step 5.1 — Write failing test**

Create `tests/tools/test_shadow_runner_db_hook.py`:

```python
"""Verify millennium_shadow upserts a live_runs row per tick."""
from pathlib import Path


def test_shadow_upsert_hook_exists() -> None:
    import tools.maintenance.millennium_shadow as shadow
    source = Path(shadow.__file__).read_text()
    assert "db_live_runs.upsert" in source, \
        "millennium_shadow must call db_live_runs.upsert per tick"
```

- [ ] **Step 5.2 — Run test, confirm FAIL**

Run: `python -m pytest tests/tools/test_shadow_runner_db_hook.py -v`
Expected: FAIL.

- [ ] **Step 5.3 — Add hook**

In `tools/maintenance/millennium_shadow.py`, locate each
`_write_heartbeat({...})` call (lines 477, 523, 549, 577). After EACH
one, add the same upsert block adapted:

```python
    try:
        db_live_runs.upsert(
            run_id=RUN_ID,
            engine="millennium",
            mode="shadow",
            started_at=RUN_TS.isoformat(),
            run_dir=str(RUN_DIR.relative_to(ROOT)),
            host=socket.gethostname(),
            label=LABEL,
            status="running",
            tick_count=ticks_ok,
            novel_count=novel_total,
            last_tick_at=now_iso,
        )
    except Exception:
        log.exception("db_live_runs upsert failed (tick continues)")
```

The variable names (`ticks_ok`, `novel_total`, `now_iso`) match what
shadow's heartbeat dict already passes. If shadow uses different names,
map accordingly. Also add imports at top of file:

```python
import socket

from core.ops import db_live_runs
```

At the final shutdown (find `_write_run_summary` call, typically near
the end of `run_shadow()`), add:

```python
    try:
        db_live_runs.upsert(
            run_id=RUN_ID,
            ended_at=datetime.now(timezone.utc).isoformat(),
            status="stopped",
        )
    except Exception:
        log.exception("db_live_runs final upsert failed")
```

- [ ] **Step 5.4 — Run test, confirm PASS**

Run: `python -m pytest tests/tools/test_shadow_runner_db_hook.py -v`
Expected: PASS.

Run full shadow helpers suite: `python -m pytest tests/tools/test_millennium_shadow_helpers.py -v`
Expected: no regressions.

- [ ] **Step 5.5 — Commit**

```bash
git add tools/maintenance/millennium_shadow.py tests/tools/test_shadow_runner_db_hook.py
git commit -m "feat(shadow): upsert live_runs row per tick + on stop"
```

---

## Task 6 — Cleanup script: `cleanup_data_layout.py`

**Files:**
- Create: `tools/maintenance/cleanup_data_layout.py`
- Create: `tests/tools/test_cleanup_data_layout.py`

- [ ] **Step 6.1 — Write failing test**

Create `tests/tools/test_cleanup_data_layout.py`:

```python
"""Tests for cleanup_data_layout script.

Covers: dry-run default, --apply executes mv, idempotent re-run,
preserves dirs listed in data/index.json.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.maintenance import cleanup_data_layout as cd


@pytest.fixture
def fake_data_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    (tmp_path / "_bridgewater_compare" / "r1").mkdir(parents=True)
    (tmp_path / "anti_overfit" / "run").mkdir(parents=True)
    (tmp_path / "audit" / "a1").mkdir(parents=True)
    (tmp_path / "nexus.db").write_text("vazio")
    (tmp_path / "runs" / "citadel_2026-04-18_153116").mkdir(parents=True)
    (tmp_path / "citadel").mkdir()
    (tmp_path / "index.json").write_text(json.dumps([
        {"run_id": "citadel_123", "engine": "citadel"},
    ]))
    monkeypatch.setattr(cd, "DATA_ROOT", tmp_path)
    return tmp_path


def test_dry_run_moves_nothing(fake_data_root: Path) -> None:
    moves = cd.plan_moves()
    assert len(moves) > 0
    cd.run(dry_run=True)
    assert (fake_data_root / "_bridgewater_compare").exists()
    assert (fake_data_root / "nexus.db").exists()
    assert (fake_data_root / "runs" / "citadel_2026-04-18_153116").exists()


def test_apply_moves_research_dirs(fake_data_root: Path) -> None:
    cd.run(dry_run=False)
    assert not (fake_data_root / "_bridgewater_compare").exists()
    arch = fake_data_root / "_archive" / "research" / "_bridgewater_compare"
    assert arch.exists()


def test_apply_archives_nexus_db(fake_data_root: Path) -> None:
    cd.run(dry_run=False)
    assert not (fake_data_root / "nexus.db").exists()
    arch = fake_data_root / "_archive" / "db"
    snaps = list(arch.iterdir())
    assert len(snaps) == 1
    assert snaps[0].name.startswith("nexus.db.")


def test_apply_consolidates_legacy_runs_dir(fake_data_root: Path) -> None:
    cd.run(dry_run=False)
    # Moved to data/citadel/<timestamp-suffix>
    citadel = fake_data_root / "citadel"
    assert citadel.exists()
    moved = [p for p in citadel.iterdir() if p.is_dir()]
    assert any("2026-04-18_153116" in p.name for p in moved)


def test_apply_is_idempotent(fake_data_root: Path) -> None:
    cd.run(dry_run=False)
    cd.run(dry_run=False)  # second call is a no-op


def test_preserves_dirs_in_index_json(fake_data_root: Path) -> None:
    (fake_data_root / "audit" / "run_citadel_123").mkdir()
    # audit/ dir has a subdir named after an indexed run_id — still moves
    # (audit is infra, not a backtest). But the rule is: never touch a
    # *top-level* dir listed as an engine in index.json.
    cd.run(dry_run=False)
    # engine dir `citadel` survives
    assert (fake_data_root / "citadel").exists()
```

- [ ] **Step 6.2 — Run test, confirm FAIL**

Run: `python -m pytest tests/tools/test_cleanup_data_layout.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 6.3 — Implement cleanup**

Create `tools/maintenance/cleanup_data_layout.py`:

```python
"""Reversible cleanup of data/ layout.

Moves (never deletes):
- research dirs (_bridgewater_*, anti_overfit, audit, param_search,
  perf_profile, validation) -> data/_archive/research/
- legacy data/runs/<engine>_<timestamp>/ -> data/<engine>/<timestamp>/
- data/nexus.db -> data/_archive/db/nexus.db.<timestamp>

Dry-run by default. Pass --apply to execute.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from config.paths import DATA_DIR

DATA_ROOT: Path = DATA_DIR

_RESEARCH_DIRS: tuple[str, ...] = (
    "_bridgewater_compare",
    "_bridgewater_regime_filter",
    "_bridgewater_rolling_compare",
    "anti_overfit",
    "audit",
    "param_search",
    "perf_profile",
    "validation",
)

_ENGINES_PRESERVED: tuple[str, ...] = (
    "citadel", "bridgewater", "jump", "deshaw", "renaissance",
    "millennium", "twosigma", "aqr", "janestreet", "kepos", "medallion",
    "graham", "meanrev", "ornstein", "ornstein_v2", "phi",
    "millennium_live", "millennium_paper", "millennium_shadow", "live",
)


def plan_moves() -> list[tuple[Path, Path]]:
    """Compute list of (src, dst) pairs without touching disk."""
    moves: list[tuple[Path, Path]] = []
    # Research dirs
    for name in _RESEARCH_DIRS:
        src = DATA_ROOT / name
        if src.exists() and src.is_dir():
            dst = DATA_ROOT / "_archive" / "research" / name
            moves.append((src, dst))
    # Legacy runs/ dir: split per engine
    legacy_runs = DATA_ROOT / "runs"
    if legacy_runs.exists() and legacy_runs.is_dir():
        for sub in legacy_runs.iterdir():
            if not sub.is_dir():
                continue
            engine = sub.name.split("_", 1)[0]
            if engine in _ENGINES_PRESERVED:
                dst = DATA_ROOT / engine / sub.name
                moves.append((sub, dst))
    # nexus.db -> archive with timestamp
    nexus = DATA_ROOT / "nexus.db"
    if nexus.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
        dst = DATA_ROOT / "_archive" / "db" / f"nexus.db.{stamp}"
        moves.append((nexus, dst))
    for extra in ("nexus.db-shm", "nexus.db-wal"):
        p = DATA_ROOT / extra
        if p.exists():
            dst = DATA_ROOT / "_archive" / "db" / p.name
            moves.append((p, dst))
    return moves


def run(*, dry_run: bool) -> int:
    moves = plan_moves()
    if not moves:
        print("nothing to clean up.")
        return 0
    for src, dst in moves:
        rel_src = src.relative_to(DATA_ROOT)
        rel_dst = dst.relative_to(DATA_ROOT)
        if dry_run:
            print(f"[dry] mv data/{rel_src} data/{rel_dst}")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            print(f"[skip] data/{rel_dst} already exists")
            continue
        shutil.move(str(src), str(dst))
        print(f"[moved] data/{rel_src} -> data/{rel_dst}")
        print(f"[undo]  mv data/{rel_dst} data/{rel_src}")
    return len(moves)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="Execute moves. Default is dry-run.")
    args = ap.parse_args(argv)
    n = run(dry_run=not args.apply)
    print(f"\n{'planned' if not args.apply else 'executed'} {n} moves")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6.4 — Run test, confirm PASS**

Run: `python -m pytest tests/tools/test_cleanup_data_layout.py -v`
Expected: 6 passed.

- [ ] **Step 6.5 — Commit**

```bash
git add tools/maintenance/cleanup_data_layout.py tests/tools/test_cleanup_data_layout.py
git commit -m "feat(maintenance): reversible cleanup — research dirs + legacy runs/ + nexus.db"
```

---

## Task 7 — Execution gate: run migration + cleanup + backfill

**No code.** This task actually exercises the scripts on the real data/.
MUST be run by the operator manually — not automated — so that the
output can be inspected before committing.

- [ ] **Step 7.1 — Apply migration to real aurum.db**

Run (creates a Python one-shot — no separate script needed):

```bash
python -c "
import sqlite3
from config.paths import AURUM_DB_PATH
from tools.maintenance.migrations import migration_001_live_runs as m
conn = sqlite3.connect(AURUM_DB_PATH)
m.apply(conn)
conn.close()
print('migration 001 applied')
"
```

Expected output: `migration 001 applied`

Verify:
```bash
python -c "
import sqlite3
from config.paths import AURUM_DB_PATH
conn = sqlite3.connect(AURUM_DB_PATH)
cols = [r[1] for r in conn.execute('PRAGMA table_info(live_runs)').fetchall()]
print(f'live_runs columns: {cols}')
"
```

Expected: 15 columns including `run_id`, `engine`, `mode`, `tick_count`.

- [ ] **Step 7.2 — Dry-run cleanup**

```bash
python tools/maintenance/cleanup_data_layout.py
```

Expected: list of `[dry] mv` lines. Inspect each. If any looks wrong,
STOP and fix the script before applying.

- [ ] **Step 7.3 — Apply cleanup**

```bash
python tools/maintenance/cleanup_data_layout.py --apply
```

Expected output: one `[moved]` line per operation plus `[undo]` command
for each.

Verify `data/_bridgewater_*` gone, `data/_archive/research/` populated,
`data/nexus.db` gone, `data/_archive/db/nexus.db.<ts>` present.

- [ ] **Step 7.4 — Backfill from disk**

```bash
python tools/maintenance/backfill_live_runs.py
```

Expected: `would backfill N run dirs` where N ≈ 396 (48 live + 43
paper + 57 shadow + 248 live/, approximately).

If dry-run count looks right:

```bash
python tools/maintenance/backfill_live_runs.py --apply
```

Expected: `backfilled N run dirs`.

Verify in DB:

```bash
python -c "
from core.ops import db_live_runs as m
for mode in ('live', 'paper', 'shadow'):
    rows = m.list_live_runs(mode=mode)
    print(f'{mode}: {len(rows)} runs, newest {rows[0][\"run_id\"] if rows else None!r}')
"
```

Expected: each mode reports counts, newest run_id looks valid.

- [ ] **Step 7.5 — Commit**

The cleanup is already on disk — no code changed, but `aurum.db` did.
Record the migration in the repo with a marker file (git-ignores data/):

```bash
git add docs/migrations/applied/
# ^ create docs/migrations/applied/001_live_runs.md with date + output
```

```bash
cat > docs/migrations/applied/001_live_runs.md << 'EOF'
# Migration 001 applied

- date: <YYYY-MM-DD HHMM>
- cleanup: N moves
- backfill: N rows
- verified: live/paper/shadow row counts match disk
EOF
```

```bash
git add docs/migrations/applied/001_live_runs.md
git commit -m "ops: apply migration 001 + cleanup + backfill"
```

---

## Task 8 — LiveRunsScreen skeleton + filter bar

**Files:**
- Create: `launcher_support/screens/live_runs.py`
- Create: `tests/launcher/test_live_runs_screen.py`

- [ ] **Step 8.1 — Write failing test**

Create `tests/launcher/test_live_runs_screen.py`:

```python
"""Unit tests for LiveRunsScreen."""
from __future__ import annotations

import tkinter as tk
from unittest.mock import MagicMock

import pytest

from launcher_support.screens.live_runs import LiveRunsScreen


@pytest.fixture(scope="module")
def gui_root():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("tk unavailable")
    root.withdraw()
    yield root
    try:
        root.destroy()
    except Exception:
        pass


@pytest.fixture
def fake_app():
    app = MagicMock()
    return app


@pytest.fixture
def fake_runs():
    return [
        {"run_id": "r1", "engine": "millennium", "mode": "paper",
         "started_at": "2026-04-20T12:00:00+00:00",
         "ended_at": None, "status": "running",
         "tick_count": 20, "novel_count": 3, "open_count": 0,
         "equity": 10123.45, "last_tick_at": "2026-04-20T12:05:00+00:00",
         "host": "localhost", "label": None,
         "run_dir": "data/millennium_paper/2026-04-20_1200", "notes": None},
        {"run_id": "r2", "engine": "millennium", "mode": "shadow",
         "started_at": "2026-04-19T00:00:00+00:00",
         "ended_at": None, "status": "running",
         "tick_count": 106, "novel_count": 664, "open_count": 0,
         "equity": 10000.0, "last_tick_at": "2026-04-20T21:45:00+00:00",
         "host": "vps", "label": None,
         "run_dir": "data/millennium_shadow/2026-04-19_0000", "notes": None},
    ]


@pytest.mark.gui
def test_screen_builds(gui_root, fake_app, fake_runs, monkeypatch):
    monkeypatch.setattr(
        "launcher_support.screens.live_runs.db_live_runs.list_live_runs",
        lambda **kw: fake_runs,
    )
    s = LiveRunsScreen(parent=gui_root, app=fake_app)
    s.mount()
    assert s._list_frame is not None
    assert s._detail_frame is not None


@pytest.mark.gui
def test_on_enter_renders_all_mode_by_default(
    gui_root, fake_app, fake_runs, monkeypatch,
):
    calls = []
    def fake_list(**kw):
        calls.append(kw)
        return fake_runs
    monkeypatch.setattr(
        "launcher_support.screens.live_runs.db_live_runs.list_live_runs",
        fake_list,
    )
    s = LiveRunsScreen(parent=gui_root, app=fake_app)
    s.mount()
    s.on_enter()
    assert calls[0].get("mode") is None  # ALL default


@pytest.mark.gui
def test_set_filter_rerenders_with_mode(
    gui_root, fake_app, fake_runs, monkeypatch,
):
    calls = []
    def fake_list(**kw):
        calls.append(kw)
        return fake_runs
    monkeypatch.setattr(
        "launcher_support.screens.live_runs.db_live_runs.list_live_runs",
        fake_list,
    )
    s = LiveRunsScreen(parent=gui_root, app=fake_app)
    s.mount()
    s.on_enter()
    s.set_filter("paper")
    assert calls[-1].get("mode") == "paper"


@pytest.mark.gui
def test_ttl_cache_avoids_repeat_query(
    gui_root, fake_app, fake_runs, monkeypatch,
):
    calls = []
    def fake_list(**kw):
        calls.append(kw)
        return fake_runs
    monkeypatch.setattr(
        "launcher_support.screens.live_runs.db_live_runs.list_live_runs",
        fake_list,
    )
    s = LiveRunsScreen(parent=gui_root, app=fake_app)
    s.mount()
    s.on_enter()
    s.on_enter()  # within TTL
    s.on_enter()
    assert len(calls) == 1
```

- [ ] **Step 8.2 — Run test, confirm FAIL**

Run: `python -m pytest tests/launcher/test_live_runs_screen.py -v`
Expected: `ModuleNotFoundError: No module named 'launcher_support.screens.live_runs'`

- [ ] **Step 8.3 — Implement skeleton**

Create `launcher_support/screens/live_runs.py`:

```python
"""LiveRunsScreen — histórico de runs live/paper/shadow/demo/testnet.

Espelha BACKTESTS visualmente: left scrollable list + right detail panel.
Reads from aurum.db live_runs table — not the filesystem.
"""
from __future__ import annotations

import time
import tkinter as tk
from typing import Any

from core.ui.ui_palette import AMBER, AMBER_D, BG, BG2, BG3, BORDER, DIM, DIM2, FONT, PANEL, WHITE
from launcher_support.screens.base import Screen
from core import db_live_runs


_LIST_COLS: list[tuple[str, int]] = [
    ("STATE", 7), ("ENGINE", 11), ("MODE", 7), ("STARTED", 16),
    ("TICKS", 6), ("SIG", 5), ("EQUITY", 10),
]


class LiveRunsScreen(Screen):
    _TTL_SEC = 3.0
    _MODES = ("all", "live", "paper", "shadow", "demo", "testnet")

    def __init__(self, parent: tk.Misc, app: Any):
        super().__init__(parent)
        self.app = app
        self._mode_filter: str = "all"
        self._list_cache: tuple[float, str, list[dict]] | None = None
        self._selected_run_id: str | None = None
        self._list_frame: tk.Frame | None = None
        self._detail_frame: tk.Frame | None = None
        self._filter_tabs: dict[str, tk.Label] = {}

    def build(self) -> None:
        outer = tk.Frame(self.container, bg=BG)
        outer.pack(fill="both", expand=True, padx=20, pady=14)

        head = tk.Frame(outer, bg=BG); head.pack(fill="x")
        tk.Label(
            head, text="LIVE RUNS", font=(FONT, 14, "bold"),
            fg=AMBER, bg=BG, anchor="w",
        ).pack(anchor="w")
        tk.Label(
            head, text="Historico live / paper / shadow / demo / testnet",
            font=(FONT, 8), fg=DIM, bg=BG, anchor="w",
        ).pack(anchor="w", pady=(3, 8))
        tk.Frame(outer, bg=DIM2, height=1).pack(fill="x", pady=(0, 8))

        # Filter bar
        fbar = tk.Frame(outer, bg=BG); fbar.pack(fill="x", pady=(0, 8))
        tk.Label(
            fbar, text="FILTER", font=(FONT, 7, "bold"),
            fg=DIM, bg=BG,
        ).pack(side="left", padx=(0, 10))
        for idx, mode in enumerate(self._MODES, start=1):
            tab = tk.Label(
                fbar, text=f" {idx}:{mode.upper()} ",
                font=(FONT, 7, "bold"),
                fg=AMBER_D if mode == self._mode_filter else DIM,
                bg=BG3 if mode == self._mode_filter else BG,
                cursor="hand2", padx=6, pady=2,
            )
            tab.pack(side="left", padx=(0, 4))
            tab.bind("<Button-1>",
                     lambda _e, m=mode: self.set_filter(m))
            self._filter_tabs[mode] = tab

        # Split: list | detail
        split = tk.Frame(outer, bg=BG)
        split.pack(fill="both", expand=True)
        split.grid_columnconfigure(0, weight=3, uniform="lr_split")
        split.grid_columnconfigure(1, weight=2, uniform="lr_split")
        split.grid_rowconfigure(0, weight=1)

        left = tk.Frame(
            split, bg=BG, highlightbackground=BORDER, highlightthickness=1,
        )
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        hrow = tk.Frame(left, bg=BG); hrow.pack(fill="x")
        for label, width in _LIST_COLS:
            tk.Label(hrow, text=label, font=(FONT, 7, "bold"),
                     fg=DIM, bg=BG, width=width, anchor="w").pack(side="left")
        tk.Frame(left, bg=DIM2, height=1).pack(fill="x", pady=(1, 2))

        self._list_frame = tk.Frame(left, bg=BG)
        self._list_frame.pack(fill="both", expand=True)

        right = tk.Frame(
            split, bg=PANEL, highlightbackground=BORDER, highlightthickness=1,
        )
        right.grid(row=0, column=1, sticky="nsew")
        tk.Label(right, text="DETAILS", font=(FONT, 7, "bold"),
                 fg=AMBER_D, bg=PANEL, anchor="w").pack(
            anchor="nw", padx=10, pady=(10, 4),
        )
        tk.Frame(right, bg=DIM2, height=1).pack(fill="x", padx=10, pady=(0, 6))
        self._detail_frame = tk.Frame(right, bg=PANEL)
        self._detail_frame.pack(fill="both", expand=True, padx=10, pady=(2, 10))

    def on_enter(self, **kwargs: Any) -> None:
        del kwargs
        app = self.app
        if hasattr(app, "h_path"):
            app.h_path.configure(text="> DATA > LIVE RUNS")
        if hasattr(app, "h_stat"):
            app.h_stat.configure(text="BROWSE", fg=AMBER_D)
        if hasattr(app, "f_lbl"):
            app.f_lbl.configure(
                text="ESC voltar  |  1-6 filter  |  click row for details",
            )
        if hasattr(app, "_kb"):
            app._kb("<Escape>", lambda: app._data_center())
            for idx, mode in enumerate(self._MODES, start=1):
                app._kb(f"<Key-{idx}>",
                        lambda m=mode: self.set_filter(m))
        self._render()

    def set_filter(self, mode: str) -> None:
        if mode not in self._MODES:
            return
        self._mode_filter = mode
        for m, tab in self._filter_tabs.items():
            tab.configure(
                fg=AMBER_D if m == mode else DIM,
                bg=BG3 if m == mode else BG,
            )
        self._list_cache = None  # force refresh on filter change
        self._render()

    def _fetch_runs(self) -> list[dict]:
        now = time.monotonic()
        cache = self._list_cache
        if cache is not None and cache[1] == self._mode_filter and \
                (now - cache[0]) < self._TTL_SEC:
            return cache[2]
        mode = None if self._mode_filter == "all" else self._mode_filter
        runs = db_live_runs.list_live_runs(mode=mode, limit=200)
        self._list_cache = (now, self._mode_filter, runs)
        return runs

    def _render(self) -> None:
        runs = self._fetch_runs()
        if self._list_frame is None:
            return
        for w in self._list_frame.winfo_children():
            w.destroy()
        if not runs:
            tk.Label(self._list_frame,
                     text="  no runs in this mode.",
                     font=(FONT, 9), fg=DIM, bg=BG,
                     anchor="w").pack(fill="x", pady=8)
            return
        for run in runs:
            self._render_row(run)
        # auto-select newest if none selected
        if self._selected_run_id is None and runs:
            self._select(runs[0]["run_id"])

    def _render_row(self, run: dict) -> None:
        if self._list_frame is None:
            return
        state_color = {
            "running": AMBER, "stopped": DIM, "crashed": DIM,
        }.get(run.get("status") or "", DIM)
        row = tk.Frame(self._list_frame, bg=BG, cursor="hand2")
        row.pack(fill="x", padx=2, pady=1)
        row.bind("<Button-1>",
                 lambda _e, rid=run["run_id"]: self._select(rid))
        cols = [
            (run.get("status", "?")[:6].upper(), state_color, _LIST_COLS[0][1]),
            (run.get("engine", "?")[:10], AMBER, _LIST_COLS[1][1]),
            (run.get("mode", "?")[:5].upper(), AMBER_D, _LIST_COLS[2][1]),
            ((run.get("started_at") or "")[:16], DIM, _LIST_COLS[3][1]),
            (str(run.get("tick_count") or 0), DIM, _LIST_COLS[4][1]),
            (str(run.get("novel_count") or 0), DIM, _LIST_COLS[5][1]),
            (f"{run.get('equity') or 0:.0f}", DIM, _LIST_COLS[6][1]),
        ]
        for text, color, width in cols:
            lbl = tk.Label(row, text=text, font=(FONT, 8),
                           fg=color, bg=BG, width=width, anchor="w")
            lbl.pack(side="left")
            lbl.bind("<Button-1>",
                     lambda _e, rid=run["run_id"]: self._select(rid))

    def _select(self, run_id: str) -> None:
        self._selected_run_id = run_id
        self._render_detail(run_id)

    def _render_detail(self, run_id: str) -> None:
        # Stubbed — expanded in Task 10.
        if self._detail_frame is None:
            return
        for w in self._detail_frame.winfo_children():
            w.destroy()
        run = db_live_runs.get_live_run(run_id)
        if run is None:
            tk.Label(self._detail_frame, text="run not found",
                     font=(FONT, 9), fg=DIM, bg=PANEL).pack(anchor="w")
            return
        tk.Label(
            self._detail_frame,
            text=f"{run['engine']} / {run['mode']}  |  {run['run_id']}",
            font=(FONT, 9, "bold"), fg=AMBER, bg=PANEL, anchor="w",
        ).pack(anchor="w")
```

- [ ] **Step 8.4 — Run test, confirm PASS**

Run: `python -m pytest tests/launcher/test_live_runs_screen.py -v`
Expected: 4 passed.

- [ ] **Step 8.5 — Commit**

```bash
git add launcher_support/screens/live_runs.py tests/launcher/test_live_runs_screen.py
git commit -m "feat(launcher): LiveRunsScreen skeleton — filter bar + list render + TTL cache"
```

---

## Task 9 — Detail panel: IDENTITY / TIMELINE / PERFORMANCE / ACTIVITY / ACTIONS

**Files:**
- Modify: `launcher_support/screens/live_runs.py`
- Modify: `tests/launcher/test_live_runs_screen.py`

- [ ] **Step 9.1 — Add detail test**

Append to `tests/launcher/test_live_runs_screen.py`:

```python
@pytest.mark.gui
def test_detail_panel_renders_sections(
    gui_root, fake_app, fake_runs, monkeypatch,
):
    monkeypatch.setattr(
        "launcher_support.screens.live_runs.db_live_runs.list_live_runs",
        lambda **kw: fake_runs,
    )
    monkeypatch.setattr(
        "launcher_support.screens.live_runs.db_live_runs.get_live_run",
        lambda rid: next(r for r in fake_runs if r["run_id"] == rid),
    )
    s = LiveRunsScreen(parent=gui_root, app=fake_app)
    s.mount()
    s.on_enter()
    # Detail for first run (auto-select)
    texts = []
    def collect(w):
        if isinstance(w, tk.Label):
            texts.append(w.cget("text"))
        for c in w.winfo_children():
            collect(c)
    collect(s._detail_frame)
    blob = " ".join(texts)
    assert "IDENTITY" in blob
    assert "TIMELINE" in blob
    assert "PERFORMANCE" in blob
    assert "ACTIVITY" in blob
```

- [ ] **Step 9.2 — Run test, confirm FAIL**

Run: `python -m pytest tests/launcher/test_live_runs_screen.py::test_detail_panel_renders_sections -v`
Expected: FAIL — sections missing.

- [ ] **Step 9.3 — Expand `_render_detail`**

Replace the stub `_render_detail` in `live_runs.py`:

```python
    def _render_detail(self, run_id: str) -> None:
        if self._detail_frame is None:
            return
        for w in self._detail_frame.winfo_children():
            w.destroy()
        run = db_live_runs.get_live_run(run_id)
        if run is None:
            tk.Label(self._detail_frame, text="run not found",
                     font=(FONT, 9), fg=DIM, bg=PANEL).pack(anchor="w")
            return

        tk.Label(
            self._detail_frame,
            text=f"{run['engine']} / {run['mode']}",
            font=(FONT, 10, "bold"), fg=AMBER, bg=PANEL, anchor="w",
        ).pack(anchor="w")
        tk.Label(
            self._detail_frame, text=run["run_id"],
            font=(FONT, 8), fg=DIM, bg=PANEL, anchor="w",
        ).pack(anchor="w", pady=(0, 8))

        self._detail_section("IDENTITY", [
            ("engine", run.get("engine", "?")),
            ("mode", run.get("mode", "?")),
            ("host", run.get("host") or "?"),
            ("label", run.get("label") or "-"),
            ("run_dir", run.get("run_dir") or "?"),
        ])
        self._detail_section("TIMELINE", [
            ("started", (run.get("started_at") or "?")[:19]),
            ("ended", (run.get("ended_at") or "-")[:19]),
            ("last tick", (run.get("last_tick_at") or "-")[:19]),
            ("status", run.get("status") or "unknown"),
        ])
        self._detail_section("PERFORMANCE", [
            ("equity", f"{run.get('equity') or 0:.2f}"),
            ("open positions", str(run.get("open_count") or 0)),
        ])
        self._detail_section("ACTIVITY", [
            ("ticks", str(run.get("tick_count") or 0)),
            ("novel signals", str(run.get("novel_count") or 0)),
        ])

    def _detail_section(self, title: str, rows: list[tuple[str, str]]) -> None:
        if self._detail_frame is None:
            return
        tk.Label(
            self._detail_frame, text=title,
            font=(FONT, 8, "bold"), fg=AMBER_D, bg=PANEL, anchor="w",
        ).pack(anchor="w", pady=(6, 2))
        tk.Frame(self._detail_frame, bg=DIM2, height=1).pack(fill="x")
        for k, v in rows:
            row = tk.Frame(self._detail_frame, bg=PANEL)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=f"  {k}", font=(FONT, 8),
                     fg=DIM, bg=PANEL, anchor="w", width=18).pack(side="left")
            tk.Label(row, text=str(v), font=(FONT, 8),
                     fg=WHITE, bg=PANEL, anchor="w").pack(side="left")
```

- [ ] **Step 9.4 — Run test, confirm PASS**

Run: `python -m pytest tests/launcher/test_live_runs_screen.py -v`
Expected: 5 passed.

- [ ] **Step 9.5 — Commit**

```bash
git add launcher_support/screens/live_runs.py tests/launcher/test_live_runs_screen.py
git commit -m "feat(launcher): LiveRunsScreen detail panel — IDENTITY/TIMELINE/PERFORMANCE/ACTIVITY"
```

---

## Task 10 — Actions: OPEN DIR, ARCHIVE, STOP

**Files:**
- Modify: `launcher_support/screens/live_runs.py`
- Modify: `tests/launcher/test_live_runs_screen.py`

- [ ] **Step 10.1 — Add actions test**

Append to `tests/launcher/test_live_runs_screen.py`:

```python
@pytest.mark.gui
def test_archive_action_calls_archiver(
    gui_root, fake_app, fake_runs, monkeypatch,
):
    monkeypatch.setattr(
        "launcher_support.screens.live_runs.db_live_runs.list_live_runs",
        lambda **kw: fake_runs,
    )
    monkeypatch.setattr(
        "launcher_support.screens.live_runs.db_live_runs.get_live_run",
        lambda rid: next(r for r in fake_runs if r["run_id"] == rid),
    )
    calls = []
    monkeypatch.setattr(
        "launcher_support.screens.live_runs._archive_run",
        lambda rid: calls.append(rid) or True,
    )
    s = LiveRunsScreen(parent=gui_root, app=fake_app)
    s.mount()
    s.on_enter()
    s._archive_selected()
    assert calls == ["r1"]
```

- [ ] **Step 10.2 — Run test, confirm FAIL**

Run: `python -m pytest tests/launcher/test_live_runs_screen.py::test_archive_action_calls_archiver -v`
Expected: FAIL.

- [ ] **Step 10.3 — Implement actions**

In `launcher_support/screens/live_runs.py`, add module-level helper:

```python
import shutil
import subprocess
from pathlib import Path

from config.paths import DATA_DIR


def _archive_run(run_id: str) -> bool:
    """Soft-delete: mv run_dir into data/_archive/live/. Returns True on success."""
    from core import db_live_runs as _db
    run = _db.get_live_run(run_id)
    if run is None:
        return False
    src = Path(run["run_dir"])
    if not src.is_absolute():
        src = DATA_DIR.parent / src
    if not src.exists():
        return False
    dst = DATA_DIR / "_archive" / "live" / src.parent.name / src.name
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return False
    shutil.move(str(src), str(dst))
    return True


def _open_dir(run_dir: str) -> None:
    p = Path(run_dir)
    if not p.is_absolute():
        p = DATA_DIR.parent / p
    if not p.exists():
        return
    subprocess.Popen(["explorer", str(p)])
```

Extend `_render_detail` — after the ACTIVITY section, add ACTIONS:

```python
        actions = tk.Frame(self._detail_frame, bg=PANEL)
        actions.pack(fill="x", pady=(10, 0))
        for label, cmd, color in [
            ("OPEN DIR", lambda rd=run.get("run_dir"): _open_dir(rd or ""), AMBER),
            ("ARCHIVE", self._archive_selected, AMBER_D),
        ]:
            b = tk.Label(
                actions, text=f"  {label}  ", font=(FONT, 8, "bold"),
                fg=color, bg=BG3, cursor="hand2", padx=8, pady=3,
            )
            b.pack(side="left", padx=(0, 6))
            b.bind("<Button-1>", lambda _e, c=cmd: c())
```

Add method:

```python
    def _archive_selected(self) -> None:
        if not self._selected_run_id:
            return
        ok = _archive_run(self._selected_run_id)
        if ok:
            self._list_cache = None
            self._selected_run_id = None
            self._render()
```

- [ ] **Step 10.4 — Run test, confirm PASS**

Run: `python -m pytest tests/launcher/test_live_runs_screen.py -v`
Expected: 6 passed.

- [ ] **Step 10.5 — Commit**

```bash
git add launcher_support/screens/live_runs.py tests/launcher/test_live_runs_screen.py
git commit -m "feat(launcher): LiveRunsScreen actions — OPEN DIR + ARCHIVE (mv to _archive/live/)"
```

---

## Task 11 — Register + wire into DATA CENTER menu

**Files:**
- Modify: `launcher_support/screens/registry.py`
- Modify: `launcher_support/screens/data_center.py`
- Modify: `launcher.py` — add `_data_live_runs` method

- [ ] **Step 11.1 — Register screen**

Edit `launcher_support/screens/registry.py` — add import + registration:

```python
from launcher_support.screens.live_runs import LiveRunsScreen
```

Add after `data_center` registration (same pattern):

```python
    manager.register(
        "live_runs",
        lambda parent: LiveRunsScreen(parent=parent, app=app),
    )
```

- [ ] **Step 11.2 — Add `_data_live_runs` method to launcher.py**

Locate `_data_backtests` (around line 7681). Add right before or after
it (pick a spot that keeps DATA-related methods together):

```python
    def _data_live_runs(self):
        """LIVE RUNS screen — histórico de runs em modos live/paper/shadow/demo/testnet."""
        self._clr(); self._clear_kb()
        # Flip from main to screens_container (same pattern as other migrated screens).
        if self.main.winfo_manager():
            self.main.pack_forget()
        if not self.screens_container.winfo_manager():
            self.screens_container.pack(fill="both", expand=True)
        self.screens.show("live_runs")
```

- [ ] **Step 11.3 — Add LIVE RUNS entry to DATA CENTER screen**

Edit `launcher_support/screens/data_center.py` — in the `sections` list
inside `build()`, add a new section at the top (or insert as first item
of PRIMARY ROUTES):

```python
            (
                "PRIMARY ROUTES",
                [
                    ("H", "RUNS HISTORY", "unified cockpit: local + VPS runs, results, trades, logs", "runs", app._data_runs_history),
                    ("L", "LIVE RUNS", "historico de runs live/paper/shadow/demo/testnet", "live", app._data_live_runs),
                    ("B", "BACKTESTS", "validated runs, metrics and run-level inspection", "backtests", app._data_backtests),
                    ("E", "ENGINE LOGS", "running procs + log tails (legacy — moves to PROCESSES)", "engines", app._data_engines),
                ],
            ),
```

In the `on_enter` method of `data_center.py`, add `"l"` to the keybind
dict:

```python
        for key_label, cmd in {
            "h": app._data_runs_history,
            "l": app._data_live_runs,
            "b": app._data_backtests,
            "e": app._data_engines,
            "p": app._data_lake,
            "r": app._data,
            "x": app._export_analysis,
        }.items():
            app._kb(f"<Key-{key_label}>", cmd)
```

And add a new `"live"` stat entry in `_get_counts` (update method):

```python
    def _get_counts(self) -> dict[str, Any]:
        now = time.monotonic()
        cache = self._counts_cache
        if cache is not None and (now - cache[0]) < self._COUNTS_TTL_SEC:
            return cache[1]
        app = self.app
        eng_running, eng_total = app._data_count_procs()
        data = {
            "bt_count": app._data_count_backtests(),
            "eng_running": eng_running,
            "eng_total": eng_total,
            "rep_count": app._data_count_reports(),
            "cache_tag": self._cache_tag(),
            "live_count": self._count_live_runs(),
        }
        self._counts_cache = (now, data)
        return data

    def _count_live_runs(self) -> int:
        try:
            from core import db_live_runs as _db
            return len(_db.list_live_runs(limit=500))
        except Exception:
            return 0
```

Add `"live"` to the stats dict in `on_enter`:

```python
        stats = {
            "runs": "banco de dados",
            "live": f"{counts['live_count']} runs on db",
            "backtests": f"{bt_count} runs on disk",
            ...
        }
```

- [ ] **Step 11.4 — Run existing tests**

```bash
python -m pytest tests/launcher/test_data_center_screen.py tests/launcher/test_live_runs_screen.py -v
```

Expected: all pass. If `test_data_center_screen.py::test_get_counts_first_call_hits_disk` fails because of new `live_count` key, update the test to include it.

Quick fix to that test: add in the assertion block:

```python
    assert counts["live_count"] == 0  # empty db in test
```

And stub `_count_live_runs` via monkeypatch in the fixture or test.

- [ ] **Step 11.5 — Commit**

```bash
git add launcher_support/screens/registry.py launcher_support/screens/data_center.py launcher.py tests/launcher/test_data_center_screen.py
git commit -m "feat(launcher): wire LIVE RUNS into DATA CENTER menu (key L) + registry"
```

---

## Task 12 — Integration test + smoke verify

**Files:**
- Create: `tests/integration/test_launcher_live_runs.py`

- [ ] **Step 12.1 — Write integration test**

Create `tests/integration/test_launcher_live_runs.py`:

```python
"""Integration: Terminal app shows LIVE RUNS screen via ScreenManager."""
from __future__ import annotations

import sqlite3
import tkinter as tk
from pathlib import Path

import pytest

from core.ops import db_live_runs
from tools.maintenance.migrations import migration_001_live_runs as mig


@pytest.fixture
def fake_live_db(tmp_path, monkeypatch):
    db = tmp_path / "a.db"
    conn = sqlite3.connect(db)
    mig.apply(conn)
    conn.close()
    monkeypatch.setattr(db_live_runs, "DB_PATH", db)
    db_live_runs.upsert(
        run_id="test_paper_2026-04-20_1200",
        engine="millennium", mode="paper",
        started_at="2026-04-20T12:00:00+00:00",
        run_dir="data/millennium_paper/2026-04-20_1200",
        host="localhost", status="running",
        tick_count=20, novel_count=3, equity=10123.45,
        last_tick_at="2026-04-20T12:05:00+00:00",
    )
    return db


@pytest.mark.gui
def test_live_runs_screen_shows_via_screen_manager(fake_live_db):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("tk unavailable")
    root.withdraw()
    try:
        from launcher_support.screens.manager import ScreenManager
        from launcher_support.screens.live_runs import LiveRunsScreen
        from unittest.mock import MagicMock

        app = MagicMock()
        parent = tk.Frame(root)
        mgr = ScreenManager(parent=parent)
        mgr.register(
            "live_runs",
            lambda p, a=app: LiveRunsScreen(parent=p, app=a),
        )
        s = mgr.show("live_runs")
        assert s is not None
        assert mgr.current_name() == "live_runs"
    finally:
        root.destroy()
```

- [ ] **Step 12.2 — Run test**

Run: `python -m pytest tests/integration/test_launcher_live_runs.py -v`
Expected: PASS.

- [ ] **Step 12.3 — Run full smoke**

```bash
python smoke_test.py --quiet
```

Expected: `178/178 passed` (may change to 179 or 180 with new tests).

- [ ] **Step 12.4 — Run full launcher + integration**

```bash
python -m pytest tests/launcher/ tests/integration/test_launcher_live_runs.py tests/integration/test_paper_runner_db_hook.py tests/tools/ tests/core/test_db_live_runs.py -v
```

Expected: all pass.

- [ ] **Step 12.5 — Commit**

```bash
git add tests/integration/test_launcher_live_runs.py
git commit -m "test(integration): LIVE RUNS screen end-to-end via ScreenManager"
```

---

## Task 13 — Session log + daily log update

**Files:**
- Create: `docs/sessions/YYYY-MM-DD_HHMM.md`
- Modify: `docs/days/YYYY-MM-DD.md`

- [ ] **Step 13.1 — Write session log**

Follow CLAUDE.md session log template. Include:
- Resumo: 3 frases sobre Fase 1 + Fase 2
- Commits: all hashes from this plan
- Mudanças críticas: DB schema, runtime hook em runners (NENHUMA em CORE PROTEGIDO)
- Estado: suite counts

- [ ] **Step 13.2 — Update daily log**

Incrementar `docs/days/YYYY-MM-DD.md` com:
- sessão no topo da lista
- entrega: "LIVE RUNS refactor — Fase 1 + Fase 2 shipadas"

- [ ] **Step 13.3 — Commit**

```bash
git add docs/sessions/ docs/days/
git commit -m "docs(sessions): YYYY-MM-DD_HHMM live runs refactor shipped"
```

---

## Out-of-scope (Fase 3, future sessions)

- `tools/maintenance/archive_old_live_runs.py` — retenção automática 90d
- Sparkline de equity no detail panel (Canvas reuse)
- Telegram deep link no detail
- Hook em `engines/live.py` (atualmente 248 dirs órfãos em `data/live/`
  — backfill já os registra no DB, mas runtime não atualiza. Quando
  usuário voltar a usar `engines/live.py`, adicionar hook igual paper/shadow)

---

## Success criteria recap

After all tasks complete:

1. `aurum.db` has `live_runs` table with rows for every existing
   millennium/live/paper/shadow dir.
2. `data/_archive/research/` contains all moved research dirs.
3. `data/_archive/db/nexus.db.<stamp>` exists.
4. `data/runs/` empty or gone (legacy runs moved to engine dirs).
5. LIVE RUNS screen reachable via DATA CENTER > L, renders rows, filter
   works, detail panel shows sections, ARCHIVE moves dirs to
   `data/_archive/live/`.
6. Smoke suite passes (178+ tests).
7. Contracts suite passes (835+).
8. Launcher opens and navigation feels smooth (sub-5ms reentry on
   LIVE RUNS).
