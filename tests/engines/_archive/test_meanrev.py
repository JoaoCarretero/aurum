"""Unit tests for engines/meanrev.py."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engines.meanrev import MeanRevParams, decide_entry, simulate_trade


def test_decide_entry_long_fires_on_extreme_neg_deviation_and_oversold_rsi():
    prev = pd.Series({"deviation": -3.0, "open": 99.0, "close": 98.0})
    row = pd.Series({"deviation": -2.5, "rsi": 25.0, "atr_pct": 0.5, "open": 98.0, "close": 99.0})
    assert decide_entry(row, MeanRevParams(), prev_row=prev) == +1


def test_decide_entry_short_fires_on_extreme_pos_deviation_and_overbought_rsi():
    prev = pd.Series({"deviation": 3.0, "open": 101.0, "close": 102.0})
    row = pd.Series({"deviation": 2.5, "rsi": 75.0, "atr_pct": 0.5, "open": 102.0, "close": 101.0})
    assert decide_entry(row, MeanRevParams(), prev_row=prev) == -1


def test_decide_entry_rsi_gate_blocks_long():
    prev = pd.Series({"deviation": -3.5, "open": 99.0, "close": 98.0})
    row = pd.Series({"deviation": -3.0, "rsi": 50.0, "atr_pct": 0.5, "open": 98.0, "close": 99.0})
    assert decide_entry(row, MeanRevParams(), prev_row=prev) == 0


def test_decide_entry_rsi_gate_blocks_short():
    prev = pd.Series({"deviation": 3.5, "open": 101.0, "close": 102.0})
    row = pd.Series({"deviation": 3.0, "rsi": 50.0, "atr_pct": 0.5, "open": 102.0, "close": 101.0})
    assert decide_entry(row, MeanRevParams(), prev_row=prev) == 0


def test_decide_entry_deviation_gate_blocks_moderate():
    prev = pd.Series({"deviation": -1.0, "open": 99.0, "close": 98.0})
    row = pd.Series({"deviation": -0.5, "rsi": 20.0, "atr_pct": 0.5, "open": 98.0, "close": 99.0})
    assert decide_entry(row, MeanRevParams(), prev_row=prev) == 0


def test_decide_entry_nan_values_return_zero():
    prev = pd.Series({"deviation": -3.5, "open": 99.0, "close": 98.0})
    row = pd.Series({"deviation": np.nan, "rsi": 20.0, "atr_pct": 0.5, "open": 98.0, "close": 99.0})
    assert decide_entry(row, MeanRevParams(), prev_row=prev) == 0
    row = pd.Series({"deviation": -3.0, "rsi": np.nan, "atr_pct": 0.5, "open": 98.0, "close": 99.0})
    assert decide_entry(row, MeanRevParams(), prev_row=prev) == 0


def test_decide_entry_respects_custom_thresholds():
    prev = pd.Series({"deviation": -2.0, "open": 99.0, "close": 98.0})
    row = pd.Series({"deviation": -1.5, "rsi": 35.0, "atr_pct": 0.5, "open": 98.0, "close": 99.0})
    assert decide_entry(row, MeanRevParams(), prev_row=prev) == 0  # default too strict
    relaxed = MeanRevParams(deviation_enter=1.0, rsi_long_max=40.0)
    assert decide_entry(row, relaxed, prev_row=prev) == +1


def test_decide_entry_touch_mode_skips_reversal_confirmation():
    row = pd.Series({"deviation": -2.5, "rsi": 25.0, "atr_pct": 0.5, "open": 99.0, "close": 98.0})
    params = MeanRevParams(entry_mode="touch")
    assert decide_entry(row, params, prev_row=None) == +1


def test_decide_entry_reversal_bar_requires_bounce():
    prev = pd.Series({"deviation": -3.0, "open": 99.0, "close": 98.0})
    row = pd.Series({"deviation": -2.7, "rsi": 20.0, "atr_pct": 0.5, "open": 99.0, "close": 98.0})
    assert decide_entry(row, MeanRevParams(), prev_row=prev) == 0


def test_decide_entry_wick_reclaim_long_requires_intrabar_flush_and_bounce():
    row = pd.Series({
        "deviation": -1.2,
        "low_deviation": -2.8,
        "rsi": 22.0,
        "atr_pct": 0.5,
        "atr": 2.0,
        "low": 95.0,
        "high": 100.0,
        "open": 97.0,
        "close": 98.5,
    })
    params = MeanRevParams(entry_mode="wick_reclaim", reclaim_atr_min=1.5)
    assert decide_entry(row, params, prev_row=None) == +1


def test_decide_entry_extreme_reclaim_short_requires_high_overshoot_and_close_back_inside():
    row = pd.Series({
        "deviation": 0.8,
        "high_deviation": 2.7,
        "rsi": 78.0,
        "atr_pct": 0.5,
        "open": 102.0,
        "close": 101.0,
    })
    params = MeanRevParams(entry_mode="extreme_reclaim", reclaim_deviation_exit=1.0)
    assert decide_entry(row, params, prev_row=None) == -1


def _fake_df(prices: list[float], atr: float = 1.0, ema50: float = 100.0) -> pd.DataFrame:
    return pd.DataFrame({
        "open": prices,
        "high": [p + 0.5 for p in prices],
        "low": [p - 0.5 for p in prices],
        "close": prices,
        "atr": [atr] * len(prices),
        "ema50": [ema50] * len(prices),
    })


def test_simulate_trade_long_hits_target():
    # Enter long at price 98 (below ema50=100), target 100, stop 94 (2*ATR below)
    # Price rallies to 100.5 on bar 3 — hits target
    df = _fake_df([98.0, 98.0, 99.0, 100.5, 101.0], atr=2.0, ema50=100.0)
    trade = simulate_trade(df, entry_idx=0, direction=+1, params=MeanRevParams())
    assert trade is not None
    assert trade["reason"] == "tp"
    assert trade["net_pnl_pct"] > 0


def test_simulate_trade_long_hits_stop():
    # Enter long at 98, stop 94. Price crashes to 93 on bar 2
    df = _fake_df([98.0, 98.0, 93.0, 92.0, 91.0], atr=2.0, ema50=100.0)
    trade = simulate_trade(df, entry_idx=0, direction=+1, params=MeanRevParams())
    assert trade is not None
    assert trade["reason"] == "sl"
    assert trade["net_pnl_pct"] < 0


def test_simulate_trade_time_stop_closes_open_position():
    # Enter long at 98, never hits target or stop, time_stop_bars=3
    df = _fake_df([98.0, 98.5, 99.0, 99.1, 99.2, 99.1], atr=2.0, ema50=100.0)
    params = MeanRevParams(time_stop_bars=3)
    trade = simulate_trade(df, entry_idx=0, direction=+1, params=params)
    assert trade is not None
    assert trade["reason"] == "time_stop"


def test_simulate_trade_scale_in_improves_average_entry():
    df = _fake_df([98.0, 98.0, 96.0, 99.0, 100.5, 101.0], atr=2.0, ema50=100.0)
    params = MeanRevParams(scale_in_levels=2, scale_in_step_atr=0.5)
    trade = simulate_trade(df, entry_idx=0, direction=+1, params=params)
    assert trade is not None
    assert trade["fills"] == 2
    assert trade["entry_initial"] == 98.0
    assert trade["entry"] < trade["entry_initial"]
    assert trade["reason"] == "tp"


def test_simulate_trade_partial_revert_target_is_closer_than_anchor():
    df = _fake_df([98.0, 98.0, 99.0, 99.5, 100.5], atr=2.0, ema50=100.0)
    params = MeanRevParams(target_mode="partial_revert", target_reclaim_frac=0.5)
    trade = simulate_trade(df, entry_idx=0, direction=+1, params=params)
    assert trade is not None
    assert trade["target"] == 99.0
    assert trade["reason"] == "tp"


def test_simulate_trade_costs_reduce_pnl():
    # TP hit; compare raw pnl_pct vs net_pnl_pct
    df = _fake_df([98.0, 98.0, 100.5, 101.0], atr=2.0, ema50=100.0)
    trade = simulate_trade(df, entry_idx=0, direction=+1, params=MeanRevParams())
    assert trade["pnl_pct"] > trade["net_pnl_pct"]  # costs applied


def test_simulate_trade_returns_none_at_last_bar():
    df = _fake_df([98.0, 98.0], atr=2.0, ema50=100.0)
    # entry_idx=1 means entry bar is last — no next bar for open
    trade = simulate_trade(df, entry_idx=1, direction=+1, params=MeanRevParams())
    assert trade is None


def test_meanrev_params_defaults_are_sane():
    p = MeanRevParams()
    assert p.deviation_enter > 0
    assert 0 < p.rsi_long_max < 50
    assert 50 < p.rsi_short_min < 100
    assert p.atr_stop_mult > 0
    assert p.time_stop_bars > 0
    assert 0 < p.risk_per_trade < 1
