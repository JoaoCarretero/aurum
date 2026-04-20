"""Focused tests for engines/medallion.py recent tuning paths."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engines.medallion import (
    MedallionParams,
    _resolve_exit,
    calc_levels,
    decide_direction,
    medallion_kelly_fraction,
)


def _feature_df(**overrides) -> pd.DataFrame:
    n = 8
    base = {
        "time": pd.date_range("2025-01-01", periods=n, freq="15min"),
        "open": [100.0] * n,
        "high": [101.0] * n,
        "low": [99.0] * n,
        "close": [100.0] * n,
        "atr": [1.0] * n,
        "rsi": [70.0] * n,
        "med_trend_flat": [1.0] * n,
        "med_autocorr": [-0.2] * n,
        "med_z_return": [1.5] * n,
        "med_z_vol": [1.5] * n,
        "med_ema_dev_z": [1.2] * n,
        "med_seasonality_z": [1.0] * n,
        "med_ensemble_score": [-0.6] * n,
        "hmm_prob_chop": [0.8] * n,
        "hmm_prob_bull": [0.1] * n,
        "hmm_prob_bear": [0.1] * n,
        "ema20": [98.0] * n,
    }
    base.update(overrides)
    return pd.DataFrame(base)


def test_decide_direction_respects_min_active_components_gate():
    params = MedallionParams(min_active_components=5, hmm_enabled=False)
    df = _feature_df(
        med_ema_dev_z=[0.2] * 8,
        med_seasonality_z=[0.1] * 8,
    )

    assert decide_direction(df, 5, params) == 0


def test_calc_levels_uses_ema_target_when_farther_than_tp_floor():
    params = MedallionParams(ema_fast=20, tp_atr_mult=0.8, stop_atr_mult=1.0)
    df = _feature_df(open=[100.0] * 8, atr=[2.0] * 8, ema20=[105.0] * 8)

    levels = calc_levels(df, 5, +1, params)

    assert levels is not None
    entry, stop, tp = levels
    assert entry == pytest.approx(100.0)
    assert stop == pytest.approx(98.0)
    assert tp == pytest.approx(105.0)


def test_resolve_exit_hmm_trend_exit_for_long_position():
    params = MedallionParams(hmm_enabled=True, exit_on_hmm_trend=True, hmm_exit_trend_prob=0.75)
    df = _feature_df(
        high=[100.5] * 8,
        low=[99.5] * 8,
        close=[100.0] * 8,
        med_ensemble_score=[0.2] * 8,
        hmm_prob_bear=[0.8] * 8,
        hmm_prob_bull=[0.1] * 8,
    )

    result = _resolve_exit(df, bar_idx=5, entry_idx=2, direction=+1, entry=100.0, stop=98.0, tp=104.0, params=params)

    assert result == ("hmm_trend_exit", 100.0)


def test_resolve_exit_hmm_trend_exit_for_short_position():
    params = MedallionParams(hmm_enabled=True, exit_on_hmm_trend=True, hmm_exit_trend_prob=0.75)
    df = _feature_df(
        high=[100.5] * 8,
        low=[99.5] * 8,
        close=[100.0] * 8,
        med_ensemble_score=[-0.2] * 8,
        hmm_prob_bull=[0.8] * 8,
        hmm_prob_bear=[0.1] * 8,
    )

    result = _resolve_exit(df, bar_idx=5, entry_idx=2, direction=-1, entry=100.0, stop=102.0, tp=96.0, params=params)

    assert result == ("hmm_trend_exit", 100.0)


def test_medallion_kelly_fraction_dampens_negative_expectancy_and_loss_rate():
    params = MedallionParams(
        kelly_fraction=0.25,
        kelly_min_trades=10,
        kelly_rolling_trades=10,
        max_pct_equity=0.02,
    )
    recent_pnls = [-1.0, -1.0, -1.0, -1.0, -1.0, -1.0, 2.0, 2.0, 2.0, 2.0]

    value = medallion_kelly_fraction(recent_pnls, params)

    assert np.isfinite(value)
    assert 0.0 < value < 0.02
