"""Tests for cockpit-shaped payload normalisation in db_live_trades.

The cockpit /v1/runs/{id}/trades endpoint emits trades with
'entry_at' / 'exit_at' / 'pnl_after_fees', not the JSONL canonical
'ts' / 'exit_ts' / 'pnl_usd'. Without this aliasing, backfill_live_trades
silently drops every cockpit-fetched paper trade (2026-04-25 incident:
2 XRP trades on VPS, 0 in local live_trades after --from-vps --apply).
"""
from __future__ import annotations

import sqlite3
import pytest


@pytest.fixture
def conn(tmp_path):
    # Distinct file path per test avoids collision with the
    # _MIGRATED_DBS cache (which keys :memory: connections by id(),
    # an address Python may recycle between tests).
    db_path = tmp_path / "test.db"
    c = sqlite3.connect(str(db_path))
    yield c
    c.close()


def _cockpit_trade_payload(**overrides) -> dict:
    """Mirrors the actual /v1/runs/{id}/trades response shape."""
    base = {
        "id": "pos_000001",
        "engine": "JUMP",
        "symbol": "XRPUSDT",
        "direction": "LONG",
        "entry_price": 1.4285,
        "exit_price": 1.4239,
        "stop": 1.4239,
        "target": 1.4407,
        "size": 3100.94,
        "entry_at": "2026-04-25T16:16:40.927169+00:00",
        "exit_at": "2026-04-25T16:30:00",
        "exit_reason": "stop_initial",
        "pnl": -14.31,
        "pnl_after_fees": -17.85,
        "r_multiple": -1.0,
        "bars_held": 0,
        "primed": False,
    }
    base.update(overrides)
    return base


def test_cockpit_paper_trade_persists_with_entry_at_as_ts(conn):
    """Cockpit payload (entry_at, exit_at, pnl_after_fees) must persist."""
    from core.ops.db_live_trades import upsert_trade, list_trades_for_run

    payload = _cockpit_trade_payload()
    inserted = upsert_trade(conn, "test-run-1", payload)
    assert inserted, (
        "cockpit-shaped payload was rejected — likely 'entry_at' "
        "is not aliased to 'ts'"
    )

    rows = list_trades_for_run(conn, "test-run-1")
    assert len(rows) == 1
    row = rows[0]
    assert row["ts"] == "2026-04-25T16:16:40.927169+00:00"
    assert row["symbol"] == "XRPUSDT"
    assert row["direction"] == "LONG"
    assert row["entry"] == pytest.approx(1.4285)
    assert row["exit"] == pytest.approx(1.4239)
    assert row["exit_ts"] == "2026-04-25T16:30:00"
    assert row["exit_reason"] == "stop_initial"


def test_cockpit_pnl_after_fees_preferred_over_gross_pnl(conn):
    """pnl_after_fees is the net value the user expects. Prefer it."""
    from core.ops.db_live_trades import upsert_trade, list_trades_for_run

    payload = _cockpit_trade_payload(pnl=-14.31, pnl_after_fees=-17.85)
    upsert_trade(conn, "test-run-2", payload)
    rows = list_trades_for_run(conn, "test-run-2")
    assert len(rows) == 1
    assert rows[0]["pnl_usd"] == pytest.approx(-17.85), (
        "pnl_usd must reflect the after-fees value, not gross pnl"
    )


def test_cockpit_size_persists_into_size_usd(conn):
    """Cockpit emits raw 'size' (units). Persisted as size_usd alias."""
    from core.ops.db_live_trades import upsert_trade, list_trades_for_run

    payload = _cockpit_trade_payload()
    upsert_trade(conn, "test-run-3", payload)
    rows = list_trades_for_run(conn, "test-run-3")
    # If notional is provided cockpit-side it wins; otherwise raw size persists.
    assert rows[0]["size_usd"] is not None


def test_cockpit_engine_field_aliases_to_strategy(conn):
    """Cockpit /trades emits 'engine' not 'strategy'. Persist as strategy."""
    from core.ops.db_live_trades import upsert_trade, list_trades_for_run

    payload = _cockpit_trade_payload(engine="JUMP")
    upsert_trade(conn, "test-run-eng", payload)
    rows = list_trades_for_run(conn, "test-run-eng")
    assert len(rows) == 1
    assert rows[0]["strategy"] == "JUMP", (
        "cockpit 'engine' must map to live_trades.strategy column"
    )


def test_idempotent_reupsert_of_cockpit_payload(conn):
    """Re-running backfill on same cockpit row produces 1 row, not 2."""
    from core.ops.db_live_trades import upsert_trade, list_trades_for_run

    payload = _cockpit_trade_payload()
    assert upsert_trade(conn, "test-run-4", payload)
    upsert_trade(conn, "test-run-4", payload)
    rows = list_trades_for_run(conn, "test-run-4")
    assert len(rows) == 1
