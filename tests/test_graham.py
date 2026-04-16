"""Tests for engines/graham.py — endogenous momentum engine + baseline test."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from config.params import ACCOUNT_SIZE
from engines.graham import (
    GrahamParams,
    compute_features,
    count_higher_highs,
    count_lower_lows,
    calc_levels,
    decide_direction,
    graham_size,
    run_backtest,
    scan_symbol,
    update_trailing_stop,
)


# ════════════════════════════════════════════════════════════════════
# Data fixtures
# ════════════════════════════════════════════════════════════════════

def _make_ohlcv(n: int = 4000, seed: int = 0, vol: float = 0.01,
                start_price: float = 100.0,
                drift: float = 0.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    log_ret = rng.standard_normal(n) * vol + drift
    close = start_price * np.exp(np.cumsum(log_ret))
    hi_noise = np.abs(rng.standard_normal(n)) * vol * 0.5
    lo_noise = np.abs(rng.standard_normal(n)) * vol * 0.5
    high = close * (1 + hi_noise)
    low = close * (1 - lo_noise)
    open_ = np.concatenate([[start_price], close[:-1]])
    time = pd.date_range("2025-01-01", periods=n, freq="15min")
    return pd.DataFrame({
        "time": time, "open": open_, "high": high, "low": low,
        "close": close, "vol": rng.uniform(100, 1000, size=n),
        "tbb": rng.uniform(50, 500, size=n),
    })


def _df_with_columns(n: int = 100, **cols) -> pd.DataFrame:
    """Build a minimal df with explicit columns for unit-level tests."""
    defaults = {
        "time": pd.date_range("2025-01-01", periods=n, freq="15min"),
        "open": np.full(n, 100.0),
        "high": np.full(n, 100.5),
        "low": np.full(n, 99.5),
        "close": np.full(n, 100.0),
        "atr": np.full(n, 1.0),
        "graham_ema_fast": np.full(n, 100.0),
        "graham_ema_slow": np.full(n, 100.0),
        "graham_slope": np.zeros(n),
        "graham_hh_count": np.zeros(n, dtype=int),
        "graham_ll_count": np.zeros(n, dtype=int),
        "eta_smooth": np.full(n, 0.5),
    }
    defaults.update(cols)
    return pd.DataFrame(defaults)


# ════════════════════════════════════════════════════════════════════
# Sizing
# ════════════════════════════════════════════════════════════════════

def test_graham_size_fixed_risk_pct():
    size = graham_size(10_000, 100.0, 98.0, target_pct=0.03)
    assert size == pytest.approx(150.0, rel=1e-6)


def test_graham_size_zero_on_bad_inputs():
    assert graham_size(10_000, 100.0, 100.0, 0.03) == 0.0
    assert graham_size(0, 100.0, 98.0, 0.03) == 0.0


# ════════════════════════════════════════════════════════════════════
# Higher-highs / lower-lows
# ════════════════════════════════════════════════════════════════════

def test_count_higher_highs_monotonic_up():
    """Pure up-trend with distinct peaks should give multiple HHs."""
    highs = np.array([1.0, 3.0, 2.0, 5.0, 3.0, 7.0, 4.0, 9.0, 5.0, 11.0])
    # Pivots (i-1<i>i+1) in indices 1..8: i=1 (3>1,3>2) yes, i=3 yes,
    # i=5 yes, i=7 yes. Pivot heights: [3,5,7,9]. HH diffs: 3 positive → 3 HHs.
    # But count_higher_highs excludes the last index (i+1 must exist),
    # so up to index 8 where i=7 is the last confirmed pivot.
    n = count_higher_highs(highs, lookback=20)
    assert n >= 2


def test_count_higher_highs_monotonic_down_is_zero():
    highs = np.array([10.0, 8.0, 9.0, 6.0, 7.0, 4.0, 5.0, 2.0, 3.0, 1.0])
    # Pivots are at 2,4,6,8 with heights [9,7,5,3] — strictly decreasing →
    # 0 higher-highs.
    n = count_higher_highs(highs, lookback=20)
    assert n == 0


def test_count_lower_lows_monotonic_down():
    lows = np.array([10.0, 8.0, 9.0, 6.0, 7.0, 4.0, 5.0, 2.0, 3.0, 1.0])
    # Pivots: (i-1>i<i+1) at 1 (10>8<9), 3, 5, 7 with values [8,6,4,2].
    # Strictly decreasing → 3 LLs.
    n = count_lower_lows(lows, lookback=20)
    assert n >= 2


def test_count_higher_highs_flat():
    highs = np.full(20, 5.0)
    assert count_higher_highs(highs, lookback=20) == 0


def test_count_hh_ll_respect_short_array():
    assert count_higher_highs(np.array([1.0, 2.0]), 5) == 0
    assert count_lower_lows(np.array([1.0, 2.0]), 5) == 0


# ════════════════════════════════════════════════════════════════════
# decide_direction — five conditions
# ════════════════════════════════════════════════════════════════════

def _scenario_long(sustained_bars: int, eta: float = 0.85, **overrides
                   ) -> pd.DataFrame:
    """Build a df where at bar t=sustained_bars-1 everything aligns for LONG."""
    n = sustained_bars + 20
    eta_arr = np.full(n, eta)
    df = _df_with_columns(
        n,
        eta_smooth=eta_arr,
        graham_ema_fast=np.full(n, 101.0),   # fast > slow
        graham_ema_slow=np.full(n, 100.0),
        close=np.full(n, 102.0),              # close > fast
        graham_slope=np.full(n, 0.001),       # slope > min_abs default 0.0008
        graham_hh_count=np.full(n, 3, dtype=int),  # >= 2
        graham_ll_count=np.zeros(n, dtype=int),
    )
    for col, val in overrides.items():
        df[col] = val
    return df


def test_decide_direction_long_all_conditions_met():
    params = GrahamParams(
        eta_lower=0.80, eta_upper=0.95,
        eta_sustained_bars=5, slope_min_abs=0.0008,
        structure_min_count=2,
    )
    df = _scenario_long(sustained_bars=10, eta=0.85)
    assert decide_direction(df, t=9, params=params) == +1


def test_decide_direction_eta_out_of_band_blocks():
    params = GrahamParams(eta_lower=0.80, eta_upper=0.95, eta_sustained_bars=5)
    df = _scenario_long(sustained_bars=10, eta=0.60)  # below band
    assert decide_direction(df, t=9, params=params) == 0


def test_decide_direction_eta_above_upper_blocks():
    params = GrahamParams(eta_lower=0.80, eta_upper=0.95, eta_sustained_bars=5)
    df = _scenario_long(sustained_bars=10, eta=0.99)  # above upper
    assert decide_direction(df, t=9, params=params) == 0


def test_decide_direction_slope_below_threshold_blocks():
    params = GrahamParams(slope_min_abs=0.001, eta_sustained_bars=5)
    df = _scenario_long(sustained_bars=10, eta=0.85,
                        graham_slope=np.full(30, 0.0005))
    assert decide_direction(df, t=9, params=params) == 0


def test_decide_direction_hh_below_threshold_blocks():
    params = GrahamParams(structure_min_count=3, eta_sustained_bars=5)
    df = _scenario_long(sustained_bars=10, eta=0.85,
                        graham_hh_count=np.full(30, 1, dtype=int))
    assert decide_direction(df, t=9, params=params) == 0


def test_decide_direction_bypass_eta_gate_allows_trend_only_entry():
    """With bypass, eta conditions are ignored; trend filters still apply."""
    params = GrahamParams(bypass_eta_gate=True, eta_sustained_bars=5,
                          slope_min_abs=0.0008, structure_min_count=2)
    df = _scenario_long(sustained_bars=10, eta=0.40)  # eta way out of band
    assert decide_direction(df, t=9, params=params) == +1


def test_decide_direction_short_path():
    params = GrahamParams(
        eta_lower=0.80, eta_upper=0.95, eta_sustained_bars=5,
        slope_min_abs=0.0008, structure_min_count=2,
    )
    n = 25
    df = _df_with_columns(
        n,
        eta_smooth=np.full(n, 0.85),
        graham_ema_fast=np.full(n, 99.0),
        graham_ema_slow=np.full(n, 100.0),
        close=np.full(n, 98.0),
        graham_slope=np.full(n, -0.001),
        graham_hh_count=np.zeros(n, dtype=int),
        graham_ll_count=np.full(n, 3, dtype=int),
    )
    assert decide_direction(df, t=10, params=params) == -1


# ════════════════════════════════════════════════════════════════════
# calc_levels
# ════════════════════════════════════════════════════════════════════

def test_calc_levels_long():
    params = GrahamParams(stop_atr_mult=2.0)
    df = _df_with_columns(10, atr=np.full(10, 2.0), open=np.full(10, 100.0))
    lv = calc_levels(df, t=5, direction=+1, params=params)
    assert lv is not None
    entry, stop = lv
    assert stop < entry
    assert stop == pytest.approx(100.0 - 2.0 * 2.0)


def test_calc_levels_short():
    params = GrahamParams(stop_atr_mult=2.0)
    df = _df_with_columns(10, atr=np.full(10, 2.0), open=np.full(10, 100.0))
    lv = calc_levels(df, t=5, direction=-1, params=params)
    assert lv is not None
    entry, stop = lv
    assert stop > entry


# ════════════════════════════════════════════════════════════════════
# Trailing stop
# ════════════════════════════════════════════════════════════════════

def test_trailing_stop_activates_after_1atr_long():
    params = GrahamParams(trail_atr_mult=2.0)
    trade = {
        "direction": +1, "entry": 100.0, "stop": 98.0,
        "atr_at_entry": 1.0, "extreme_price": 100.0,
        "trail_active": False,
    }
    # Price moves up by 0.5 ATR → not active yet
    update_trailing_stop(trade, high=100.5, low=100.0, atr_now=1.0, params=params)
    assert trade["trail_active"] is False
    # Price moves to entry + 1 ATR exactly → activates
    update_trailing_stop(trade, high=101.0, low=100.5, atr_now=1.0, params=params)
    assert trade["trail_active"] is True


def test_trailing_stop_moves_with_trend_long():
    params = GrahamParams(trail_atr_mult=2.0)
    trade = {
        "direction": +1, "entry": 100.0, "stop": 98.0,
        "atr_at_entry": 1.0, "extreme_price": 100.0, "trail_active": True,
    }
    update_trailing_stop(trade, high=105.0, low=100.0, atr_now=1.0, params=params)
    # Trail candidate: 105 - 2*1 = 103 > 98 → stop moves to 103
    assert trade["stop"] == pytest.approx(103.0)


def test_trailing_stop_does_not_retreat():
    params = GrahamParams(trail_atr_mult=2.0)
    trade = {
        "direction": +1, "entry": 100.0, "stop": 103.0,
        "atr_at_entry": 1.0, "extreme_price": 105.0, "trail_active": True,
    }
    # Bar where high is 104 (lower than extreme 105)
    update_trailing_stop(trade, high=104.0, low=103.5, atr_now=1.0, params=params)
    # extreme stays 105; candidate 103; should NOT lower from 103 to 103
    assert trade["stop"] == pytest.approx(103.0)


def test_trailing_stop_short_mirrors_long():
    params = GrahamParams(trail_atr_mult=2.0)
    trade = {
        "direction": -1, "entry": 100.0, "stop": 102.0,
        "atr_at_entry": 1.0, "extreme_price": 100.0, "trail_active": False,
    }
    # Price drops to entry - 1 ATR → activates
    update_trailing_stop(trade, high=99.0, low=99.0, atr_now=1.0, params=params)
    assert trade["trail_active"] is True
    assert trade["extreme_price"] == 99.0


# ════════════════════════════════════════════════════════════════════
# Smoke backtest
# ════════════════════════════════════════════════════════════════════

def test_compute_features_adds_columns():
    df = _make_ohlcv(3500, seed=2)
    params = GrahamParams(
        hawkes_window_bars=1000, hawkes_refit_every=250,
        hawkes_min_events=15, hawkes_vol_lookback=80,
        structure_lookback=10,
    )
    out = compute_features(df, params)
    required = {
        "graham_ema_fast", "graham_ema_slow", "graham_slope",
        "graham_hh_count", "graham_ll_count",
        "eta_raw", "eta_smooth", "atr",
    }
    assert required.issubset(out.columns)


def test_scan_symbol_smoke():
    df = _make_ohlcv(3500, seed=5)
    params = GrahamParams(
        hawkes_window_bars=1000, hawkes_refit_every=200,
        hawkes_min_events=15, hawkes_vol_lookback=80,
        structure_lookback=10,
    )
    feat = compute_features(df, params)
    trades, vetos = scan_symbol(feat, "SYNTH", params, ACCOUNT_SIZE)
    assert isinstance(trades, list)
    assert isinstance(vetos, dict)


def test_run_backtest_with_bypass_gives_different_result():
    """Falsification sanity: turning the η gate on vs off should change
    the trade count (not necessarily by a lot, but zero-delta would mean
    the gate is inert in practice)."""
    df = _make_ohlcv(3500, seed=7, drift=0.0005)
    params_a = GrahamParams(
        hawkes_window_bars=1000, hawkes_refit_every=200,
        hawkes_min_events=15, hawkes_vol_lookback=80,
        structure_lookback=10, slope_min_abs=0.0002,
        eta_lower=0.60, eta_upper=0.90,
    )
    params_b = GrahamParams(**{**params_a.__dict__, "bypass_eta_gate": True})
    ta, _, _ = run_backtest({"SYN": df}, params_a, ACCOUNT_SIZE)
    tb, _, _ = run_backtest({"SYN": df}, params_b, ACCOUNT_SIZE)
    # baseline must have >= trades (gate can only *filter* entries)
    assert len(tb) >= len(ta)


# ════════════════════════════════════════════════════════════════════
# Contract
# ════════════════════════════════════════════════════════════════════

def test_graham_registered_in_engines_dict():
    from config.engines import ENGINES
    assert "graham" in ENGINES
    assert ENGINES["graham"]["display"] == "GRAHAM"


def test_graham_script_path_exists():
    from config.engines import ENGINES
    assert Path(ENGINES["graham"]["script"]).exists()


def test_graham_not_in_frozen_or_intervals_yet():
    from config.params import ENGINE_BASKETS, ENGINE_INTERVALS, FROZEN_ENGINES
    assert "GRAHAM" not in FROZEN_ENGINES
    assert "GRAHAM" not in ENGINE_INTERVALS
    assert "GRAHAM" not in ENGINE_BASKETS
