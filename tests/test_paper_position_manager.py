"""PositionManager tests — backtest-parity logic (label_trade mirror).

Split into three blocks:
  * simple stop/target paths that never trigger BE/trail (tight RR)
  * BE + trailing + liquidation
  * funding accrual

Every fixture initializes ``cur_stop=stop`` and a non-triggering liq
pair (LEVERAGE=1 default) so old-style "no trailing" semantics still
work when the bar doesn't push far enough to activate BE.
"""
import pytest

from config.params import (
    TRAIL_ACTIVATE_MULT,
    TRAIL_BE_MULT,
    TRAIL_DISTANCE_MULT,
)
from tools.operations.paper_executor import Position
from tools.operations.paper_position_manager import PositionManager, ClosedTrade


def _pos(direction="LONG", entry=100.0, stop=98.0, target=104.0, size=1.0,
         liq_long=-1.0, liq_short=1e9):
    return Position(
        id="pos_test", engine="CITADEL", symbol="BTCUSDT",
        direction=direction, entry_price=entry, stop=stop, target=target,
        size=size, notional=entry * size,
        opened_at="2026-04-19T14:05:00Z", opened_at_idx=0,
        commission_paid=entry * size * 0.0004,
        cur_stop=stop, liq_long=liq_long, liq_short=liq_short,
    )


def _bar(high, low, close, ts="2026-04-19T14:20:00Z"):
    return {"high": float(high), "low": float(low), "close": float(close),
            "time": ts}


# ─── Simple stop/target (RR < BE threshold) ────────────────────────

def test_long_target_hit_before_be_triggers():
    """Target inside the BE envelope: target exits as 'target' without BE."""
    # entry 100, stop 98 -> risk 2, BE@102, target 101.5 (below BE)
    pm = PositionManager(commission=0.0004, funding_per_8h=0.0, tick_sec=900)
    pos = _pos(entry=100.0, stop=98.0, target=101.5)
    closed = pm.check_exits([pos], [_bar(high=101.8, low=99.5, close=101.6)])
    assert len(closed) == 1
    assert closed[0].exit_reason == "target"
    assert closed[0].exit_price == 101.5
    assert closed[0].pnl > 0
    assert pos.be_done is False


def test_long_stop_hit_initial():
    """Price drops under stop before ever reaching BE threshold."""
    pm = PositionManager(commission=0.0004, funding_per_8h=0.0, tick_sec=900)
    pos = _pos(entry=100.0, stop=98.0, target=104.0)
    closed = pm.check_exits([pos], [_bar(high=101.0, low=97.0, close=97.5)])
    assert closed[0].exit_reason == "stop_initial"
    assert closed[0].exit_price == 98.0
    assert closed[0].pnl < 0


def test_short_target_hit_before_be_triggers():
    pm = PositionManager(commission=0.0004, funding_per_8h=0.0, tick_sec=900)
    # entry 100, stop 102 -> risk 2, BE@98, target 98.5 (above BE)
    pos = _pos(direction="SHORT", entry=100.0, stop=102.0, target=98.5)
    closed = pm.check_exits([pos], [_bar(high=100.5, low=98.2, close=98.3)])
    assert closed[0].exit_reason == "target"
    assert closed[0].exit_price == 98.5


def test_both_hit_same_bar_when_be_disabled_resolves_to_stop():
    """Tie-break stop-wins holds when BE hasn't shifted cur_stop up."""
    pm = PositionManager(commission=0.0004, funding_per_8h=0.0, tick_sec=900)
    # RR < BE so BE doesn't fire; both levels cleared in the same bar
    pos = _pos(entry=100.0, stop=98.0, target=101.5)
    closed = pm.check_exits([pos], [_bar(high=102.0, low=97.0, close=99.0)])
    # BE fires at high>=102 (>= entry+1*risk=102) → cur_stop=100
    # Then trail check: h=102 vs entry+1.5*2=103 → NO. Stop: l=97 <= 100
    # (cur_stop moved to BE) → exit at 100 "breakeven".
    assert closed[0].exit_reason == "breakeven"
    assert closed[0].exit_price == 100.0


