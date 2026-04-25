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


def test_backfill_covers_non_millennium_engines(fake_data_root: Path) -> None:
    """Pre-fix, only millennium_* dirs were catalogued; citadel/jump/
    renaissance/probe were silently skipped, which is why the live-
    engines audit kept flagging them as DB-missing."""
    _make_run(
        fake_data_root, "citadel_shadow", "2026-04-22_1500",
        heartbeat={
            "started_at": "2026-04-22T15:00:00+00:00",
            "last_tick_at": "2026-04-22T15:05:00+00:00",
            "ticks_ok": 3, "novel_total": 0, "equity": 10000.0,
            "status": "running", "mode": "shadow",
        },
    )
    _make_run(
        fake_data_root, "jump_paper", "2026-04-22_1502",
        heartbeat={
            "started_at": "2026-04-22T15:02:00+00:00",
            "last_tick_at": "2026-04-22T15:05:00+00:00",
            "ticks_ok": 1, "novel_total": 0, "equity": 10000.0,
            "status": "running", "mode": "paper",
        },
    )
    n = bf.run(dry_run=False)
    assert n == 2
    engines = {r["engine"] for r in db_live_runs.list_live_runs()}
    assert engines == {"citadel", "jump"}


def test_parse_vps_row_maps_payload_fields() -> None:
    """VPS /v1/runs payload → live_runs upsert dict conversion."""
    row = {
        "run_id": "2026-04-24_174018p_desk-paper-b",
        "engine": "MILLENNIUM",
        "mode": "paper",
        "status": "running",
        "started_at": "2026-04-24T17:40:18.130356+00:00",
        "last_tick_at": "2026-04-24T18:15:00+00:00",
        "ticks_ok": 9,
        "novel_total": 1,
        "equity": 10010.5,
        "host": "srv-01",
        "label": "desk-paper-b",
    }
    parsed = bf._parse_vps_row(row)
    assert parsed is not None
    # engine/mode normalized to lowercase for consistency with local-disk
    # rows (which come from the parent dir name, also lowercase).
    assert parsed["engine"] == "millennium"
    assert parsed["mode"] == "paper"
    assert parsed["status"] == "running"
    assert parsed["tick_count"] == 9
    assert parsed["novel_count"] == 1
    # run_dir is the vps:// sentinel so the row has a non-null path
    # without pretending the files are on local disk.
    assert parsed["run_dir"].startswith("vps://")


def test_parse_vps_row_skips_rows_without_run_id() -> None:
    assert bf._parse_vps_row({"engine": "citadel", "mode": "paper"}) is None


def test_run_from_vps_upserts_all_runs(
    fake_data_root: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_rows = [
        {
            "run_id": "RUN_A", "engine": "citadel", "mode": "paper",
            "status": "running", "started_at": "2026-04-24T17:00:00+00:00",
            "ticks_ok": 5, "novel_total": 1, "equity": 10005.0,
        },
        {
            "run_id": "RUN_B", "engine": "jump", "mode": "shadow",
            "status": "stopped", "started_at": "2026-04-23T10:00:00+00:00",
            "ticks_ok": 30, "novel_total": 2,
        },
    ]

    class _FakeClient:
        def _get(self, path):
            assert path == "/v1/runs"
            return fake_rows

    # Patch the lazy import inside run_from_vps — the function imports
    # the client factory from engines_live_view at call time, so we
    # monkeypatch there rather than at module scope.
    import launcher_support.engines_live_view as evv
    monkeypatch.setattr(evv, "_get_cockpit_client", lambda: _FakeClient())

    seen, written = bf.run_from_vps(dry_run=False)
    assert seen == 2
    assert written == 2
    rows = db_live_runs.list_live_runs()
    run_ids = {r["run_id"] for r in rows}
    assert run_ids == {"RUN_A", "RUN_B"}
