"""Tests for PHI engine — focus on high-risk parts (lookahead, fib math, cluster)."""
import numpy as np
import pandas as pd
import pytest

from engines.phi import PhiParams, compute_features


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
