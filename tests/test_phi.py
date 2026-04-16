"""Tests for PHI engine — focus on high-risk parts (lookahead, fib math, cluster)."""
import numpy as np
import pandas as pd
import pytest

from engines.phi import PhiParams, compute_features, compute_fibs, compute_zigzag


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


def test_fibs_math_up_swing():
    # L@100 idx 10 → H@200 idx 50. Range = 100.
    # Retracement 0.618 from H going down = 200 - 0.618*100 = 138.2.
    # Extension 1.272 above H = 200 + 0.272*100 = 227.2.
    n = 100
    idx = pd.date_range("2024-01-01", periods=n, freq="5min")
    df = pd.DataFrame({
        "time": idx,
        "open": np.full(n, 150.0), "high": np.full(n, 150.0), "low": np.full(n, 150.0),
        "close": np.full(n, 150.0), "volume": np.full(n, 1000.0),
        "atr": np.full(n, 1.0),
        "last_pivot_idx": np.full(n, -1, dtype=np.int64),
        "last_pivot_price": np.full(n, np.nan),
        "last_pivot_type": np.array([""] * n, dtype=object),
        "prev_pivot_idx": np.full(n, -1, dtype=np.int64),
        "prev_pivot_price": np.full(n, np.nan),
        "prev_pivot_type": np.array([""] * n, dtype=object),
    })
    df.loc[52:, "last_pivot_idx"] = 50
    df.loc[52:, "last_pivot_price"] = 200.0
    df.loc[52:, "last_pivot_type"] = "H"
    df.loc[52:, "prev_pivot_idx"] = 10
    df.loc[52:, "prev_pivot_price"] = 100.0
    df.loc[52:, "prev_pivot_type"] = "L"

    out = compute_fibs(df, PhiParams())
    assert abs(out["fib_0.618"].iloc[60] - 138.2) < 1e-3
    assert abs(out["fib_0.786"].iloc[60] - 121.4) < 1e-3
    assert abs(out["fib_1.272"].iloc[60] - 227.2) < 1e-3
    assert abs(out["fib_1.618"].iloc[60] - 261.8) < 1e-3
    assert out["swing_direction"].iloc[60] == +1


def test_fibs_math_down_swing():
    # H@200 idx 10 → L@100 idx 50. Down swing.
    # Retracement 0.618 from L going up = 100 + 0.618*100 = 161.8.
    # Extension 1.272 below L = 100 - 0.272*100 = 72.8.
    n = 100
    idx = pd.date_range("2024-01-01", periods=n, freq="5min")
    df = pd.DataFrame({
        "time": idx,
        "open": np.full(n, 150.0), "high": np.full(n, 150.0), "low": np.full(n, 150.0),
        "close": np.full(n, 150.0), "volume": np.full(n, 1000.0),
        "atr": np.full(n, 1.0),
        "last_pivot_idx": np.full(n, -1, dtype=np.int64),
        "last_pivot_price": np.full(n, np.nan),
        "last_pivot_type": np.array([""] * n, dtype=object),
        "prev_pivot_idx": np.full(n, -1, dtype=np.int64),
        "prev_pivot_price": np.full(n, np.nan),
        "prev_pivot_type": np.array([""] * n, dtype=object),
    })
    df.loc[52:, "last_pivot_idx"] = 50
    df.loc[52:, "last_pivot_price"] = 100.0
    df.loc[52:, "last_pivot_type"] = "L"
    df.loc[52:, "prev_pivot_idx"] = 10
    df.loc[52:, "prev_pivot_price"] = 200.0
    df.loc[52:, "prev_pivot_type"] = "H"

    out = compute_fibs(df, PhiParams())
    assert abs(out["fib_0.618"].iloc[60] - 161.8) < 1e-3
    assert abs(out["fib_1.272"].iloc[60] - 72.8) < 1e-3
    assert out["swing_direction"].iloc[60] == -1


from engines.phi import align_htfs_to_base, detect_cluster


def test_htf_alignment_no_lookahead():
    """At base time t, HTF value must come from the HTF bar that CLOSED
    strictly before or at t, not the one still open at t."""
    # Base 5m from 10:00 to 11:00 (12 bars, 10:00 through 10:55)
    base_idx = pd.date_range("2024-01-01 10:00", periods=12, freq="5min")
    base = pd.DataFrame({"time": base_idx, "close": np.arange(12, dtype=float)})
    # HTF 1h: a bar timestamped 10:00 covers 10:00-11:00 (closes at 11:00).
    #         a bar timestamped 09:00 covers 09:00-10:00 (closes at 10:00).
    # Fixture: 07:00→80, 08:00→90, 09:00→100, 10:00→110, 11:00→120
    # The 09:00 bar (close=100) is the one that closed at 10:00.
    htf_idx = pd.date_range("2024-01-01 07:00", periods=5, freq="1h")
    htf = pd.DataFrame({"time": htf_idx, "close": [80.0, 90.0, 100.0, 110.0, 120.0]})
    merged = align_htfs_to_base(base, {"1h": htf})

    # At base 10:00, the 1h bar that JUST CLOSED is the 09:00→10:00 bar (close=100.0).
    # The 10:00→11:00 bar is still OPEN at base 10:00, so it MUST NOT appear.
    row_10_00 = merged.loc[merged["time"] == pd.Timestamp("2024-01-01 10:00")].iloc[0]
    assert row_10_00["close_1h"] == 100.0

    # At base 10:55, still inside the 10:00-11:00 HTF bar → latest closed HTF is still 09:00-10:00.
    row_10_55 = merged.loc[merged["time"] == pd.Timestamp("2024-01-01 10:55")].iloc[0]
    assert row_10_55["close_1h"] == 100.0


