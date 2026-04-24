"""Contract tests for core.arb_scoring — 6-factor arbitrage scorer.

Pure module (no I/O). Covers:

- _linear_clamp: None/≤floor → 0; ≥ceil → 100; mid → linear
- _log_norm: None/≤0/≤floor → 0; ≥ceil → 100; mid → log-linear
- _pair_min: both None → None; mixed → min of present
- _grade: GO / MAYBE / SKIP cutoffs match thresholds
- _weighted_score: missing factors redistribute weight, do not drag
  score to zero
- Individual factor scorers: shape of return, sensible mappings
- score_opp: ScoreResult with score in [0, 100], factors dict, grade
  consistent with score + thresholds
- score_batch: empty → []; preserves order; identical to sequential
  score_opp per element
"""
from __future__ import annotations

import pytest

from core.arb_scoring import (
    ScoreResult,
    _grade,
    _linear_clamp,
    _log_norm,
    _pair_min,
    _score_net_apr,
    _score_oi,
    _score_risk,
    _score_venue,
    _score_volume,
    _weighted_score,
    score_batch,
    score_opp,
)


# ────────────────────────────────────────────────────────────
# Normalisation primitives
# ────────────────────────────────────────────────────────────

class TestLinearClamp:
    def test_none_is_zero(self):
        assert _linear_clamp(None, 0, 10) == 0.0

    def test_below_floor_is_zero(self):
        assert _linear_clamp(-5, 0, 10) == 0.0
        assert _linear_clamp(0, 0, 10) == 0.0

    def test_above_ceil_is_one_hundred(self):
        assert _linear_clamp(20, 0, 10) == 100.0

    def test_midpoint_is_fifty(self):
        assert _linear_clamp(5, 0, 10) == pytest.approx(50.0)


class TestLogNorm:
    def test_none_and_zero_are_zero(self):
        assert _log_norm(None, 100, 10_000) == 0.0
        assert _log_norm(0, 100, 10_000) == 0.0

    def test_at_floor_is_zero(self):
        assert _log_norm(100, 100, 10_000) == 0.0

    def test_at_ceil_is_one_hundred(self):
        assert _log_norm(10_000, 100, 10_000) == 100.0

    def test_log_midpoint_is_fifty(self):
        # Between 100 and 10_000 in log-space, midpoint is 1000
        assert _log_norm(1000, 100, 10_000) == pytest.approx(50.0, rel=1e-3)


class TestPairMin:
    def test_both_none(self):
        assert _pair_min(None, None) is None

    def test_one_none_returns_other(self):
        assert _pair_min(5, None) == 5
        assert _pair_min(None, 7) == 7

    def test_both_present_returns_min(self):
        assert _pair_min(5, 3) == 3


# ────────────────────────────────────────────────────────────
# Grading
# ────────────────────────────────────────────────────────────

class TestGrade:
    TH = {"go": 70.0, "maybe": 40.0}

    def test_go_at_threshold(self):
        assert _grade(70.0, self.TH) == "GO"
        assert _grade(100.0, self.TH) == "GO"

    def test_maybe_range(self):
        assert _grade(69.99, self.TH) == "MAYBE"
        assert _grade(40.0, self.TH) == "MAYBE"

    def test_skip_below_maybe(self):
        assert _grade(39.99, self.TH) == "SKIP"
        assert _grade(0.0, self.TH) == "SKIP"


# ────────────────────────────────────────────────────────────
# Weighted composite
# ────────────────────────────────────────────────────────────

class TestWeightedScore:
    W = {"a": 0.5, "b": 0.3, "c": 0.2}

    def test_all_present_is_weighted_average(self):
        s = _weighted_score({"a": 100, "b": 100, "c": 100}, self.W)
        assert s == pytest.approx(100.0)

    def test_all_missing_is_zero(self):
        s = _weighted_score({"a": None, "b": None, "c": None}, self.W)
        assert s == 0.0

    def test_missing_factor_redistributes_weight(self):
        # With a missing, weights become b=0.3/0.5, c=0.2/0.5 renormalized.
        # Two 100s → composite stays 100 (not penalized for missing factor).
        s = _weighted_score({"a": None, "b": 100, "c": 100}, self.W)
        assert s == pytest.approx(100.0)

    def test_mixed_values_renormalized(self):
        # b=100, c=0 → score = 100*0.6 + 0*0.4 = 60 (weights 0.3 and 0.2 of 0.5)
        s = _weighted_score({"a": None, "b": 100, "c": 0}, self.W)
        assert s == pytest.approx(60.0)