def test_no_exit_marks_to_market():
    pm = PositionManager(commission=0.0004, funding_per_8h=0.0, tick_sec=900)
    pos = _pos(entry=100.0, stop=98.0, target=104.0, size=2.0)
    closed = pm.check_exits([pos], [_bar(high=101.0, low=99.5, close=100.8)])
    assert closed == []
    assert pos.mtm_price == 100.8
    assert pos.unrealized_pnl == pytest.approx((100.8 - 100.0) * 2.0)
    assert pos.bars_held == 1


def test_r_multiple_on_clean_target():
    """R computed against initial stop distance, not cur_stop."""
    pm = PositionManager(commission=0.0004, funding_per_8h=0.0, tick_sec=900)
    # risk = 2, target 101.5 -> R = 0.75 (reward/risk)
    pos = _pos(entry=100.0, stop=98.0, target=101.5)
    closed = pm.check_exits([pos], [_bar(high=101.6, low=99.9, close=101.5)])
    assert closed[0].r_multiple == pytest.approx(0.75, rel=0.01)


# ─── BE + trailing + liquidation ───────────────────────────────────

def test_long_be_triggers_and_moves_cur_stop_to_entry():
    """When h >= entry + BE*risk, cur_stop moves to entry (no exit)."""
    pm = PositionManager(commission=0.0004, funding_per_8h=0.0, tick_sec=900)
    pos = _pos(entry=100.0, stop=98.0, target=110.0)  # risk 2, BE@102
    pm.check_exits([pos], [_bar(high=102.5, low=99.9, close=102.0)])
    assert pos.be_done is True
    assert pos.cur_stop == pytest.approx(100.0)  # entry
    # target 110 not hit; trail threshold 103 not hit either
    assert pos.trail_done is False


def test_long_trail_activates_and_tracks_high():
    """Trail starts once h >= entry + ACT*risk; cur_stop follows h - DST*risk."""
    pm = PositionManager(commission=0.0004, funding_per_8h=0.0, tick_sec=900)
    pos = _pos(entry=100.0, stop=98.0, target=120.0)  # risk 2, BE@102, trail@103
    # Bar 1: high 104 (activates BE + trail), low 99.9
    pm.check_exits([pos], [_bar(high=104.0, low=99.9, close=103.5)])
    assert pos.trail_done is True
    expected_stop = max(100.0, 104.0 - TRAIL_DISTANCE_MULT * 2.0)
    assert pos.cur_stop == pytest.approx(expected_stop)
    # Bar 2: higher high raises trail
    pm.check_exits([pos], [_bar(high=108.0, low=103.5, close=107.0)])
    new_expected = max(expected_stop, 108.0 - TRAIL_DISTANCE_MULT * 2.0)
    assert pos.cur_stop == pytest.approx(new_expected)


def test_long_trailing_stop_exit_emits_trailing_reason():
    pm = PositionManager(commission=0.0004, funding_per_8h=0.0, tick_sec=900)
    pos = _pos(entry=100.0, stop=98.0, target=120.0)
    # Bar 1: push to 108 (BE + trail activate, cur_stop = 108 - 0.3*2 = 107.4).
    # Low stays above cur_stop so this bar does not exit — label_trade
    # checks lo<=cur_stop AFTER applying the trail update on the same bar.
    pm.check_exits([pos], [_bar(high=108.0, low=107.5, close=107.7)])
    assert pos.trail_done is True
    cur_stop = pos.cur_stop
    # Bar 2: no new high (so trail stays at 107.4), pullback below cur_stop.
    closed = pm.check_exits(
        [pos], [_bar(high=107.5, low=cur_stop - 0.5, close=cur_stop - 0.2)])
    assert closed[0].exit_reason == "trailing"
    assert closed[0].exit_price == pytest.approx(cur_stop)


def test_long_liquidation_fires_before_stop_when_lev_gt_1():
    """With liq_long set, a low into liq_price produces 'liquidation'."""
    pm = PositionManager(commission=0.0004, funding_per_8h=0.0, tick_sec=900)
    # Manually simulate LEVERAGE=10 on entry 100: liq ≈ 90.5
    pos = _pos(entry=100.0, stop=98.0, target=110.0, liq_long=90.5)
    closed = pm.check_exits([pos], [_bar(high=100.5, low=89.0, close=92.0)])
    # Even though low also breaches the initial stop, liquidation wins
    assert closed[0].exit_reason == "liquidation"
    assert closed[0].exit_price == 90.5


