"""Unit tests for engines/meanrev.py."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engines.meanrev import MeanRevParams, decide_entry, simulate_trade


def test_decide_entry_long_fires_on_extreme_neg_deviation_and_oversold_rsi():
    row = pd.Series({"deviation": -2.5, "rsi": 25.0, "atr_pct": 0.5})
    assert decide_entry(row, MeanRevParams()) == +1


def test_decide_entry_short_fires_on_extreme_pos_deviation_and_overbought_rsi():
    row = pd.Series({"deviation": 2.5, "rsi": 75.0, "atr_pct": 0.5})
    assert decide_entry(row, MeanRevParams()) == -1


def test_decide_entry_rsi_gate_blocks_long():
    row = pd.Series({"deviation": -3.0, "rsi": 50.0, "atr_pct": 0.5})
    assert decide_entry(row, MeanRevParams()) == 0


def test_decide_entry_rsi_gate_blocks_short():
    row = pd.Series({"deviation": 3.0, "rsi": 50.0, "atr_pct": 0.5})
    assert decide_entry(row, MeanRevParams()) == 0


def test_decide_entry_deviation_gate_blocks_moderate():
    row = pd.Series({"deviation": -0.5, "rsi": 20.0, "atr_pct": 0.5})
    assert decide_entry(row, MeanRevParams()) == 0


def test_decide_entry_nan_values_return_zero():
    row = pd.Series({"deviation": np.nan, "rsi": 20.0, "atr_pct": 0.5})
    assert decide_entry(row, MeanRevParams()) == 0
    row = pd.Series({"deviation": -3.0, "rsi": np.nan, "atr_pct": 0.5})
    assert decide_entry(row, MeanRevParams()) == 0


def test_decide_entry_respects_custom_thresholds():
    row = pd.Series({"deviation": -1.5, "rsi": 35.0, "atr_pct": 0.5})
    assert decide_entry(row, MeanRevParams()) == 0  # default too strict
    relaxed = MeanRevParams(deviation_enter=1.0, rsi_long_max=40.0)
    assert decide_entry(row, relaxed) == +1


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
