"""Tests for tools/maintenance/normalize_live_trades_details.py.

The migration walks live_trades + live_signals and unwraps any
details_json that was double-wrapped by the pre-fix _norm_*. Idempotent
— rerunning on a normalised DB is a no-op.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest


@pytest.fixture
def db(tmp_path: Path):
    p = tmp_path / "test.db"
    conn = sqlite3.connect(str(p))
    from tools.maintenance.migrations import (
        migration_001_live_runs,
        migration_002_live_trades,
    )
    migration_001_live_runs.apply(conn)
    migration_002_live_trades.apply(conn)
    yield conn, p
    conn.close()


def _insert_trade(conn, run_id, ts, symbol, details_json):
    conn.execute(
        "INSERT INTO live_trades (run_id, ts, symbol, direction, entry, "
        "details_json) VALUES (?, ?, ?, ?, ?, ?)",
        (run_id, ts, symbol, "LONG", 1.0, details_json),
    )
    conn.commit()


def _insert_signal(conn, run_id, observed_at, symbol, details_json):
    conn.execute(
        "INSERT INTO live_signals (run_id, observed_at, symbol, strategy, "
        "direction, details_json) VALUES (?, ?, ?, ?, ?, ?)",
        (run_id, observed_at, symbol, "JUMP", "BULLISH", details_json),
    )
    conn.commit()


def test_unwraps_double_wrapped_trade(db):
    conn, _ = db
    inner = json.dumps({"id": "pos_1", "engine": "JUMP", "bars_held": 0})
    wrapped = json.dumps({"details_json": inner})
    _insert_trade(conn, "rid", "ts1", "XRP", wrapped)

    from tools.maintenance import normalize_live_trades_details as nm
    n_t, n_s = nm.normalize(conn)
    conn.commit()

    assert n_t == 1
    assert n_s == 0
    raw = conn.execute(
        "SELECT details_json FROM live_trades WHERE ts='ts1'").fetchone()[0]
    parsed = json.loads(raw)
    assert "details_json" not in parsed, \
        f"still wrapped after migration: {parsed!r}"
    assert parsed["id"] == "pos_1"
    assert parsed["engine"] == "JUMP"


def test_unwraps_double_wrapped_signal(db):
    conn, _ = db
    inner = json.dumps({"trade_type": "ORDER-FLOW", "struct": "DOWN"})
    wrapped = json.dumps({"details_json": inner})
    _insert_signal(conn, "rid", "obs1", "SAND", wrapped)

    from tools.maintenance import normalize_live_trades_details as nm
    n_t, n_s = nm.normalize(conn)
    conn.commit()

    assert n_t == 0
    assert n_s == 1
    raw = conn.execute(
        "SELECT details_json FROM live_signals "
        "WHERE observed_at='obs1'").fetchone()[0]
    parsed = json.loads(raw)
    assert "details_json" not in parsed
    assert parsed["trade_type"] == "ORDER-FLOW"


def test_idempotent_on_clean_row(db):
    """A row that's already canonical must not be touched."""
    conn, _ = db
    clean = json.dumps({"id": "pos_2", "engine": "CITADEL"})
    _insert_trade(conn, "rid", "ts2", "BTC", clean)

    from tools.maintenance import normalize_live_trades_details as nm
    n_t, n_s = nm.normalize(conn)
    assert n_t == 0
    assert n_s == 0
    raw = conn.execute(
        "SELECT details_json FROM live_trades WHERE ts='ts2'").fetchone()[0]
    assert raw == clean  # byte-for-byte unchanged


def test_idempotent_double_run(db):
    """Running twice on a DB with one wrapped row: first pass fixes it,
    second pass is a no-op."""
    conn, _ = db
    inner = json.dumps({"k": "v"})
    wrapped = json.dumps({"details_json": inner})
    _insert_trade(conn, "rid", "ts3", "ETH", wrapped)

    from tools.maintenance import normalize_live_trades_details as nm
    n1_t, n1_s = nm.normalize(conn)
    conn.commit()
    n2_t, n2_s = nm.normalize(conn)
    assert n1_t == 1
    assert n2_t == 0
    assert n1_s == 0 and n2_s == 0


def test_skips_rows_with_null_details(db):
    conn, _ = db
    _insert_trade(conn, "rid", "ts4", "AVAX", None)
    from tools.maintenance import normalize_live_trades_details as nm
    n_t, n_s = nm.normalize(conn)
    assert n_t == 0
    assert n_s == 0


def test_dry_run_does_not_mutate(db):
    conn, _ = db
    wrapped = json.dumps({"details_json": json.dumps({"id": "pos_x"})})
    _insert_trade(conn, "rid", "ts5", "LINK", wrapped)

    from tools.maintenance import normalize_live_trades_details as nm
    n_t, n_s = nm.normalize(conn, dry_run=True)
    # Counts what WOULD change but doesn't write
    assert n_t == 1
    raw = conn.execute(
        "SELECT details_json FROM live_trades WHERE ts='ts5'").fetchone()[0]
    assert raw == wrapped, "dry_run mutated the row"


def test_handles_pathological_inner_not_json(db):
    """Defensive: outer is {'details_json': '...'} but inner isn't valid
    JSON. Skip it (no-op) — preserve original rather than corrupt."""
    conn, _ = db
    wrapped = json.dumps({"details_json": "not-json-at-all"})
    _insert_trade(conn, "rid", "ts6", "FET", wrapped)

    from tools.maintenance import normalize_live_trades_details as nm
    n_t, n_s = nm.normalize(conn)
    # Defensive — count as 0 changes, leave row untouched
    assert n_t == 0
    raw = conn.execute(
        "SELECT details_json FROM live_trades WHERE ts='ts6'").fetchone()[0]
    assert raw == wrapped


def test_handles_outer_not_dict(db):
    """If details_json is a JSON list/string/null/number, skip silently."""
    conn, _ = db
    _insert_trade(conn, "rid", "ts7", "FET", json.dumps([1, 2, 3]))
    _insert_trade(conn, "rid", "ts8", "FET", json.dumps("just a string"))

    from tools.maintenance import normalize_live_trades_details as nm
    n_t, n_s = nm.normalize(conn)
    assert n_t == 0


def test_only_unwraps_exact_singleton_wrap(db):
    """If outer dict has details_json AND other keys, we don't unwrap —
    that's a legitimate dict with a 'details_json' field, not a wrap."""
    conn, _ = db
    rich = json.dumps({"details_json": "inner", "other": 42})
    _insert_trade(conn, "rid", "ts9", "FET", rich)

    from tools.maintenance import normalize_live_trades_details as nm
    n_t, n_s = nm.normalize(conn)
    assert n_t == 0
    raw = conn.execute(
        "SELECT details_json FROM live_trades WHERE ts='ts9'").fetchone()[0]
    assert raw == rich
