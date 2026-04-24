"""Tests for backfill_live_runs script."""
from __future__ import annotations

import json
import sqlite3
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


def test_heartbeat_status_running_but_no_last_tick_forced_stopped(
    fake_data_root: Path,
) -> None:
    """A heartbeat claiming running with no last_tick_at is a dead runner."""
    _make_run(
        fake_data_root, "millennium_paper", "2026-04-18_0900",
        heartbeat={
            "run_id": "paper_2026-04-18_0900",
            "started_at": "2026-04-18T09:00:00+00:00",
            "status": "running",
            # no last_tick_at
        },
    )
    bf.run(dry_run=False)
    rows = db_live_runs.list_live_runs()
    assert len(rows) == 1
    assert rows[0]["status"] == "stopped"
