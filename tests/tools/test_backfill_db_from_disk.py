from __future__ import annotations

import sqlite3

from tools.maintenance.backfill_db_from_disk import (
    db_run_ids,
    find_report_json,
    group_missing,
    missing_runs,
    walk_disk,
)


def _make_db(path):
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY)")
        conn.execute("INSERT INTO runs (run_id) VALUES (?)", ("citadel_2026-04-20_1000",))
        conn.commit()
    finally:
        conn.close()


def test_find_report_json_prefers_reports_dir_then_summary(tmp_path):
    run_dir = tmp_path / "run"
    reports = run_dir / "reports"
    reports.mkdir(parents=True)
    (reports / "config.json").write_text("{}", encoding="utf-8")
    primary = reports / "report.json"
    primary.write_text("{}", encoding="utf-8")

    assert find_report_json(run_dir) == primary

    primary.unlink()
    (run_dir / "summary.json").write_text("{}", encoding="utf-8")
    assert find_report_json(run_dir) == run_dir / "summary.json"


def test_db_run_ids_reads_existing_rows(tmp_path):
    db = tmp_path / "aurum.db"
    _make_db(db)

    assert db_run_ids(db_path=db) == {"citadel_2026-04-20_1000"}


def test_walk_disk_collects_engine_runs(tmp_path):
    run_dir = tmp_path / "bridgewater" / "2026-04-20_1001" / "reports"
    run_dir.mkdir(parents=True)
    report = run_dir / "report.json"
    report.write_text("{}", encoding="utf-8")

    disk = walk_disk(data_dir=tmp_path)

    assert disk == [("bridgewater", tmp_path / "bridgewater" / "2026-04-20_1001", report)]


def test_missing_runs_treats_prefixed_or_bare_ids_as_covered(tmp_path):
    report = tmp_path / "report.json"
    report.write_text("{}", encoding="utf-8")
    disk_runs = [
        ("citadel", tmp_path / "2026-04-20_1000", report),
        ("jump", tmp_path / "jump_2026-04-20_1001", report),
        ("bridgewater", tmp_path / "2026-04-20_1002", report),
    ]

    missing = missing_runs(
        existing_ids={"citadel_2026-04-20_1000", "jump_2026-04-20_1001"},
        disk_runs=disk_runs,
    )

    assert missing == [("bridgewater", tmp_path / "2026-04-20_1002", report)]
    assert group_missing(missing) == {"bridgewater": 1}
