"""Tests for PHI engine — focus on high-risk parts (lookahead, fib math, cluster)."""
import numpy as np
import pandas as pd
import pytest

from engines.phi import PhiParams, compute_features, compute_zigzag


def _synthetic_df(n: int = 600, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.normal(0, 0.5, n))
    high = close + rng.uniform(0.1, 0.8, n)
    low = close - rng.uniform(0.1, 0.8, n)
    open_ = close + rng.normal(0, 0.2, n)
    vol = rng.uniform(1000, 5000, n)
    idx = pd.date_range("2024-01-01", periods=n, freq="5min")
    return pd.DataFrame({
        "time": idx, "open": open_, "high": high, "low": low,
        "close": close, "volume": vol,
    })


def test_compute_features_adds_expected_columns():
    df = _synthetic_df()
    out = compute_features(df, PhiParams())
    for col in ["atr", "rsi", "bb_width", "adx", "ema200",
                "ema200_slope", "wick_ratio", "vol_ma20"]:
        assert col in out.columns, f"missing column: {col}"
    assert out["atr"].iloc[-1] > 0
    assert 0 <= out["rsi"].iloc[-1] <= 100
    assert out["bb_width"].iloc[-1] > 0


def test_compute_features_no_lookahead():
    """A feature at index t must not change if we extend the DF beyond t."""
    df = _synthetic_df(n=600)
    full = compute_features(df, PhiParams())
    short = compute_features(df.iloc[:500].copy(), PhiParams())
    cols = ["atr", "rsi", "bb_width", "adx", "ema200", "wick_ratio"]
    for c in cols:
        assert abs(full[c].iloc[400] - short[c].iloc[400]) < 1e-6, f"lookahead in {c}"


def test_zigzag_detects_alternating_pivots():
    # Synthetic: sharp V — one high near idx 30, one low near idx 70.
    n = 100
    close = np.concatenate([np.linspace(100, 120, 30), np.linspace(120, 90, 40), np.linspace(90, 110, 30)])
    high = close + 0.5
    low = close - 0.5
    idx = pd.date_range("2024-01-01", periods=n, freq="5min")
    df = pd.DataFrame({"time": idx, "open": close, "high": high, "low": low,
                       "close": close, "volume": np.ones(n) * 1000})
    df = compute_features(df, PhiParams())
    z = compute_zigzag(df, PhiParams())
    # Columns should exist
    assert "last_pivot_type" in z.columns
    assert "last_pivot_price" in z.columns
    assert "prev_pivot_type" in z.columns
    assert "prev_pivot_price" in z.columns
    # By end of series, at least one H and one L should be confirmed somewhere
    types_seen = set(z["last_pivot_type"].unique()) | set(z["prev_pivot_type"].unique())
    assert "H" in types_seen and "L" in types_seen


def test_zigzag_no_lookahead():
    """Pivot state at idx t must match whether we pass the full df or df[:t+confirm+5]."""
    n = 300
    rng = np.random.default_rng(7)
    close = 100 + np.cumsum(rng.normal(0, 0.5, n))
    high = close + rng.uniform(0.1, 0.8, n)
    low = close - rng.uniform(0.1, 0.8, n)
    idx = pd.date_range("2024-01-01", periods=n, freq="5min")
    df = pd.DataFrame({"time": idx, "open": close, "high": high, "low": low,
                       "close": close, "volume": np.ones(n) * 1000})
    df_full = compute_features(df, PhiParams())
    z_full = compute_zigzag(df_full, PhiParams())
    df_short = compute_features(df.iloc[:160].copy(), PhiParams())
    z_short = compute_zigzag(df_short, PhiParams())
    # last_pivot_price at idx 150 must match (both dfs have 150 fully processed).
    assert z_full["last_pivot_type"].iloc[150] == z_short["last_pivot_type"].iloc[150]
    p_full = z_full["last_pivot_price"].iloc[150]
    p_short = z_short["last_pivot_price"].iloc[150]
    if not (np.isnan(p_full) and np.isnan(p_short)):
        assert abs(p_full - p_short) < 1e-6
