"""Contract tests for core.chronos — time-series intelligence layer.

Covers:
- GaussianHMMNp: fit/predict_proba/predict on synthetic regimes;
  probabilities sum to ~1; predicted states in [0, n_states)
- enrich_with_regime: idempotent when columns present; returns all
  HMM_COLS (possibly NaN); NaN when data below min warmup; valid
  probs in [0, 1]; regime_label in {BULL, BEAR, CHOP, None}
- momentum_decay: pure column adder; in [-3, 3]; no NaN in output
- hurst_rolling: pure column adder; H in [0, 1] where populated
- seasonality_score: without 'time' column → 0.0; with 'time' →
  score in [-1, 1]
- ChronosFeatures.available_features: reports all 5 keys with bool
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from core.chronos import (
    HMM_COLS,
    ChronosFeatures,
    GaussianHMMNp,
    enrich_with_regime,
    hurst_rolling,
    momentum_decay,
    seasonality_score,
)


def _make_ohlcv(n: int = 400, seed: int = 42) -> pd.DataFrame:
    """Synthetic price series with 3 regimes (drift up / flat / down)."""
    rng = np.random.default_rng(seed)
    # Three regimes: 150 bars each of positive drift, flat, negative drift
    drifts = np.concatenate([
        rng.normal(0.002, 0.01, n // 3),          # bull
        rng.normal(0.000, 0.005, n // 3),         # chop
        rng.normal(-0.002, 0.01, n - 2 * (n // 3)),  # bear
    ])
    price = 100 * np.exp(np.cumsum(drifts))
    df = pd.DataFrame({
        "close": price,
        "open":  price * (1 + rng.normal(0, 0.001, n)),
        "high":  price * (1 + np.abs(rng.normal(0, 0.002, n))),
        "low":   price * (1 - np.abs(rng.normal(0, 0.002, n))),
        "vol":   rng.uniform(100, 1000, n),
        "tbb":   rng.uniform(40, 600, n),
        "time":  pd.date_range("2025-01-01", periods=n, freq="15min"),
    })
    return df


# ────────────────────────────────────────────────────────────
# GaussianHMMNp
# ────────────────────────────────────────────────────────────

class TestGaussianHMMNp:
    def test_fit_then_predict_proba_shape(self):
        rng = np.random.default_rng(0)
        X = rng.normal(0, 1, (200, 2))
        hmm = GaussianHMMNp(n_states=3, n_iter=20, random_state=0)
        hmm.fit(X)
        proba = hmm.predict_proba(X)
        assert proba.shape == (200, 3)

    def test_probabilities_sum_to_one(self):
        rng = np.random.default_rng(1)
        X = rng.normal(0, 1, (150, 2))
        hmm = GaussianHMMNp(n_states=3, n_iter=20, random_state=1)
        hmm.fit(X)
        sums = hmm.predict_proba(X).sum(axis=1)
        assert np.allclose(sums, 1.0, atol=1e-6)

    def test_predict_returns_state_indices(self):
        rng = np.random.default_rng(2)
        X = rng.normal(0, 1, (100, 2))
        hmm = GaussianHMMNp(n_states=3, n_iter=15, random_state=2)
        hmm.fit(X)
        states = hmm.predict(X)
        assert states.dtype.kind in ("i", "u")  # integer
        assert (0 <= states).all() and (states < 3).all()

    def test_handles_single_state_fit(self):
        # K=1 is a trivial case — fit should not iterate or diverge
        X = np.random.default_rng(3).normal(0, 1, (50, 2))
        hmm = GaussianHMMNp(n_states=1, n_iter=10, random_state=3)
        hmm.fit(X)
        proba = hmm.predict_proba(X)
        assert proba.shape == (50, 1)
        assert np.allclose(proba, 1.0)


# ────────────────────────────────────────────────────────────
# enrich_with_regime
# ────────────────────────────────────────────────────────────

class TestEnrichWithRegime:
    def test_adds_all_hmm_columns(self):
        df = _make_ohlcv(n=400)
        out = enrich_with_regime(df, n_states=3, lookback=300)
        for col in HMM_COLS:
            assert col in out.columns

    def test_idempotent_when_columns_exist(self):
        df = _make_ohlcv(n=400)
        first = enrich_with_regime(df, n_states=3, lookback=300)
        # Second call: every HMM_COL already present → early return
        second = enrich_with_regime(first, n_states=3, lookback=300)
        assert second is first

    def test_nan_when_below_min_warmup(self):
        # min_warmup = max(n_states*20, 80) → for n_states=3, 80 bars min.
        df = _make_ohlcv(n=40)  # way below min
        out = enrich_with_regime(df, n_states=3, lookback=300)
        # All rows should have NaN probs
        assert out["hmm_prob_bull"].isna().all()

    def test_missing_close_returns_nan_columns(self):
        df = pd.DataFrame({"open": [1, 2, 3]})
        out = enrich_with_regime(df, n_states=3, lookback=300)
        assert "hmm_prob_bull" in out.columns
        assert out["hmm_prob_bull"].isna().all()

    def test_probs_in_unit_interval_when_populated(self):
        df = _make_ohlcv(n=400)
        out = enrich_with_regime(df, n_states=3, lookback=300)
        for col in ("hmm_prob_bull", "hmm_prob_bear", "hmm_prob_chop"):
            populated = out[col].dropna()
            if len(populated) > 0:
                assert ((0.0 <= populated) & (populated <= 1.0)).all()

    def test_regime_label_in_expected_set(self):
        df = _make_ohlcv(n=400)
        out = enrich_with_regime(df, n_states=3, lookback=300)
        labels = set(out["hmm_regime_label"].dropna().unique())
        assert labels <= {"BULL", "BEAR", "CHOP"}


# ────────────────────────────────────────────────────────────
# momentum_decay
# ────────────────────────────────────────────────────────────

class TestMomentumDecay:
    def test_adds_column(self):
        df = _make_ohlcv(n=300)
        out = momentum_decay(df)
        assert "momentum_decay" in out.columns

    def test_values_clipped_to_unit_range(self):
        df = _make_ohlcv(n=300)
        out = momentum_decay(df)
        vals = out["momentum_decay"]
        assert vals.min() >= -3.0
        assert vals.max() <= 3.0

    def test_no_nan_in_output(self):
        df = _make_ohlcv(n=300)
        out = momentum_decay(df)
        assert not out["momentum_decay"].isna().any()


# ────────────────────────────────────────────────────────────
# hurst_rolling
# ────────────────────────────────────────────────────────────

class TestHurstRolling:
    def test_adds_column(self):
        df = _make_ohlcv(n=200)
        out = hurst_rolling(df, window=80, min_periods=40)
        assert "hurst_rolling" in out.columns

    def test_values_in_unit_range_where_populated(self):
        df = _make_ohlcv(n=200)
        out = hurst_rolling(df, window=80, min_periods=40)
        populated = out["hurst_rolling"].dropna()
        assert len(populated) > 0
        assert ((0.0 <= populated) & (populated <= 1.0)).all()


# ────────────────────────────────────────────────────────────
# seasonality_score
# ────────────────────────────────────────────────────────────

class TestSeasonalityScore:
    def test_returns_zero_without_time_column(self):
        df = pd.DataFrame({"close": [1, 2, 3, 4, 5]})
        out = seasonality_score(df)
        assert "seasonality_score" in out.columns
        assert (out["seasonality_score"] == 0.0).all()

    def test_values_clipped_to_unit_range(self):
        df = _make_ohlcv(n=2000)
        out = seasonality_score(df, min_samples=30)
        vals = out["seasonality_score"]
        assert vals.min() >= -1.0
        assert vals.max() <= 1.0


# ────────────────────────────────────────────────────────────
# ChronosFeatures.available_features
# ────────────────────────────────────────────────────────────

class TestAvailableFeatures:
    def test_reports_all_five_features(self):
        avail = ChronosFeatures.available_features()
        expected = {
            "regime_probability (HMM)",
            "volatility_forecast (GARCH)",
            "momentum_decay",
            "hurst_rolling",
            "seasonality_score",
        }
        assert set(avail.keys()) == expected

    def test_pure_numpy_features_always_true(self):
        avail = ChronosFeatures.available_features()
        assert avail["momentum_decay"] is True
        assert avail["hurst_rolling"] is True
        assert avail["seasonality_score"] is True
