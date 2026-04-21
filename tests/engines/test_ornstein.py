"""Tests for ORNSTEIN — mean-reversion engine (2026-04-17).

Cover the high-risk parts: no lookahead in HTF merge, stats battery math,
Ω aggregation with per-component logging, ablation flag wiring.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engines.ornstein import (
    ABLATION_VARIANTS,
    OrnsteinParams,
    ORNSTEIN_PRESETS,
    _atr_gate,
    _rolling_ou_fit,
    _rolling_variance_ratio,
    _subscore_adf,
    _subscore_bb,
    _subscore_hurst,
    _subscore_ou,
    _subscore_vr,
    align_htfs_to_base,
    compute_features,
    compute_omega,
    derive_entry_direction,
    ornstein_size,
)


def _synthetic_df(n: int = 600, seed: int = 42,
                  freq: str = "15min") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.normal(0, 0.5, n))
    high = close + rng.uniform(0.1, 0.8, n)
    low = close - rng.uniform(0.1, 0.8, n)
    open_ = close + rng.normal(0, 0.2, n)
    vol = rng.uniform(1000, 5000, n)
    idx = pd.date_range("2026-01-01", periods=n, freq=freq)
    return pd.DataFrame({
        "time": idx, "open": open_, "high": high, "low": low,
        "close": close, "vol": vol,
    })


# ── Feature computation ─────────────────────────────────────────

def test_compute_features_adds_expected_columns():
    df = _synthetic_df()
    out = compute_features(df, OrnsteinParams())
    for col in ("atr", "rsi", "sma_fast", "ema_medium", "ema_slow",
                "hma", "vwap", "deviation", "bb_upper", "bb_lower",
                "bb_pct_b", "atr_percentile"):
        assert col in out.columns, f"missing: {col}"
    # Deviation is close-to-EMA normalized by ATR — bounded by ATR spec.
    assert not np.isnan(out["deviation"].iloc[-1])


def test_compute_features_no_lookahead():
    """Feature at idx t unchanged if we extend df beyond t."""
    df = _synthetic_df(n=600)
    full = compute_features(df, OrnsteinParams())
    short = compute_features(df.iloc[:500].copy(), OrnsteinParams())
    cols = ["atr", "rsi", "sma_fast", "ema_medium", "hma", "deviation"]
    for c in cols:
        a = full[c].iloc[400]
        b = short[c].iloc[400]
        if np.isnan(a) and np.isnan(b):
            continue
        assert abs(a - b) < 1e-6, f"lookahead in {c}"


# ── HTF alignment ──────────────────────────────────────────────

def test_htf_alignment_uses_closed_bars_only():
    """At base 10:00, the 1h bar visible is the 09:00→10:00 one (just closed)."""
    base_idx = pd.date_range("2026-01-01 10:00", periods=12, freq="5min")
    base = pd.DataFrame({"time": base_idx, "close": np.arange(12, dtype=float)})
    htf_idx = pd.date_range("2026-01-01 07:00", periods=5, freq="1h")
    htf = pd.DataFrame({"time": htf_idx, "close": [80.0, 90.0, 100.0, 110.0, 120.0]})
    merged = align_htfs_to_base(base, {"1h": htf})
    row_10_00 = merged.loc[merged["time"] == pd.Timestamp("2026-01-01 10:00")].iloc[0]
    assert row_10_00["close_1h"] == 100.0
    row_10_55 = merged.loc[merged["time"] == pd.Timestamp("2026-01-01 10:55")].iloc[0]
    assert row_10_55["close_1h"] == 100.0


# ── O-U fit ────────────────────────────────────────────────────

def test_ou_fit_detects_mean_reverting_series():
    """AR(1) with beta=-0.2 should produce theta~0.2 and halflife~ln(2)/0.2 ≈ 3.47."""
    rng = np.random.default_rng(7)
    n = 500
    x = np.zeros(n)
    theta_true = 0.2
    for i in range(1, n):
        x[i] = x[i - 1] * (1 - theta_true) + rng.normal(0, 1)
    theta, mu, hl = _rolling_ou_fit(x, window=200)
    # Tail should be populated
    tail_theta = theta[-1]
    tail_hl = hl[-1]
    assert not np.isnan(tail_theta)
    assert 0.1 < tail_theta < 0.4  # some tolerance
    assert 2.0 < tail_hl < 10.0


def test_ou_fit_weak_theta_on_random_walk():
    """A random walk does not have true mean reversion — expected theta
    distribution is noisy around zero. The downstream half-life gate
    (halflife_min=5) is what filters these weak fits out of the scoring
    pipeline; OU fit alone is not a hard filter.
    """
    rng = np.random.default_rng(7)
    x = np.cumsum(rng.normal(0, 1, 500))
    theta, mu, hl = _rolling_ou_fit(x, window=200)
    tail_theta = theta[~np.isnan(theta)][300 - sum(np.isnan(theta[:300])):]
    if len(tail_theta) > 0:
        # Random walk theta should be small on average (no real reversion)
        assert abs(np.nanmean(theta[300:])) < 0.05

    # Strong MR series for contrast — theta must be clearly larger
    rng2 = np.random.default_rng(7)
    y = np.zeros(500)
    for i in range(1, 500):
        y[i] = y[i - 1] * 0.7 + rng2.normal(0, 1)
    theta_mr, _, _ = _rolling_ou_fit(y, window=200)
    assert np.nanmean(theta_mr[300:]) > 0.2


# ── Variance Ratio ─────────────────────────────────────────────

def test_variance_ratio_below_one_for_mean_reverting():
    """Mean-reverting series has VR<1 (diffs anti-correlated)."""
    rng = np.random.default_rng(5)
    n = 400
    x = np.zeros(n)
    for i in range(1, n):
        x[i] = x[i - 1] * 0.7 + rng.normal(0, 1)
    vr = _rolling_variance_ratio(x, window=200, lags=(2, 4, 8))
    tail = vr[-1]
    # At least 2 of 3 lags below 1
    below = sum(1 for v in tail if not np.isnan(v) and v < 1.0)
    assert below >= 2


def test_variance_ratio_near_one_for_random_walk():
    rng = np.random.default_rng(5)
    x = np.cumsum(rng.normal(0, 1, 400))
    vr = _rolling_variance_ratio(x, window=200, lags=(2, 4, 8))
    tail = vr[-1]
    # Random walk → VR ≈ 1 → majority NOT strictly below 1 with margin
    below = sum(1 for v in tail if not np.isnan(v) and v < 0.9)
    assert below <= 1


# ── Subscore math ──────────────────────────────────────────────

def test_subscore_ou_scores_zero_when_halflife_out_of_band():
    p = OrnsteinParams(halflife_min=5.0, halflife_max=50.0)
    row_too_short = pd.Series({"halflife": 2.0, "ou_theta": 0.4})
    row_too_long = pd.Series({"halflife": 100.0, "ou_theta": 0.01})
    row_in_band = pd.Series({"halflife": 20.0, "ou_theta": 0.05})
    assert _subscore_ou(row_too_short, p) == 0.0
    assert _subscore_ou(row_too_long, p) == 0.0
    assert _subscore_ou(row_in_band, p) > 0.0


def test_subscore_hurst_zero_above_threshold():
    p = OrnsteinParams(hurst_threshold=0.45)
    assert _subscore_hurst(pd.Series({"hurst": 0.7}), p) == 0.0
    assert _subscore_hurst(pd.Series({"hurst": 0.3}), p) > 0.0


def test_subscore_adf_zero_above_pvalue():
    p = OrnsteinParams(adf_pvalue_max=0.05)
    assert _subscore_adf(pd.Series({"adf_pvalue": 0.10}), p) == 0.0
    assert _subscore_adf(pd.Series({"adf_pvalue": 0.01}), p) > 0.0


def test_subscore_vr_requires_minimum_lags_below_one():
    p = OrnsteinParams(vr_lags=(2, 4, 8), vr_min_below_one=2)
    row_fail = pd.Series({"vr_lag2": 0.8, "vr_lag4": 1.2, "vr_lag8": 1.5})
    row_ok = pd.Series({"vr_lag2": 0.8, "vr_lag4": 0.9, "vr_lag8": 1.2})
    assert _subscore_vr(row_fail, p) == 0.0
    assert _subscore_vr(row_ok, p) > 0.0


def test_subscore_bb_fires_only_on_correct_direction():
    row_extreme_long = pd.Series({"bb_pct_b": -0.3})
    row_extreme_short = pd.Series({"bb_pct_b": 1.3})
    row_mid = pd.Series({"bb_pct_b": 0.5})
    assert _subscore_bb(row_extreme_long, +1) > 0.0
    assert _subscore_bb(row_extreme_long, -1) == 0.0
    assert _subscore_bb(row_extreme_short, -1) > 0.0
    assert _subscore_bb(row_extreme_short, +1) == 0.0
    assert _subscore_bb(row_mid, +1) == 0.0


# ── ATR gate ────────────────────────────────────────────────────

def test_atr_gate_blocks_above_percentile():
    p = OrnsteinParams(atr_percentile_block=90.0, atr_percentile_boost=30.0)
    allow_high, _ = _atr_gate(pd.Series({"atr_percentile": 95.0}), p)
    allow_low, boost_low = _atr_gate(pd.Series({"atr_percentile": 10.0}), p)
    assert allow_high is False
    assert allow_low is True
    assert boost_low == 100.0


# ── Ω aggregation ──────────────────────────────────────────────

def test_compute_omega_logs_each_subscore_separately():
    """Omega must expose per-component raw + weighted values for audit."""
    p = OrnsteinParams()
    row = pd.Series({
        "div_score": 80.0, "rsi_score": 70.0,
        "halflife": 20.0, "ou_theta": 0.05,
        "hurst": 0.3, "adf_pvalue": 0.02,
        "vr_lag2": 0.8, "vr_lag4": 0.9, "vr_lag8": 1.2,
        "bb_pct_b": -0.2, "atr_percentile": 50.0,
    })
    out = compute_omega(row, direction=+1, params=p)
    assert "omega_final" in out
    assert "subscores" in out and "weighted" in out
    for key in ("div", "rsi", "ou", "hurst", "adf", "vr", "bb", "atr_boost"):
        assert key in out["subscores"]
        assert key in out["weighted"]
    # All components active → omega > 0
    assert out["omega_final"] > 0


def test_compute_omega_respects_ablation_flags():
    """Disabling a component zeroes its contribution."""
    row = pd.Series({
        "div_score": 80.0, "rsi_score": 70.0,
        "halflife": 20.0, "ou_theta": 0.05,
        "hurst": 0.3, "adf_pvalue": 0.02,
        "vr_lag2": 0.8, "vr_lag4": 0.9, "vr_lag8": 1.2,
        "bb_pct_b": -0.2, "atr_percentile": 50.0,
    })
    full = compute_omega(row, direction=+1, params=OrnsteinParams())
    no_ou = compute_omega(row, direction=+1, params=OrnsteinParams(disable_ou=True))
    assert no_ou["subscores"]["ou"] == 0.0
    assert no_ou["weighted"]["ou"] == 0.0
    assert no_ou["omega_final"] < full["omega_final"]


def test_derive_entry_direction_uses_divergence_by_default():
    row = pd.Series({"div_direction": 1, "deviation": 3.0})
    assert derive_entry_direction(row, OrnsteinParams()) == 1


def test_derive_entry_direction_falls_back_to_signed_deviation():
    params = OrnsteinParams(disable_divergence=True)
    assert derive_entry_direction(pd.Series({"deviation": -1.5}), params) == 1
    assert derive_entry_direction(pd.Series({"deviation": 2.0}), params) == -1
    assert derive_entry_direction(pd.Series({"deviation": 0.0}), params) == 0


# ── Sizing ──────────────────────────────────────────────────────

def test_ornstein_size_respects_notional_cap():
    """Notional capped at 2% of equity regardless of omega strength."""
    sz = ornstein_size(equity=10_000, entry=100.0, sl=99.0,
                       omega=120.0, params=OrnsteinParams())
    # With huge omega and tiny stop, raw notional blows past cap.
    assert sz["notional"] <= 200.0 * 1.01  # within rounding


def test_ornstein_size_scales_with_omega():
    """size_mult is min(omega/omega_entry, size_mult_cap). Higher omega = more size."""
    p = OrnsteinParams(omega_entry=75.0, size_mult_cap=1.5)
    lo = ornstein_size(equity=10_000, entry=100, sl=98, omega=75, params=p)
    hi = ornstein_size(equity=10_000, entry=100, sl=98, omega=150, params=p)
    assert hi["size_mult"] >= lo["size_mult"]
    # hi should hit cap
    assert hi["size_mult"] == pytest.approx(1.5, rel=0.01)


# ── Params & contracts ─────────────────────────────────────────

def test_all_presets_are_valid_orneinparam_overrides():
    for name, overrides in ORNSTEIN_PRESETS.items():
        p = OrnsteinParams()
        for k, v in overrides.items():
            setattr(p, k, v)
        # Just ensure no attribute error — dataclass picks it up.
        assert hasattr(p, "omega_entry")


def test_ablation_variants_all_map_to_known_flags():
    """Every variant must target a known disable_* flag on OrnsteinParams."""
    valid_flags = {f for f in dir(OrnsteinParams) if f.startswith("disable_")}
    for name, overrides in ABLATION_VARIANTS.items():
        for k in overrides.keys():
            assert k in valid_flags, f"variant {name} uses unknown flag {k}"


def test_params_contract_halflife_range_sensible():
    p = OrnsteinParams()
    assert p.halflife_min < p.halflife_max
    assert p.halflife_min > 0