def test_cluster_detects_confluence():
    """When fib_0.618 in 3+ TFs lies within 0.5*ATR(5m) of price, cluster fires."""
    # close=100, ATR=1.0, tolerance=0.5. fib values:
    #   1d=99.8 (in), 4h=100.3 (in), 1h=100.1 (in), 15m=95.0 (out), 5m=107.0 (out)
    # → 3 confluences → cluster fires.
    n = 50
    idx = pd.date_range("2024-01-01", periods=n, freq="5min")
    base = pd.DataFrame({
        "time": idx,
        "close": np.full(n, 100.0),
        "atr": np.full(n, 1.0),
        "fib_0.618_1d": np.full(n, 99.8),
        "fib_0.618_4h": np.full(n, 100.3),
        "fib_0.618_1h": np.full(n, 100.1),
        "fib_0.618_15m": np.full(n, 95.0),
        "fib_0.618": np.full(n, 107.0),
        "swing_direction_1d": np.full(n, +1, dtype=np.int8),
        "swing_direction_4h": np.full(n, +1, dtype=np.int8),
        "swing_direction_1h": np.full(n, +1, dtype=np.int8),
        "swing_direction_15m": np.full(n, -1, dtype=np.int8),
        "swing_direction": np.full(n, -1, dtype=np.int8),
    })
    out = detect_cluster(base, PhiParams())
    assert out["cluster_confluences"].iloc[10] == 3
    assert bool(out["cluster_active"].iloc[10]) == True
    # Majority of the 3 in-range TFs have direction=+1 → cluster_direction=+1
    assert out["cluster_direction"].iloc[10] == +1


def test_cluster_below_threshold():
    """If only 2 TFs agree, cluster is NOT active."""
    n = 50
    idx = pd.date_range("2024-01-01", periods=n, freq="5min")
    base = pd.DataFrame({
        "time": idx,
        "close": np.full(n, 100.0),
        "atr": np.full(n, 1.0),
        "fib_0.618_1d": np.full(n, 99.9),    # in
        "fib_0.618_4h": np.full(n, 100.1),   # in
        "fib_0.618_1h": np.full(n, 95.0),    # out
        "fib_0.618_15m": np.full(n, 110.0),  # out
        "fib_0.618": np.full(n, 108.0),      # out
        "swing_direction_1d": np.full(n, +1, dtype=np.int8),
        "swing_direction_4h": np.full(n, +1, dtype=np.int8),
        "swing_direction_1h": np.full(n, 0, dtype=np.int8),
        "swing_direction_15m": np.full(n, 0, dtype=np.int8),
        "swing_direction": np.full(n, 0, dtype=np.int8),
    })
    out = detect_cluster(base, PhiParams())
    assert out["cluster_confluences"].iloc[10] == 2
    assert bool(out["cluster_active"].iloc[10]) == False


from engines.phi import check_regime_gates, check_golden_trigger


def test_regime_gates_all_pass():
    """All three gates pass → regime_ok True."""
    n = 600
    idx = pd.date_range("2024-01-01", periods=n, freq="5min")
    df = pd.DataFrame({
        "time": idx,
        "close": np.full(n, 100.0),
        "ema200": np.full(n, 99.0),            # distance = 1
        "atr": np.full(n, 1.0),                # distance/ATR = 1 > 0.618 ✓
        "adx": np.full(n, 30.0),               # > 23.6 ✓
        # BB widening: rolling p38.2 over 500 bars sits ~0.003, tail is 0.05 → passes
        "bb_width": np.concatenate([np.linspace(0.001, 0.01, 500), np.full(100, 0.05)]),
    })
    out = check_regime_gates(df, PhiParams())
    assert bool(out["regime_ok"].iloc[-1]) == True


def test_regime_gates_fail_on_adx():
    n = 600
    idx = pd.date_range("2024-01-01", periods=n, freq="5min")
    df = pd.DataFrame({
        "time": idx,
        "close": np.full(n, 100.0),
        "ema200": np.full(n, 99.0),
        "atr": np.full(n, 1.0),
        "adx": np.full(n, 10.0),  # < 23.6 ✗
        "bb_width": np.full(n, 0.05),
    })
    out = check_regime_gates(df, PhiParams())
    assert bool(out["regime_ok"].iloc[-1]) == False


def test_golden_trigger_long():
    """Long trigger: wick_ratio>=0.618, volume>MA20*1.272, RSI<38.2."""
    n = 50
    df = pd.DataFrame({
        "wick_ratio": np.full(n, 0.7),
        "volume": np.full(n, 2000.0),
        "vol_ma20": np.full(n, 1000.0),   # 2000 > 1272 ✓
        "rsi": np.full(n, 30.0),          # < 38.2 ✓
    })
    out = check_golden_trigger(df, PhiParams())
    assert bool(out["trigger_long"].iloc[-1]) == True
    assert bool(out["trigger_short"].iloc[-1]) == False


def test_golden_trigger_neither():
    n = 50
    df = pd.DataFrame({
        "wick_ratio": np.full(n, 0.4),   # < 0.618 ✗
        "volume": np.full(n, 2000.0),
        "vol_ma20": np.full(n, 1000.0),
        "rsi": np.full(n, 50.0),
    })
    out = check_golden_trigger(df, PhiParams())
    assert bool(out["trigger_long"].iloc[-1]) == False
    assert bool(out["trigger_short"].iloc[-1]) == False
