"""Tests for core/ops/db_live_trades + migration_002."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from core.ops.db_live_trades import (
    ensure_schema,
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


def test_ensure_schema_creates_tables_on_plain_connection(tmp_path: Path):
    db = tmp_path / "plain.db"
    c = sqlite3.connect(str(db))
    ensure_schema(c)
    tables = {r[0] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    c.close()
    assert "live_trades" in tables
    assert "live_signals" in tables


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
        "exit_at": "2026-04-25T11:00:00Z",
        "notional": 900.0,
        "size": 0.3,
        "pnl": 1.67,  # legacy alias
    }
    upsert_trade(conn, "rid_1", payload)
    rows = list_trades_for_run(conn, "rid_1")
    assert rows[0]["entry"] == 3000.0
    assert rows[0]["exit"] == 2950.0
    assert rows[0]["exit_ts"] == "2026-04-25T11:00:00Z"
    assert rows[0]["pnl_usd"] == 1.67
    assert rows[0]["size_usd"] == 900.0
    extras = json.loads(rows[0]["details_json"])
    assert extras["size"] == 0.3


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


# ─── Round-trip / details_json preservation ─────────────────────────


def test_upsert_trade_preserves_existing_details_json_on_round_trip(conn):
    """sync_vps_db reads a row and re-upserts it; details_json must stay
    canonical (single JSON encoding), not get double-wrapped into
    {"details_json": "<original>"}.

    Regression: 2026-04-25 paper trades XRPUSDT/JUMP arrived locally
    double-encoded because _norm_trade fed `details_json` (already a
    string) into `extras` and re-serialized it.
    """
    original_details = json.dumps({
        "id": "pos_000001", "engine": "JUMP", "bars_held": 0,
        "primed": False, "pnl_after_fees": -17.85,
    })
    payload = {
        "ts": "2026-04-25T16:16:40Z", "symbol": "XRPUSDT",
        "direction": "LONG", "strategy": "JUMP",
        "entry": 1.428513, "exit": 1.4239, "pnl_usd": -17.85,
        "details_json": original_details,
    }
    upsert_trade(conn, "rid_round", payload)
    rows = list_trades_for_run(conn, "rid_round")
    assert len(rows) == 1
    raw = rows[0]["details_json"]
    parsed = json.loads(raw)
    # Must NOT be {"details_json": "..."} (double-wrap)
    assert "details_json" not in parsed, \
        f"double-wrapped details_json detected: {parsed!r}"
    # Must preserve the original keys
    assert parsed["id"] == "pos_000001"
    assert parsed["engine"] == "JUMP"
    assert parsed["bars_held"] == 0


def test_upsert_signal_preserves_existing_details_json_on_round_trip(conn):
    """Same regression but for signals — sync_vps_db round-trips signals too."""
    original_details = json.dumps({
        "trade_type": "ORDER-FLOW", "struct": "DOWN", "cascade_n": 0,
    })
    payload = {
        "observed_at": "2026-04-21T23:30:19Z",
        "symbol": "SANDUSDT", "strategy": "JUMP", "direction": "BEARISH",
        "details_json": original_details,
    }
    upsert_signal(conn, "rid_sig_round", payload)
    rows = list_signals_for_run(conn, "rid_sig_round")
    assert len(rows) == 1
    parsed = json.loads(rows[0]["details_json"])
    assert "details_json" not in parsed, \
        f"double-wrapped details_json detected: {parsed!r}"
    assert parsed["trade_type"] == "ORDER-FLOW"
    assert parsed["cascade_n"] == 0


def test_upsert_trade_merges_existing_details_json_with_new_extras(conn):
    """If both incoming details_json AND novel extras exist, both must
    survive — no silent data loss in either direction."""
    original = json.dumps({"id": "pos_X", "engine": "JUMP"})
    payload = {
        "ts": "ts_x", "symbol": "BTCUSDT",
        "direction": "long", "entry": 1.0,
        "details_json": original,
        "novel_field": "added_after_first_write",
    }
    upsert_trade(conn, "rid_merge", payload)
    rows = list_trades_for_run(conn, "rid_merge")
    parsed = json.loads(rows[0]["details_json"])
    assert parsed.get("id") == "pos_X"
    assert parsed.get("engine") == "JUMP"
    assert parsed.get("novel_field") == "added_after_first_write"


def test_upsert_signal_coerces_pandas_timestamp(conn):
    """millennium_shadow passes the engine's raw `t["timestamp"]` straight
    through; for pandas-backed engines that's a `pd.Timestamp` object, not
    a string. Pre-fix this raised `Error binding parameter 3: type
    'Timestamp' is not supported` on VPS, silently dropping every shadow
    signal from live_signals (only WARNING, non-fatal). Coerce to ISO str.
    """
    import pandas as pd
    payload = {
        "shadow_observed_at": "2026-04-25T18:29:37Z",
        "timestamp": pd.Timestamp("2026-04-25 18:00:00"),
        "symbol": "XRPUSDT", "strategy": "JUMP", "direction": "BEARISH",
        "entry": 1.42, "stop": 1.427, "target": 1.4,
    }
    inserted = upsert_signal(conn, "rid_ts", payload)
    assert inserted is True, "should not silently drop on Timestamp"
    rows = list_signals_for_run(conn, "rid_ts")
    assert len(rows) == 1
    assert isinstance(rows[0]["signal_ts"], str)
    assert "2026-04-25" in rows[0]["signal_ts"]


def test_upsert_trade_coerces_pandas_timestamp(conn):
    """Same coercion guard for trade ts/exit_ts (paper engines use df-index
    Timestamps too)."""
    import pandas as pd
    payload = {
        "ts": pd.Timestamp("2026-04-25T16:16:40Z"),
        "exit_ts": pd.Timestamp("2026-04-25T16:30:00Z"),
        "symbol": "XRPUSDT", "direction": "LONG", "entry": 1.428,
        "exit": 1.4239, "pnl_usd": -17.85,
    }
    inserted = upsert_trade(conn, "rid_ts2", payload)
    assert inserted is True
    rows = list_trades_for_run(conn, "rid_ts2")
    assert len(rows) == 1
    assert isinstance(rows[0]["ts"], str)
    assert isinstance(rows[0]["exit_ts"], str)


def test_upsert_trade_idempotent_round_trip_preserves_details(conn):
    """Insert, read back, re-upsert — details_json must stabilise after
    one cycle (not grow nesting on every sync)."""
    payload = {
        "ts": "ts_a", "symbol": "BTCUSDT", "direction": "long",
        "entry": 1.0, "details_json": json.dumps({"k": "v"}),
    }
    upsert_trade(conn, "rid_stab", payload)
    rows1 = list_trades_for_run(conn, "rid_stab")
    # Simulate sync_vps_db: strip id/run_id and re-upsert
    re_payload = {k: v for k, v in rows1[0].items()
                  if k not in ("id", "run_id") and v is not None}
    upsert_trade(conn, "rid_stab", re_payload)
    rows2 = list_trades_for_run(conn, "rid_stab")
    # Two cycles must converge
    assert rows1[0]["details_json"] == rows2[0]["details_json"]
    parsed = json.loads(rows2[0]["details_json"])
    assert parsed == {"k": "v"}
