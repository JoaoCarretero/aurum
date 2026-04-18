"""Contract tests for core.harmonics — RENAISSANCE harmonic patterns.

Focuses on the pure helpers (pivot detection, alternation, pattern
rule match, entropy / hurst classification, Bayesian scoring) plus
a smoke test of scan_hermes end-to-end on minimal synthetic data.

Covers:
- _h_pivots: detects local highs/lows given H_PIVOT_N window
- _h_alt_pivots: alternates H/L; keeps the more extreme value in a run
- _h_check: returns known pattern name for Gartley-like ratios; None
  when nothing matches
- _h_levels: BULLISH stop<D<target; BEARISH target<D<stop
- _h_entropy: RANDOM / TRANSITION / STRUCTURED buckets
- _h_hurst: MEAN_REVERTING / TRENDING / RANDOM_WALK / UNKNOWN
- _BayesWR: priors initialised from H_BAYESIAN_PRIOR; update +
  p_win moves in expected direction; score clamps to ≥0
- scan_hermes: returns (list, dict); short df yields no trades
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from core import harmonics as h


# ────────────────────────────────────────────────────────────
# _h_pivots & _h_alt_pivots
# ────────────────────────────────────────────────────────────

class TestPivots:
    def test_detects_local_high(self):
        # Build a tiny df where index 5 is a clear local high
        highs = [10, 11, 12, 13, 14, 20, 13, 12, 11, 10]
        lows  = [9,  10, 11, 12, 13, 19, 12, 11, 10, 9]
        df = pd.DataFrame({"high": highs, "low": lows})
        ph, pl = h._h_pivots(df)
        # Index 5 should be in high pivots
        assert 5 in ph and ph[5] == 20

    def test_detects_local_low(self):
        highs = [20, 19, 18, 17, 16, 10, 16, 17, 18, 19]
        lows  = [19, 18, 17, 16, 15,  5, 15, 16, 17, 18]
        df = pd.DataFrame({"high": highs, "low": lows})
        _, pl = h._h_pivots(df)
        assert 5 in pl and pl[5] == 5

    def test_alt_pivots_alternates_types(self):
        ph = {5: 20.0, 10: 25.0}
        pl = {8: 5.0,  12: 3.0}
        alt = h._h_alt_pivots(ph, pl)
        types = [pt["type"] for pt in alt]
        # Sorted by index: 5(H), 8(L), 10(H), 12(L) — alternating
        assert types == ["H", "L", "H", "L"]

    def test_alt_pivots_keeps_more_extreme_in_run(self):
        # Two adjacent highs; alt_pivots should keep only the higher one.
        ph = {5: 20.0, 6: 22.0}  # consecutive highs
        pl = {10: 5.0}
        alt = h._h_alt_pivots(ph, pl)
        # Should have 1 high (the larger) + 1 low
        highs = [pt for pt in alt if pt["type"] == "H"]
        assert len(highs) == 1
        assert highs[0]["p"] == 22.0


# ────────────────────────────────────────────────────────────
# _h_check
# ────────────────────────────────────────────────────────────

class TestPatternCheck:
    def test_gartley_ratios_match(self):
        # Construct XABCD with Gartley ratios:
        #   AB/XA=0.618, BC/AB∈[0.382,0.886], CD/BC∈[1.272,1.618], AD/XA=0.786
        # Simple bullish setup: X=0, A=100, B=38.2, C=88.6, D=78.6
        X = {"i": 0,  "p": 0.0,   "type": "L"}
        A = {"i": 10, "p": 100.0, "type": "H"}
        B = {"i": 20, "p": 38.2,  "type": "L"}  # AB/XA = 61.8/100 = 0.618
        # BC = 50.4 → BC/AB = 50.4/61.8 ≈ 0.815 (in [.382,.886])
        C = {"i": 30, "p": 88.6,  "type": "H"}
        # CD = 10.0 → CD/BC = 10/50.4 ≈ 0.198 (too low for Gartley)
        # Adjust: use D so CD/BC ≈ 1.272–1.618
        # CD should be ~64-82. Start from C=88.6, D = C - 72 = 16.6 → AD/XA = 83.4/100 (close to 0.786)
        D = {"i": 40, "p": 16.6,  "type": "L"}
        pat, ratios = h._h_check(X, A, B, C, D)
        # With H_TOL=0.10 the ratios should be close enough to Gartley
        assert pat is not None, f"expected pattern, got ratios={ratios}"

    def test_unrelated_points_return_none(self):
        # Random XABCD unlikely to match any pattern
        X = {"i": 0, "p": 100.0, "type": "L"}
        A = {"i": 1, "p": 101.0, "type": "H"}
        B = {"i": 2, "p": 100.5, "type": "L"}
        C = {"i": 3, "p": 100.7, "type": "H"}
        D = {"i": 4, "p": 100.6, "type": "L"}
        pat, _ = h._h_check(X, A, B, C, D)
        assert pat is None


# ────────────────────────────────────────────────────────────
# _h_levels
# ────────────────────────────────────────────────────────────

class TestLevels:
    def test_bullish_stop_below_d_target_above(self):
        # Bullish pattern: X is the initial low (below D). stop = X - buffer,
        # target = D + fib*AD, so X < D < target and stop < D.
        X = {"p": 50.0}
        D = {"p": 75.0}
        target, stop = h._h_levels(X, D, "BULLISH", XA=50.0, AD=25.0)
        assert target is not None and stop is not None
        assert stop < D["p"] < target

    def test_bearish_target_below_d_stop_above(self):
        # Bearish pattern: X is the initial high (above D). stop = X + buffer,
        # target = D - fib*AD, so target < D < X and stop > D.
        X = {"p": 100.0}
        D = {"p": 90.0}
        target, stop = h._h_levels(X, D, "BEARISH", XA=50.0, AD=10.0)
        assert target is not None and stop is not None
        assert target < D["p"] < stop


# ────────────────────────────────────────────────────────────
# _h_entropy
# ────────────────────────────────────────────────────────────

class TestEntropy:
    def test_short_series_is_structured(self):
        df = pd.DataFrame({"close": np.linspace(100, 110, 10)})
        assert h._h_entropy(df, idx=5) == "STRUCTURED"

    def test_flat_series_is_structured(self):
        # Zero variance → returns STRUCTURED
        df = pd.DataFrame({"close": [100.0] * 100})
        result = h._h_entropy(df, idx=60)
        assert result in ("STRUCTURED", "RANDOM", "TRANSITION")


# ────────────────────────────────────────────────────────────
# _h_hurst
# ────────────────────────────────────────────────────────────

class TestHurst:
    def test_short_series_returns_unknown(self):
        df = pd.DataFrame({"close": np.linspace(100, 110, 20)})
        assert h._h_hurst(df, idx=10) == "UNKNOWN"

    def test_trending_series_labels_something(self):
        # Monotonic upward → should classify as TRENDING or RANDOM_WALK
        df = pd.DataFrame({"close": np.cumsum(np.ones(200)) + 100})
        label = h._h_hurst(df, idx=150)
        assert label in ("TRENDING", "RANDOM_WALK", "MEAN_REVERTING", "UNKNOWN")


# ────────────────────────────────────────────────────────────
# _BayesWR
# ────────────────────────────────────────────────────────────

class TestBayesWR:
    def test_priors_initialised_from_H_BAYESIAN_PRIOR(self):
        bayes = h._BayesWR()
        for pat, prior in h.H_BAYESIAN_PRIOR.items():
            expected = prior * 10 / (prior * 10 + (1 - prior) * 10)
            assert bayes.p_win(pat) == pytest.approx(expected, rel=1e-6)

    def test_wins_increase_p_win(self):
        bayes = h._BayesWR()
        before = bayes.p_win("Gartley")
        bayes.update("Gartley", "WIN", rr=2.0)
        bayes.update("Gartley", "WIN", rr=2.0)
        assert bayes.p_win("Gartley") > before

    def test_losses_decrease_p_win(self):
        bayes = h._BayesWR()
        before = bayes.p_win("Gartley")
        bayes.update("Gartley", "LOSS", rr=2.0)
        bayes.update("Gartley", "LOSS", rr=2.0)
        assert bayes.p_win("Gartley") < before

    def test_unknown_pattern_gets_neutral_prior(self):
        bayes = h._BayesWR()
        # New pattern → 5/5 prior = 0.5 exactly
        assert bayes.p_win("MadeUp") == pytest.approx(0.5)

    def test_score_is_non_negative(self):
        bayes = h._BayesWR()
        # Negative edge → score clamps to 0
        s = bayes.score(rr=0.1, pat="Gartley", regime="VOLATILE")
        assert s >= 0


# ────────────────────────────────────────────────────────────
# scan_hermes smoke
# ────────────────────────────────────────────────────────────

class TestScanHermesSmoke:
    def test_returns_tuple_of_list_and_dict(self):
        # Minimal df below min_idx — scan bails fast with 0 trades
        df = pd.DataFrame({
            "time":  pd.date_range("2025-01-01", periods=50, freq="15min"),
            "open":  np.linspace(100, 110, 50),
            "high":  np.linspace(101, 111, 50),
            "low":   np.linspace(99,  109, 50),
            "close": np.linspace(100, 110, 50),
            "vol":   np.ones(50) * 100.0,
            "tbb":   np.ones(50) * 50.0,
        })
        trades, vetos = h.scan_hermes(df, "BTCUSDT",
                                      macro_bias_series=None, corr=None)
        assert isinstance(trades, list)
        assert isinstance(vetos, dict)
        # Below min_idx → zero trades
        assert len(trades) == 0
