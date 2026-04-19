"""Unit tests for PositionManager."""
import pytest
from tools.operations.paper_executor import Position
from tools.operations.paper_position_manager import PositionManager, ClosedTrade


def _pos(direction="LONG", entry=100.0, stop=98.0, target=104.0, size=1.0):
    return Position(
        id="pos_test", engine="CITADEL", symbol="BTCUSDT",
        direction=direction, entry_price=entry, stop=stop, target=target,
        size=size, notional=entry*size,
        opened_at="2026-04-19T14:05:00Z", opened_at_idx=0,
        commission_paid=entry*size*0.0004,
    )


def _bar(high, low, close, ts="2026-04-19T14:20:00Z"):
    return {"high": float(high), "low": float(low), "close": float(close),
            "time": ts}


def test_long_target_hit():
    pm = PositionManager(commission=0.0004, funding_per_8h=0.0, tick_sec=900)
    pos = _pos(direction="LONG", entry=100.0, stop=98.0, target=104.0, size=1.0)
    bars = [_bar(high=105.0, low=99.0, close=104.5)]  # hits target 104 intrabar
    closed = pm.check_exits([pos], bars)
    assert len(closed) == 1
    c: ClosedTrade = closed[0]
    assert c.exit_reason == "target"
    assert c.exit_price == 104.0
    assert c.pnl > 0


def test_long_stop_hit():
    pm = PositionManager(commission=0.0004, funding_per_8h=0.0, tick_sec=900)
    pos = _pos(direction="LONG", entry=100.0, stop=98.0, target=104.0)
    bars = [_bar(high=101.0, low=97.0, close=97.5)]
    closed = pm.check_exits([pos], bars)
    assert closed[0].exit_reason == "stop"
    assert closed[0].exit_price == 98.0
    assert closed[0].pnl < 0


def test_both_hit_same_bar_resolves_to_stop():
    pm = PositionManager(commission=0.0004, funding_per_8h=0.0, tick_sec=900)
    pos = _pos(direction="LONG", entry=100.0, stop=98.0, target=104.0)
    bars = [_bar(high=105.0, low=97.0, close=100.0)]
    closed = pm.check_exits([pos], bars)
    assert closed[0].exit_reason == "stop"


def test_short_target_hit():
    pm = PositionManager(commission=0.0004, funding_per_8h=0.0, tick_sec=900)
    pos = _pos(direction="SHORT", entry=100.0, stop=102.0, target=96.0)
    bars = [_bar(high=101.0, low=95.0, close=95.5)]
    closed = pm.check_exits([pos], bars)
    assert closed[0].exit_reason == "target"
    assert closed[0].exit_price == 96.0


def test_no_exit_marks_to_market():
    pm = PositionManager(commission=0.0004, funding_per_8h=0.0, tick_sec=900)
    pos = _pos(direction="LONG", entry=100.0, stop=98.0, target=104.0, size=2.0)
    bars = [_bar(high=102.0, low=99.0, close=101.5)]
    closed = pm.check_exits([pos], bars)
    assert closed == []
    assert pos.mtm_price == 101.5
    assert pos.unrealized_pnl == pytest.approx((101.5 - 100.0) * 2.0)
    assert pos.bars_held == 1


def test_r_multiple_computed_on_close():
    pm = PositionManager(commission=0.0004, funding_per_8h=0.0, tick_sec=900)
    # entry 100, stop 98 -> risk per unit = 2; target 104 -> reward = 4 -> R = 2
    pos = _pos(direction="LONG", entry=100.0, stop=98.0, target=104.0, size=1.0)
    bars = [_bar(high=105.0, low=99.5, close=104.5)]
    closed = pm.check_exits([pos], bars)
    assert closed[0].r_multiple == pytest.approx(2.0, rel=0.01)


def test_funding_reduces_long_pnl():
    pm = PositionManager(commission=0.0004, funding_per_8h=0.001, tick_sec=900)
    pos = _pos(direction="LONG", entry=100.0, stop=98.0, target=104.0, size=1.0)
    bars = [_bar(high=102.0, low=99.0, close=101.0)]
    pm.check_exits([pos], bars)
    # funding_delta = 100 * 0.001 * (900 / 28800) = 0.003125
    # LONG pays funding -> unrealized reduced
    assert pos.unrealized_pnl < (101.0 - 100.0) * 1.0
