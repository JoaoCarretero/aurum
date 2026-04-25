"""Tests for core/ops/db_live_trades + migration_002."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from core.ops.db_live_trades import (
    upsert_trade,
    upsert_signal,
    upsert_trades_bulk,
    upsert_signals_bulk,
    list_trades_for_run,
    list_signals_for_run,
)
from tools.maintenance.migrations import (
    migration_001_live_runs,
    migration_002_live_trades,
)


@pytest.fixture
def conn(tmp_path: Path):
    db = tmp_path / "test.db"
    c = sqlite3.connect(str(db))
    migration_001_live_runs.apply(c)
    migration_002_live_trades.apply(c)
    yield c
    c.close()


# ─── Migration shape ────────────────────────────────────────────────


def test_migration_creates_both_tables(conn):
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "live_trades" in tables
    assert "live_signals" in tables


def test_migration_idempotent(conn):
    # second apply must not raise
    migration_002_live_trades.apply(conn)
    migration_002_live_trades.apply(conn)


def test_indexes_present(conn):
    idx = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' "
        "AND tbl_name IN ('live_trades','live_signals')").fetchall()}
    assert "idx_live_trades_run" in idx
    assert "idx_live_trades_symbol_ts" in idx
    assert "idx_live_signals_run" in idx
    assert "idx_live_signals_symbol_obs" in idx


# ─── upsert_trade ───────────────────────────────────────────────────


def test_upsert_trade_basic(conn):
    payload = {
        "ts": "2026-04-25T10:00:00Z",
        "symbol": "BTCUSDT",
        "strategy": "citadel",
        "direction": "long",
        "entry": 50000.0,
        "exit": 50500.0,
        "pnl_usd": 5.0,
        "r_multiple": 1.0,
        "exit_reason": "target",
    }
    inserted = upsert_trade(conn, "rid_1", payload)
    assert inserted is True
    rows = list_trades_for_run(conn, "rid_1")
    assert len(rows) == 1
    assert rows[0]["symbol"] == "BTCUSDT"
    assert rows[0]["pnl_usd"] == 5.0
    assert rows[0]["strategy"] == "citadel"


def test_upsert_trade_idempotent(conn):
    payload = {
        "ts": "2026-04-25T10:00:00Z", "symbol": "BTCUSDT",
        "direction": "long", "entry": 50000.0, "pnl_usd": 1.0,
    }
    upsert_trade(conn, "rid_1", payload)
    upsert_trade(conn, "rid_1", payload)
    upsert_trade(conn, "rid_1", payload)
    rows = list_trades_for_run(conn, "rid_1")
    assert len(rows) == 1, "(run_id, ts, symbol) is unique key"


def test_upsert_trade_updates_on_conflict(conn):
    """Re-upsert with newer pnl should overwrite — represents trade close."""
    base = {"ts": "2026-04-25T10:00:00Z", "symbol": "BTCUSDT",
            "direction": "long", "entry": 50000.0, "pnl_usd": 0.0}
    upsert_trade(conn, "rid_1", base)
    base["pnl_usd"] = 5.0
    base["exit"] = 50500.0
    base["exit_reason"] = "target"
    upsert_trade(conn, "rid_1", base)
    rows = list_trades_for_run(conn, "rid_1")
    assert len(rows) == 1
    assert rows[0]["pnl_usd"] == 5.0
    assert rows[0]["exit"] == 50500.0
    assert rows[0]["exit_reason"] == "target"


def test_upsert_trade_handles_legacy_field_names(conn):
    """Older paper jsonl used 'entry_price'/'exit_price'/'pnl' instead of canonical."""
    payload = {
        "ts": "2026-04-25T10:00:00Z", "symbol": "ETHUSDT",
        "direction": "short",
        "entry_price": 3000.0,  # legacy alias
        "exit_price": 2950.0,
        "pnl": 1.67,  # legacy alias
    }
    upsert_trade(conn, "rid_1", payload)
    rows = list_trades_for_run(conn, "rid_1")
    assert rows[0]["entry"] == 3000.0
    assert rows[0]["exit"] == 2950.0
    assert rows[0]["pnl_usd"] == 1.67


def test_upsert_trade_skips_invalid(conn):
    """Missing required fields = skip silently."""
    assert upsert_trade(conn, "rid_1", {"symbol": "BTC"}) is False
    assert list_trades_for_run(conn, "rid_1") == []


def test_upsert_trade_preserves_extras_in_details_json(conn):
    payload = {
        "ts": "2026-04-25T10:00:00Z", "symbol": "BTCUSDT",
        "direction": "long", "entry": 50000.0,
        "weird_field": "engine_specific_value",
        "score": 0.75,  # known col
    }
    upsert_trade(conn, "rid_1", payload)
    rows = list_trades_for_run(conn, "rid_1")
    assert rows[0]["score"] == 0.75
    extras = json.loads(rows[0]["details_json"])
    assert extras["weird_field"] == "engine_specific_value"


# ─── upsert_signal ──────────────────────────────────────────────────


def test_upsert_signal_basic(conn):
    """AVAXUSDT real-world shape from shadow_trades.jsonl."""
    payload = {
        "shadow_observed_at": "2026-04-24T18:31:32Z",
        "timestamp": "2026-04-24 18:15:00",
        "symbol": "AVAXUSDT",
        "strategy": "RENAISSANCE",
        "pattern": "Gartley",
        "direction": "BULLISH",
        "entry": 9.412823,
        "stop": 9.3386,
        "target": 9.4418,
        "score": 0.6598,
        "primed": False,
        "shadow_run_id": "2026-04-24_174018s_desk-shadow-a",
    }
    inserted = upsert_signal(conn, "rid_shadow", payload)
    assert inserted is True
    rows = list_signals_for_run(conn, "rid_shadow")
    assert len(rows) == 1
    r = rows[0]
    assert r["symbol"] == "AVAXUSDT"
    assert r["strategy"] == "RENAISSANCE"
    assert r["pattern"] == "Gartley"
    assert r["direction"] == "BULLISH"
    assert r["primed"] == 0  # bool → int
    assert r["score"] == 0.6598


def test_upsert_signal_idempotent(conn):
    payload = {
        "shadow_observed_at": "2026-04-24T18:31:32Z",
        "symbol": "AVAXUSDT",
        "strategy": "RENAISSANCE",
        "direction": "BULLISH",
    }
    upsert_signal(conn, "rid", payload)
    upsert_signal(conn, "rid", payload)
    rows = list_signals_for_run(conn, "rid")
    assert len(rows) == 1


def test_upsert_signal_requires_strategy(conn):
    """Strategy is mandatory for signals — shadow always tags one."""
    bad = {
        "shadow_observed_at": "x", "symbol": "BTC", "direction": "BULLISH",
    }
    assert upsert_signal(conn, "rid", bad) is False


# ─── Bulk + cross-run ───────────────────────────────────────────────


def test_bulk_upsert(conn):
    payloads = [
        {"ts": "t1", "symbol": "BTC", "direction": "long", "entry": 1.0},
        {"ts": "t2", "symbol": "ETH", "direction": "long", "entry": 1.0},
        {"ts": "t3", "symbol": "AVAX", "direction": "short", "entry": 1.0},
    ]
    n = upsert_trades_bulk(conn, "rid", payloads)
    assert n == 3
    assert len(list_trades_for_run(conn, "rid")) == 3


def test_signals_bulk(conn):
    payloads = [
        {"shadow_observed_at": "t1", "symbol": "BTC",
         "strategy": "S1", "direction": "BULLISH"},
        {"shadow_observed_at": "t2", "symbol": "ETH",
         "strategy": "S1", "direction": "BEARISH"},
    ]
    assert upsert_signals_bulk(conn, "rid", payloads) == 2
    assert len(list_signals_for_run(conn, "rid")) == 2


def test_runs_isolated(conn):
    """Two runs don't see each other's trades."""
    payload = {"ts": "t1", "symbol": "BTC",
               "direction": "long", "entry": 1.0}
    upsert_trade(conn, "run_A", payload)
    upsert_trade(conn, "run_B", payload)
    assert len(list_trades_for_run(conn, "run_A")) == 1
    assert len(list_trades_for_run(conn, "run_B")) == 1


def test_query_by_strategy_index_works(conn):
    """The strategy index makes 'all citadel paper trades' a fast query."""
    upsert_trade(conn, "rid", {
        "ts": "t1", "symbol": "BTC", "strategy": "citadel",
        "direction": "long", "entry": 1.0,
    })
    upsert_trade(conn, "rid", {
        "ts": "t2", "symbol": "ETH", "strategy": "jump",
        "direction": "long", "entry": 1.0,
    })
    cur = conn.execute(
        "SELECT symbol FROM live_trades WHERE strategy = ? ORDER BY ts",
        ("citadel",),
    )
    assert [r[0] for r in cur.fetchall()] == ["BTC"]
