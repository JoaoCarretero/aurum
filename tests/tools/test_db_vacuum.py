"""Unit tests for db_vacuum maintenance helper."""
from __future__ import annotations

import sqlite3
from datetime import datetime

from tools.maintenance.db_vacuum import backup_db, human, run_vacuum, top_tables


def _make_db(path):
    with sqlite3.connect(path) as con:
        con.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, pnl REAL)")
        con.execute("CREATE TABLE fills (id INTEGER PRIMARY KEY, symbol TEXT)")
        con.executemany(
            "INSERT INTO trades (pnl) VALUES (?)",
            [(float(i),) for i in range(20)],
        )
        con.executemany(
            "INSERT INTO fills (symbol) VALUES (?)",
            [(f"S{i}",) for i in range(5)],
        )
        con.commit()


def test_human_formats_sizes():
    assert human(512) == "512.0 B"
    assert human(2048) == "2.0 KB"


def test_top_tables_sorts_by_row_count(tmp_path):
    db = tmp_path / "aurum.db"
    _make_db(db)

    tables = top_tables(db, limit=2)

    assert tables == [("trades", 20), ("fills", 5)]


def test_backup_db_creates_timestamped_copy(tmp_path):
    db = tmp_path / "aurum.db"
    backup_dir = tmp_path / "backups"
    db.write_text("payload", encoding="utf-8")

    backup = backup_db(db, backup_dir, now=datetime(2026, 4, 20, 9, 30, 0))

    assert backup == backup_dir / "aurum.db.2026-04-20_093000.bak"
    assert backup.read_text(encoding="utf-8") == "payload"


def test_run_vacuum_preserves_backup_and_reports_sizes(tmp_path):
    db = tmp_path / "aurum.db"
    backup_dir = tmp_path / "backups"
    _make_db(db)
    size_before_insert = db.stat().st_size

    with sqlite3.connect(db) as con:
        con.executemany(
            "INSERT INTO trades (pnl) VALUES (?)",
            [(float(i),) for i in range(5000)],
        )
        con.execute("DELETE FROM trades WHERE id > 25")
        con.commit()

    grown_size = db.stat().st_size
    assert grown_size >= size_before_insert

    backup, size_before, size_after = run_vacuum(
        db,
        backup_dir=backup_dir,
        now=datetime(2026, 4, 20, 9, 31, 0),
    )

    assert backup.exists()
    assert size_before == grown_size
    assert size_after <= size_before
    assert backup.read_bytes() != b""
