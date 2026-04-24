from __future__ import annotations

import sqlite3

from tools.maintenance.rebuild_db import backup_db, current_counts, find_reports, report_counts, wipe_db


def _make_db(path):
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE runs (id INTEGER PRIMARY KEY, run_id TEXT)")
        conn.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, run_id TEXT)")
        conn.execute("INSERT INTO runs (run_id) VALUES ('r1')")
        conn.execute("INSERT INTO trades (run_id) VALUES ('r1')")
        conn.commit()
    finally:
        conn.close()


def test_find_reports_discovers_engine_reports_and_skips_aux_files(tmp_path):
    citadel_dir = tmp_path / "runs" / "2026-04-20_1000"
    bridgewater_reports = tmp_path / "bridgewater" / "2026-04-20_1000" / "reports"
    citadel_dir.mkdir(parents=True)
    bridgewater_reports.mkdir(parents=True)
    (citadel_dir / "citadel_btc_v1.json").write_text("{}", encoding="utf-8")
    (bridgewater_reports / "summary.json").write_text("{}", encoding="utf-8")
    (bridgewater_reports / "report.json").write_text("{}", encoding="utf-8")

    reports = find_reports(data_dir=tmp_path)

    assert reports == [
        ("citadel", citadel_dir / "citadel_btc_v1.json"),
        ("bridgewater", bridgewater_reports / "report.json"),
    ]


def test_report_counts_aggregates_by_engine():
    counts = report_counts([("citadel", object()), ("citadel", object()), ("jump", object())])

    assert counts == {"citadel": 2, "jump": 1}


def test_backup_db_dry_run_returns_planned_path(tmp_path):
    db = tmp_path / "aurum.db"
    db.write_text("db", encoding="utf-8")

    planned = backup_db(db_path=db, dry_run=True, stamp="2026-04-20_100000")

    assert planned == tmp_path / "aurum.bak_2026-04-20_100000.db"
    assert not planned.exists()


def test_current_counts_and_wipe_db(tmp_path):
    db = tmp_path / "aurum.db"
    _make_db(db)

    assert current_counts(db_path=db) == (1, 1)
    wipe_db(db_path=db, dry_run=False)
    assert current_counts(db_path=db) == (0, 0)