# ────────────────────────────────────────────────────────────
# Factor scorers
# ────────────────────────────────────────────────────────────

class TestFactorScorers:
    def test_net_apr_missing_returns_none(self):
        assert _score_net_apr({}) is None

    def test_net_apr_uses_abs(self):
        # Negative APR still yields a positive score (treat as magnitude)
        assert _score_net_apr({"net_apr": -50.0}) == pytest.approx(50.0)

    def test_net_apr_fallback_to_apr_key(self):
        assert _score_net_apr({"apr": 100.0}) == pytest.approx(100.0)

    def test_volume_missing_returns_none(self):
        assert _score_volume({}) is None

    def test_volume_uses_min_of_pair_legs(self):
        opp = {"volume_24h_short": 1_000_000, "volume_24h_long": 100_000}
        # The worse leg at 100k is at the floor → 0
        assert _score_volume(opp) == 0.0

    def test_oi_missing_returns_none(self):
        assert _score_oi({}) is None

    def test_risk_mapping(self):
        assert _score_risk({"risk": "LOW"})  == 100.0
        assert _score_risk({"risk": "MED"})  == 50.0
        assert _score_risk({"risk": "HIGH"}) == 0.0
        assert _score_risk({"risk": "low"})  == 100.0  # case-insensitive
        assert _score_risk({}) is None

    def test_venue_missing_returns_none(self):
        assert _score_venue({}, {"binance": 99}) is None

    def test_venue_lookup_unknown_returns_none(self):
        # No known venue → all scores filtered out → None
        assert _score_venue({"venue": "madeup"}, {"binance": 99}) is None

    def test_venue_worst_leg_wins(self):
        # For pairs, worst reliability leg sets the score
        opp = {"venue_short": "binance", "venue_long": "paradex"}
        rel = {"binance": 99.0, "paradex": 90.0}
        # Worst = 90 → floor → 0
        assert _score_venue(opp, rel) == 0.0


# ────────────────────────────────────────────────────────────
# score_opp (top-level)
# ────────────────────────────────────────────────────────────

class TestScoreOpp:
    def test_returns_scoreresult_shape(self):
        r = score_opp({"net_apr": 50.0, "volume_24h": 1_000_000,
                       "open_interest": 500_000, "risk": "LOW",
                       "venue": "binance"})
        assert isinstance(r, ScoreResult)
        assert 0.0 <= r.score <= 100.0
        assert r.grade in ("GO", "MAYBE", "SKIP")
        assert set(r.factors.keys()) == {
            "net_apr", "volume", "oi", "risk", "slippage", "venue",
        }

    def test_grade_consistent_with_score(self):
        r = score_opp({"net_apr": 80.0, "volume_24h": 10_000_000,
                       "open_interest": 5_000_000, "risk": "LOW",
                       "venue": "binance"})
        # Near-ideal opportunity → GO
        assert r.grade == "GO"
        assert r.score >= 70.0

    def test_empty_opp_gives_zero_score(self):
        r = score_opp({})
        assert r.score == 0.0
        assert r.grade == "SKIP"
        assert all(v is None for v in r.factors.values())


# ────────────────────────────────────────────────────────────
# score_batch
# ────────────────────────────────────────────────────────────

class TestScoreBatch:
    def test_empty_list(self):
        assert score_batch([]) == []

    def test_preserves_order(self):
        opps = [
            {"net_apr": 10, "risk": "HIGH"},
            {"net_apr": 80, "risk": "LOW"},
            {"net_apr": 50, "risk": "MED"},
        ]
        results = score_batch(opps)
        expected = [score_opp(o) for o in opps]
        assert [r.score for r in results] == [r.score for r in expected]
        assert [r.grade for r in results] == [r.grade for r in expected]

    def test_cfg_applied_consistently(self):
        opps = [{"net_apr": 50, "risk": "LOW"}]
        cfg = {"thresholds": {"go": 10.0, "maybe": 5.0}}
        results = score_batch(opps, cfg=cfg)
        # With loose thresholds, even a modest score should grade GO
        assert results[0].grade == "GO"