def test_short_be_and_trail_mirror_long():
    pm = PositionManager(commission=0.0004, funding_per_8h=0.0, tick_sec=900)
    pos = _pos(direction="SHORT", entry=100.0, stop=102.0, target=80.0)
    # risk 2, BE@98, trail@97
    pm.check_exits([pos], [_bar(high=101.0, low=96.0, close=96.5)])
    assert pos.be_done is True
    assert pos.trail_done is True
    expected_stop = min(100.0, 96.0 + TRAIL_DISTANCE_MULT * 2.0)
    assert pos.cur_stop == pytest.approx(expected_stop)


def test_direction_bullish_bearish_normalized_via_executor(monkeypatch):
    """Executor canonicalizes BULLISH→LONG; PM math stays correct."""
    from tools.operations.paper_executor import PaperExecutor

    ex = PaperExecutor(slippage=0.0, spread=0.0, commission=0.0,
                       account_size=10_000.0, base_account_size=10_000.0)
    pos = ex.open({
        "direction": "BULLISH",
        "entry": 100.0, "stop": 98.0, "target": 101.5,
        "symbol": "XRPUSDT", "strategy": "JUMP", "size": 1.0,
    }, opened_at_idx=0, opened_at_iso="2026-04-20T12:00:00Z")
    assert pos.direction == "LONG"
    # PnL must be positive on price rise
    pm = PositionManager(commission=0.0, funding_per_8h=0.0, tick_sec=900)
    closed = pm.check_exits([pos], [_bar(high=101.6, low=99.9, close=101.5)])
    assert closed[0].pnl > 0


# ─── Funding ───────────────────────────────────────────────────────

def test_funding_reduces_long_pnl():
    pm = PositionManager(commission=0.0004, funding_per_8h=0.001, tick_sec=900)
    pos = _pos(entry=100.0, stop=98.0, target=120.0)  # no exit on this bar
    pm.check_exits([pos], [_bar(high=101.5, low=99.5, close=101.0)])
    assert pos.funding_accumulated > 0
    assert pos.unrealized_pnl < (101.0 - 100.0) * 1.0


def test_funding_accumulates_across_multiple_ticks():
    pm = PositionManager(commission=0.0004, funding_per_8h=0.001, tick_sec=900)
    pos = _pos(entry=100.0, stop=98.0, target=120.0, size=10.0)
    pm.check_exits([pos], [_bar(high=100.8, low=99.5, close=100.5)])
    funding_after_1 = pos.funding_accumulated
    pm.check_exits([pos], [_bar(high=101.2, low=100.2, close=101.0)])
    assert pos.funding_accumulated == pytest.approx(funding_after_1 * 2, rel=0.01)
    # Now close via BE path: push to ≥102 and let BE bite, then retreat.
    pm.check_exits([pos], [_bar(high=102.5, low=100.5, close=101.5)])  # BE triggers
    closed = pm.check_exits(
        [pos], [_bar(high=101.5, low=99.5, close=99.8)])  # hits cur_stop=100 (BE)
    assert len(closed) == 1
    c = closed[0]
    assert c.funding_paid > 0  # LONG paid funding
    expected_without_funding = c.pnl - c.entry_commission - c.exit_commission
    assert c.pnl_after_fees == pytest.approx(
        expected_without_funding - c.funding_paid, rel=0.001)


def test_funding_short_receives_credit():
    pm = PositionManager(commission=0.0004, funding_per_8h=0.001, tick_sec=900)
    pos = _pos(direction="SHORT", entry=100.0, stop=102.0, target=80.0, size=10.0)
    pm.check_exits([pos], [_bar(high=100.5, low=99.5, close=100.0)])
    pm.check_exits([pos], [_bar(high=100.2, low=99.3, close=99.8)])
    assert pos.funding_accumulated < 0  # SHORT receives credit
