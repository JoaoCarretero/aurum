from __future__ import annotations

import json
import sqlite3

from tools.maintenance.normalize_run_ids import (
    _apply_db,
    _apply_index,
    _db_plan,
    _dedupe_index,
    _index_plan,
    _needs_prefix,
)


def _make_db(path):
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE runs (run_id TEXT PRIMARY KEY, engine TEXT)")
        conn.execute("CREATE TABLE trades (id INTEGER PRIMARY KEY, run_id TEXT)")
        conn.execute("INSERT INTO runs (run_id, engine) VALUES (?, ?)", ("2026-04-20_1000", "citadel"))
        conn.execute("INSERT INTO trades (run_id) VALUES (?)", ("2026-04-20_1000",))
        conn.commit()
    finally:
        conn.close()


def test_needs_prefix_skips_known_prefixed_forms():
    assert _needs_prefix("citadel_2026-04-20_1000", "citadel") is False
    assert _needs_prefix("jump_2026-04-20_1000", "citadel") is False
    assert _needs_prefix("2026-04-20_1000", "citadel") is True


def test_db_plan_finds_legacy_ids(tmp_path):
    db = tmp_path / "aurum.db"
    _make_db(db)

    plan = _db_plan(db_path=db)

    assert plan == [("2026-04-20_1000", "citadel", "citadel_2026-04-20_1000")]


def test_index_plan_infers_engine_and_backtest_alias(tmp_path):
    index = tmp_path / "index.json"
    index.write_text(
        json.dumps(
            [
                {"run_id": "2026-04-20_1000", "engine": "citadel"},
                {"run_id": "2026-04-20_1001", "strategy": "backtest"},
                {"run_id": "jump_2026-04-20_1002", "engine": "jump"},
            ]
        ),
        encoding="utf-8",
    )

    plan = _index_plan(index_path=index)

    assert plan == [
        (0, "2026-04-20_1000", "citadel", "citadel_2026-04-20_1000"),
        (1, "2026-04-20_1001", "citadel", "citadel_2026-04-20_1001"),
    ]


def test_apply_db_updates_runs_and_trades(tmp_path):
    db = tmp_path / "aurum.db"
    _make_db(db)

    changes = _apply_db([("2026-04-20_1000", "citadel", "citadel_2026-04-20_1000")], db_path=db)

    conn = sqlite3.connect(db)
    try:
        run_id = conn.execute("SELECT run_id FROM runs").fetchone()[0]
        trade_run_id = conn.execute("SELECT run_id FROM trades").fetchone()[0]
    finally:
        conn.close()
    assert changes == 1
    assert run_id == "citadel_2026-04-20_1000"
    assert trade_run_id == "citadel_2026-04-20_1000"


def test_apply_index_and_dedupe_keep_last_duplicate(tmp_path):
    index = tmp_path / "index.json"
    index.write_text(
        json.dumps(
            [
                {"run_id": "2026-04-20_1000", "engine": "citadel"},
                {"run_id": "citadel_2026-04-20_1000", "engine": "citadel", "note": "last"},
                {"misc": "keep"},
            ]
        ),
        encoding="utf-8",
    )

    changes = _apply_index([(0, "2026-04-20_1000", "citadel", "citadel_2026-04-20_1000")], index_path=index)
    dropped = _dedupe_index(index_path=index)
    data = json.loads(index.read_text(encoding="utf-8"))

    assert changes == 1
    assert dropped == 1
    assert data == [
        {"run_id": "citadel_2026-04-20_1000", "engine": "citadel", "note": "last"},
        {"misc": "keep"},
    ]
