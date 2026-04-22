"""Unit tests for SimpleArbEngine.

Covers: start/stop lifecycle, tick open/close cycle, funding accrual,
kill switch, filters (min_apr, min_vol), persistence, snapshot shape.

The engine is pure: no network, no threads. Tests inject synthetic opps
and control time via `now` parameter to tick().
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.arb.engine import SimpleArbEngine


# ── Fixtures ─────────────────────────────────────────────────────────


def _opp(symbol="BTCUSDT", net_apr=50.0, short_venue="binance",
         long_venue="bybit", mark_price=45000.0, volume=5_000_000.0) -> dict:
    """Synthetic FUNDING opportunity matching arb_pairs() output shape."""
    return {
        "symbol": symbol,
        "short_venue": short_venue,
        "short_venue_type": "CEX",
        "short_rate": 0.0003,
        "short_interval_h": 8.0,
        "short_apr": net_apr / 2 + 10,
        "long_venue": long_venue,
        "long_venue_type": "CEX",
        "long_rate": -0.0001,
        "long_interval_h": 8.0,
        "long_apr": -(net_apr / 2 - 10),
        "net_apr": net_apr,
        "mark_price": mark_price,
        "volume_short": volume,
        "volume_long": volume,
    }


@pytest.fixture
def tmp_state(tmp_path) -> Path:
    return tmp_path / "state.json"


# ── Lifecycle ────────────────────────────────────────────────────────


def test_engine_stopped_by_default(tmp_state):
    e = SimpleArbEngine(state_path=tmp_state)
    assert e.running is False
    assert e.positions == []
    assert e.closed == []


def test_start_initializes_state(tmp_state):
    e = SimpleArbEngine(state_path=tmp_state, account=5000.0)
    e.start(mode="paper")
    assert e.running is True
    assert e.mode == "paper"
    assert e.account == 5000.0
    assert e.peak == 5000.0
    assert e.killed is False


def test_stop_persists_state(tmp_state):
    e = SimpleArbEngine(state_path=tmp_state)
    e.start("paper")
    e.stop()
    assert e.running is False
    assert tmp_state.exists()
    raw = json.loads(tmp_state.read_text(encoding="utf-8"))
    assert raw["mode"] == "paper"
    assert raw["account"] == e.account


def test_start_twice_is_idempotent(tmp_state):
    e = SimpleArbEngine(state_path=tmp_state)
    e.start("paper")
    pos_count_before = len(e.positions)
    e.start("paper")  # should not reset
    assert e.running is True
    assert len(e.positions) == pos_count_before


# ── Tick: opening positions ──────────────────────────────────────────


def test_tick_opens_top_scoring_opp(tmp_state):
    e = SimpleArbEngine(state_path=tmp_state, max_pos=3, size_usd=1000.0,
                        min_apr=20.0, min_vol=1_000_000.0)
    e.start("paper")
    opps = [
        _opp(symbol="BTCUSDT", net_apr=50.0),
        _opp(symbol="ETHUSDT", net_apr=80.0),  # best
        _opp(symbol="SOLUSDT", net_apr=30.0),
    ]
    e.tick(opps, now=1000.0)
    assert len(e.positions) == 3
    symbols_opened = {p["symbol"] for p in e.positions}
    assert "ETHUSDT" in symbols_opened


def test_tick_respects_max_positions(tmp_state):
    e = SimpleArbEngine(state_path=tmp_state, max_pos=2, size_usd=1000.0,
                        min_apr=20.0, min_vol=1_000_000.0)
    e.start("paper")
    opps = [_opp(symbol=f"COIN{i}USDT", net_apr=50.0) for i in range(5)]
    e.tick(opps, now=1000.0)
    assert len(e.positions) == 2


def test_tick_min_apr_filter(tmp_state):
    e = SimpleArbEngine(state_path=tmp_state, min_apr=40.0, min_vol=1_000.0)
    e.start("paper")
    opps = [
        _opp(symbol="LOW1", net_apr=10.0),
        _opp(symbol="LOW2", net_apr=20.0),
        _opp(symbol="HIGH", net_apr=100.0),
    ]
    e.tick(opps, now=1000.0)
    syms = {p["symbol"] for p in e.positions}
    assert syms == {"HIGH"}


def test_tick_min_volume_filter(tmp_state):
    e = SimpleArbEngine(state_path=tmp_state, min_apr=20.0,
                        min_vol=2_000_000.0)
    e.start("paper")
    opps = [
        _opp(symbol="LOWVOL", net_apr=80.0, volume=500_000.0),
        _opp(symbol="HIGHVOL", net_apr=50.0, volume=5_000_000.0),
    ]
    e.tick(opps, now=1000.0)
    syms = {p["symbol"] for p in e.positions}
    assert syms == {"HIGHVOL"}


def test_tick_skips_already_open_symbol(tmp_state):
    e = SimpleArbEngine(state_path=tmp_state, max_pos=5, min_apr=10.0,
                        min_vol=1_000.0)
    e.start("paper")
    o = _opp(symbol="BTCUSDT", net_apr=50.0)
    e.tick([o], now=1000.0)
    assert len(e.positions) == 1
    # Same symbol offered again — should NOT open a 2nd position for it
    e.tick([o, _opp(symbol="ETHUSDT", net_apr=60.0)], now=1001.0)
    assert len(e.positions) == 2
    assert {p["symbol"] for p in e.positions} == {"BTCUSDT", "ETHUSDT"}


# ── Tick: funding accrual + exits ────────────────────────────────────


def test_tick_accrues_funding_over_time(tmp_state):
    e = SimpleArbEngine(state_path=tmp_state, size_usd=1000.0,
                        min_apr=10.0, min_vol=1_000.0,
                        entry_fee_bps=0.0, slippage_bps=0.0)
    e.start("paper")
    opp = _opp(symbol="BTCUSDT", net_apr=365.0)  # 365% APR = 1% per day
    e.tick([opp], now=0.0)
    assert len(e.positions) == 1
    pos_before = e.positions[0]
    fund_start = pos_before["funding_accrued"]
    # Advance 24 hours — with 365% APR on $1000, expect ~$10 accrual
    e.tick([opp], now=24 * 3600.0)
    pos_after = e.positions[0]
    accrued = pos_after["funding_accrued"] - fund_start
    # 365% / 365 = 1% per day of size_usd $1000 = $10
    assert 9.5 < accrued < 10.5, f"expected ~$10 accrual, got ${accrued:.2f}"


def test_tick_closes_on_max_hold(tmp_state):
    e = SimpleArbEngine(state_path=tmp_state, max_hold_h=24.0,
                        min_apr=10.0, min_vol=1_000.0)
    e.start("paper")
    opp = _opp(symbol="BTCUSDT", net_apr=50.0)
    e.tick([opp], now=0.0)
    assert len(e.positions) == 1
    # Advance past max_hold
    e.tick([opp], now=25 * 3600.0)
    assert len(e.positions) == 0
    assert len(e.closed) == 1
    assert e.closed[0]["exit_reason"] == "max_hold"


def test_tick_closes_on_decay(tmp_state):
    e = SimpleArbEngine(state_path=tmp_state, exit_decay_ratio=0.30,
                        min_apr=10.0, min_vol=1_000.0)
    e.start("paper")
    opp_strong = _opp(symbol="BTCUSDT", net_apr=100.0)
    e.tick([opp_strong], now=0.0)
    assert len(e.positions) == 1
    # Refresh with much weaker spread — decay = 20/100 = 0.20 < 0.30 threshold
    opp_weak = _opp(symbol="BTCUSDT", net_apr=20.0)
    e.tick([opp_weak], now=3600.0)
    assert len(e.positions) == 0
    assert len(e.closed) == 1
    assert e.closed[0]["exit_reason"] == "decay"


def test_tick_closes_on_flip(tmp_state):
    e = SimpleArbEngine(state_path=tmp_state, min_apr=10.0, min_vol=1_000.0)
    e.start("paper")
    opp_pos = _opp(symbol="BTCUSDT", net_apr=50.0)
    e.tick([opp_pos], now=0.0)
    # Spread flips direction — engine exits
    opp_neg = _opp(symbol="BTCUSDT", net_apr=-30.0)
    e.tick([opp_neg], now=3600.0)
    assert len(e.positions) == 0
    assert e.closed[-1]["exit_reason"] == "flip"


# ── Risk gates ───────────────────────────────────────────────────────


def test_kill_switch_blocks_new_opens(tmp_state):
    e = SimpleArbEngine(state_path=tmp_state, min_apr=10.0, min_vol=1_000.0,
                        kill_dd_pct=5.0, account=1000.0)
    e.start("paper")
    e.account = 900.0  # simulate 10% drawdown
    e.tick([_opp(symbol="BTCUSDT", net_apr=50.0)], now=0.0)
    assert e.killed is True
    assert len(e.positions) == 0


def test_killed_engine_closes_existing_positions(tmp_state):
    e = SimpleArbEngine(state_path=tmp_state, min_apr=10.0, min_vol=1_000.0,
                        kill_dd_pct=5.0, account=1000.0)
    e.start("paper")
    e.tick([_opp(symbol="BTCUSDT", net_apr=50.0)], now=0.0)
    assert len(e.positions) == 1
    # Trigger kill switch manually on next tick
    e.account = 900.0
    e.tick([], now=3600.0)
    assert e.killed is True
    # Kill switch should force-close all open positions
    assert len(e.positions) == 0
    assert e.closed[-1]["exit_reason"] == "kill"


# ── Snapshot + persistence ───────────────────────────────────────────


def test_snapshot_has_expected_fields(tmp_state):
    e = SimpleArbEngine(state_path=tmp_state, min_apr=10.0, min_vol=1_000.0)
    e.start("paper")
    e.tick([_opp(symbol="BTCUSDT", net_apr=50.0)], now=0.0)
    snap = e.snapshot()
    for k in ("mode", "running", "account", "peak", "drawdown_pct",
              "realized_pnl", "unrealized_pnl", "killed", "losses_streak",
              "trades_count", "positions", "exposure_usd", "ts"):
        assert k in snap, f"snapshot missing field: {k}"
    assert snap["running"] is True
    assert snap["mode"] == "paper"
    assert snap["trades_count"] == 1


def test_persistence_roundtrip(tmp_state):
    e = SimpleArbEngine(state_path=tmp_state, min_apr=10.0, min_vol=1_000.0)
    e.start("paper")
    e.tick([_opp(symbol="BTCUSDT", net_apr=50.0)], now=1000.0)
    e.tick([_opp(symbol="BTCUSDT", net_apr=50.0)], now=2000.0)
    e.stop()

    loaded = SimpleArbEngine.load(tmp_state)
    assert loaded.account == e.account
    assert loaded.peak == e.peak
    assert len(loaded.positions) == len(e.positions)
    assert len(loaded.closed) == len(e.closed)


def test_stop_closes_all_open_positions(tmp_state):
    e = SimpleArbEngine(state_path=tmp_state, min_apr=10.0, min_vol=1_000.0,
                        max_pos=3)
    e.start("paper")
    opps = [_opp(symbol=f"COIN{i}USDT", net_apr=50.0) for i in range(3)]
    e.tick(opps, now=0.0)
    assert len(e.positions) == 3
    e.stop()
    assert len(e.positions) == 0
    for c in e.closed:
        assert c["exit_reason"] == "manual"


# ── Empty tick edge cases ────────────────────────────────────────────


def test_tick_without_running_is_noop(tmp_state):
    e = SimpleArbEngine(state_path=tmp_state)
    e.tick([_opp(symbol="BTC")], now=0.0)
    assert len(e.positions) == 0
    assert e.running is False


def test_tick_with_empty_opps(tmp_state):
    e = SimpleArbEngine(state_path=tmp_state, min_apr=10.0, min_vol=1_000.0)
    e.start("paper")
    e.tick([], now=0.0)
    assert len(e.positions) == 0
    # Subsequent non-empty tick should still work
    e.tick([_opp(symbol="BTC", net_apr=50.0)], now=1000.0)
    assert len(e.positions) == 1
