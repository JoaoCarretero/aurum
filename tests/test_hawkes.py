"""Tests for core/hawkes.py — additive univariate Hawkes library."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core.hawkes import (
    HawkesFit,
    detect_jumps,
    fit_hawkes_exp,
    label_eta,
    rolling_branching_ratio,
)


# ════════════════════════════════════════════════════════════════════
# detect_jumps
# ════════════════════════════════════════════════════════════════════

def test_detect_jumps_on_gaussian_noise_near_expected_rate():
    """|r| > 2σ two-sided tail probability ≈ 2·Φ(-2) ≈ 4.55%."""
    rng = np.random.default_rng(42)
    N = 10_000
    returns = rng.standard_normal(N)
    jumps = detect_jumps(returns, k_sigma=2.0, vol_lookback=100)
    valid_bars = N - 100  # bars before vol_lookback are excluded
    rate = len(jumps) / valid_bars
    assert 0.035 < rate < 0.06, f"unexpected jump rate {rate:.4f}"


def test_detect_jumps_respects_k_sigma_ordering():
    rng = np.random.default_rng(7)
    returns = rng.standard_normal(5000)
    n1 = len(detect_jumps(returns, k_sigma=1.0))
    n2 = len(detect_jumps(returns, k_sigma=2.0))
    n3 = len(detect_jumps(returns, k_sigma=3.0))
    assert n1 > n2 > n3


def test_detect_jumps_returns_sorted_int_array():
    rng = np.random.default_rng(1)
    returns = rng.standard_normal(2000)
    jumps = detect_jumps(returns)
    assert jumps.dtype == np.int64
    if len(jumps) > 1:
        assert np.all(np.diff(jumps) > 0)


def test_detect_jumps_no_lookahead():
    """Spike injected at bar 500 is detected because σ uses only prior bars."""
    rng = np.random.default_rng(0)
    returns = rng.standard_normal(1000) * 0.01  # low-vol baseline
    returns[500] = 0.10  # ~10σ spike
    jumps = detect_jumps(returns, k_sigma=2.0, vol_lookback=100)
    assert 500 in jumps


def test_detect_jumps_short_array_returns_empty():
    """Bars before vol_lookback are always excluded."""
    rng = np.random.default_rng(3)
    returns = rng.standard_normal(50)
    jumps = detect_jumps(returns, k_sigma=2.0, vol_lookback=100)
    assert len(jumps) == 0


def test_detect_jumps_rejects_2d_input():
    with pytest.raises(ValueError, match="1-D"):
        detect_jumps(np.zeros((10, 2)))


# ════════════════════════════════════════════════════════════════════
# label_eta
# ════════════════════════════════════════════════════════════════════

def test_label_eta_thresholds():
    assert label_eta(0.30) == "EXO"
    assert label_eta(0.49) == "EXO"
    assert label_eta(0.50) == "MIXED"
    assert label_eta(0.65) == "MIXED"
    assert label_eta(0.79) == "MIXED"
    assert label_eta(0.80) == "ENDO"
    assert label_eta(0.87) == "ENDO"
    assert label_eta(0.94) == "ENDO"
    assert label_eta(0.95) == "CRITICAL"
    assert label_eta(0.97) == "CRITICAL"
    assert label_eta(1.0) == "CRITICAL"


def test_label_eta_nan_inputs():
    assert label_eta(None) == "NAN"
    assert label_eta(float("nan")) == "NAN"
    assert label_eta("invalid") == "NAN"


# ════════════════════════════════════════════════════════════════════
# fit_hawkes_exp — validation
# ════════════════════════════════════════════════════════════════════

def test_fit_hawkes_exp_raises_on_few_events():
    with pytest.raises(ValueError, match="need >= 10 events"):
        fit_hawkes_exp(np.arange(5, dtype=float), T=100.0)


def test_fit_hawkes_exp_raises_on_unsorted():
    events = np.array([1.0, 3.0, 2.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0])
    with pytest.raises(ValueError, match="sorted"):
        fit_hawkes_exp(events, T=100.0)


def test_fit_hawkes_exp_raises_on_bad_T():
    with pytest.raises(ValueError, match="T must be > 0"):
        fit_hawkes_exp(np.arange(20, dtype=float), T=0.0)


def test_fit_hawkes_exp_raises_when_events_past_T():
    events = np.arange(20, dtype=float)
    with pytest.raises(ValueError, match="last event"):
        fit_hawkes_exp(events, T=10.0)


# ════════════════════════════════════════════════════════════════════
# fit_hawkes_exp — recovery & behavior
# ════════════════════════════════════════════════════════════════════

def test_fit_hawkes_exp_recovers_params_on_poisson_limit():
    """Pure Poisson process (no excitation) → η ≈ 0, μ ≈ true rate."""
    rng = np.random.default_rng(100)
    mu_true = 2.0
    T = 500.0
    interarrivals = rng.exponential(1.0 / mu_true, size=1500)
    events = np.cumsum(interarrivals)
    events = events[events < T]
    assert len(events) > 500  # sanity

    fit = fit_hawkes_exp(events, T=T)
    assert fit.converged
    assert fit.branching_ratio < 0.30, (
        f"η={fit.branching_ratio:.3f} too high for Poisson process"
    )
    assert abs(fit.mu - mu_true) / mu_true < 0.35


def test_fit_hawkes_exp_detects_clustering():
    """Manually injected clusters → η clearly above 0."""
    rng = np.random.default_rng(42)
    mu_true = 0.5
    T = 1500.0
    base = np.cumsum(rng.exponential(1.0 / mu_true, size=800))
    base = base[base < T]
    # Each base event spawns a child with prob 0.6, 0.3 bar later on average
    children = []
    for t in base:
        if rng.random() < 0.6:
            child_t = t + rng.exponential(0.3)
            if child_t < T:
                children.append(child_t)
                # Second generation with prob 0.3
                if rng.random() < 0.3:
                    grand_t = child_t + rng.exponential(0.3)
                    if grand_t < T:
                        children.append(grand_t)
    events = np.sort(np.concatenate([base, np.asarray(children)]))

    fit = fit_hawkes_exp(events, T=T)
    assert fit.converged
    assert fit.branching_ratio > 0.25, (
        f"η={fit.branching_ratio:.3f} too low for clustered events"
    )


def test_fit_hawkes_exp_respects_max_eta():
    """Heavy clustering must not drive η above max_eta (soft penalty)."""
    rng = np.random.default_rng(0)
    T = 800.0
    events: list[float] = []
    t = 0.1
    while t < T:
        events.append(t)
        # burst of aftershocks
        for _ in range(int(rng.integers(4, 8))):
            t = t + rng.exponential(0.1)
            if t < T:
                events.append(t)
        t += rng.exponential(5.0)
    et = np.asarray(sorted(events))
    et = et[et < T]

    cap = 0.90
    fit = fit_hawkes_exp(et, T=T, max_eta=cap)
    # Allow tiny numerical slack but not meaningfully above the cap
    assert fit.branching_ratio <= cap + 5e-3, (
        f"η={fit.branching_ratio:.4f} exceeded cap {cap}"
    )


def test_hawkes_fit_dataclass_frozen():
    fit = HawkesFit(
        mu=1.0, alpha=0.3, beta=1.0, branching_ratio=0.3,
        loglik=-100.0, n_events=50, T=100.0,
        converged=True, message="ok",
    )
    with pytest.raises(Exception):
        fit.mu = 2.0  # type: ignore[misc]


# ════════════════════════════════════════════════════════════════════
# rolling_branching_ratio
# ════════════════════════════════════════════════════════════════════

def _synthetic_ohlcv(n: int = 5000, seed: int = 0,
                     vol: float = 0.01) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    log_ret = rng.standard_normal(n) * vol
    close = 100.0 * np.exp(np.cumsum(log_ret))
    return pd.DataFrame({"close": close}, index=pd.RangeIndex(n))


def test_rolling_branching_ratio_shape():
    df = _synthetic_ohlcv(5000)
    out = rolling_branching_ratio(
        df, window_bars=1000, refit_every=200, min_events=15,
    )
    assert len(out) == len(df)
    assert set(out.columns) == {"eta_raw", "eta_smooth", "n_events", "fit_bar"}


def test_rolling_branching_ratio_nan_before_first_fit():
    df = _synthetic_ohlcv(3000)
    out = rolling_branching_ratio(
        df, window_bars=1000, refit_every=100, min_events=15,
    )
    assert out.iloc[:1000]["eta_raw"].isna().all()
    assert out.iloc[:1000]["eta_smooth"].isna().all()
    assert out.iloc[:1000]["n_events"].isna().all()
    assert out.iloc[:1000]["fit_bar"].isna().all()


def test_rolling_branching_ratio_refits_at_expected_cadence():
    df = _synthetic_ohlcv(4000)
    out = rolling_branching_ratio(
        df, window_bars=1000, refit_every=200, min_events=15,
    )
    fit_bars = np.sort(out["fit_bar"].dropna().unique())
    # At least several fits should have succeeded
    assert len(fit_bars) >= 5
    # Distinct fit_bar values must be multiples of refit_every (all are
    # bar indices where the loop refits)
    gaps = np.diff(fit_bars)
    assert all(int(g) % 200 == 0 for g in gaps), f"unexpected gaps: {gaps}"


def test_rolling_branching_ratio_carry_forward_on_failure():
    """A flat segment produces no jumps → fits skip → η carries forward."""
    rng = np.random.default_rng(0)
    n = 4000
    log_ret = rng.standard_normal(n) * 0.01
    log_ret[2000:3000] = 0.0  # flat segment
    close = 100.0 * np.exp(np.cumsum(log_ret))
    df = pd.DataFrame({"close": close}, index=pd.RangeIndex(n))
    out = rolling_branching_ratio(
        df, window_bars=800, refit_every=200,
        min_events=15, vol_lookback=50,
    )
    # In bars [2800, 3000) most of the fit window is flat → skip → carry.
    # We cannot guarantee a single constant value because fits just before
    # may still succeed; we test instead that *within* the fully-flat zone
    # (bars [2800, 2900)) the value is constant.
    region = out.iloc[2800:2900]["eta_raw"].dropna().values
    if len(region) > 1:
        assert np.allclose(region, region[0]), (
            "expected eta_raw constant in flat region, got variation"
        )


def test_rolling_branching_ratio_smoothing_reduces_variance():
    """EWM smoothing must not *increase* variance of eta_raw."""
    df = _synthetic_ohlcv(8000, seed=3)
    out = rolling_branching_ratio(
        df, window_bars=1000, refit_every=100,
        min_events=15, smoothing_span=10,
    )
    raw = out["eta_raw"].dropna().values
    smooth = out["eta_smooth"].dropna().values
    # Align by length (both come from same non-NaN region)
    if len(raw) > 20 and len(smooth) > 20:
        assert np.var(smooth) <= np.var(raw) + 1e-9


def test_rolling_branching_ratio_bad_close_col():
    df = pd.DataFrame({"price": [1.0] * 3000})
    with pytest.raises(ValueError, match="missing column"):
        rolling_branching_ratio(df)


def test_rolling_branching_ratio_preserves_index():
    """Output must carry the input DataFrame's index."""
    idx = pd.date_range("2025-01-01", periods=3000, freq="15min")
    df = _synthetic_ohlcv(3000).set_index(idx)
    out = rolling_branching_ratio(
        df, window_bars=1000, refit_every=100, min_events=15,
    )
    assert out.index.equals(df.index)
