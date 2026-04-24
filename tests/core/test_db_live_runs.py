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
    m._MIGRATED_PATHS.discard(str(db))
    return db


def test_auto_migration_on_fresh_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """_connect() must auto-apply migration_001 on a fresh DB.

    Guards the no-manual-migrate path: new VPS install, CI tmpdir, or any
    process hitting aurum.db before the operator ran the migration script.
    """
    db = tmp_path / "fresh.db"
    monkeypatch.setattr(m, "DB_PATH", db)
    m._MIGRATED_PATHS.discard(str(db))
    m.upsert(
        run_id="auto_mig_run",
        engine="citadel",
        mode="paper",
        started_at="2026-04-22T12:00:00Z",
        run_dir="data/x",
    )
    rows = m.list_live_runs()
    assert len(rows) == 1
    assert rows[0]["run_id"] == "auto_mig_run"


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


def test_upsert_update_rejects_immutable_fields(fake_db: Path) -> None:
    m.upsert(run_id="r1", engine="citadel", mode="paper",
             started_at="2026-04-20T12:00:00Z", run_dir="d/r1")
    with pytest.raises(ValueError, match="immutable"):
        m.upsert(run_id="r1", engine="WRONG", tick_count=5)
    # Row must be unchanged: no partial UPDATE
    row = m.get_live_run("r1")
    assert row["engine"] == "citadel"
    assert row["tick_count"] == 0


def test_list_filters_by_since(fake_db: Path) -> None:
    m.upsert(run_id="old", engine="citadel", mode="paper",
             started_at="2026-04-18T00:00:00Z", run_dir="d/old")
    m.upsert(run_id="new", engine="citadel", mode="paper",
             started_at="2026-04-20T12:00:00Z", run_dir="d/new")
    rows = m.list_live_runs(since="2026-04-19T00:00:00Z")
    assert len(rows) == 1
    assert rows[0]["run_id"] == "new"


def test_cleanup_stale_rows_marks_stopped_and_tags_notes(fake_db: Path) -> None:
    """cleanup_stale_rows: transiciona 'running' stuck → 'stopped' e tagga
    notes com 'auto_cleanup_stale_YYYYMMDD_HHMM' pra debug. Fresh runs
    (last_tick dentro do threshold) ficam intactos."""
    m.upsert(run_id="zombie", engine="citadel", mode="paper",
             started_at="2026-01-01T00:00:00Z", run_dir="d/zombie",
             status="running",
             last_tick_at="2026-01-01T00:00:00Z")  # way past 30min
    m.upsert(run_id="fresh", engine="citadel", mode="paper",
             started_at="2026-04-24T10:00:00Z", run_dir="d/fresh",
             status="running",
             last_tick_at=_now_iso_minus_minutes(5))

    n = m.cleanup_stale_rows(stale_minutes=30)
    assert n == 1

    zombie = m.get_live_run("zombie")
    fresh = m.get_live_run("fresh")
    assert zombie is not None and zombie["status"] == "stopped"
    assert zombie["ended_at"] is not None
    assert zombie["notes"] is not None
    assert zombie["notes"].startswith("auto_cleanup_stale_")
    assert fresh is not None and fresh["status"] == "running"


def test_cleanup_stale_rows_idempotent_on_already_stopped(fake_db: Path) -> None:
    """Re-executar cleanup nao mexe em rows ja stopped."""
    m.upsert(run_id="zombie", engine="citadel", mode="paper",
             started_at="2026-01-01T00:00:00Z", run_dir="d/zombie",
             status="running",
             last_tick_at="2026-01-01T00:00:00Z")
    assert m.cleanup_stale_rows(stale_minutes=30) == 1
    # Second call: nothing left to clean
    assert m.cleanup_stale_rows(stale_minutes=30) == 0


def _now_iso_minus_minutes(mins: int) -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(minutes=mins)).isoformat()
