"""tests/test_arb_scoring.py
Unit tests for core/arb_scoring.py — 6-factor composite scoring engine.
TDD: written before implementation.
"""
import pytest
from core.arb_scoring import (
    ScoreResult,
    score_opp,
    score_batch,
    _log_norm,
    _linear_clamp,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_opp(**overrides) -> dict:
    """Sensible defaults for a single-leg funding opportunity."""
    base = {
        "symbol":       "BTC",
        "venue":        "binance",
        "apr":          80.0,        # strong APR
        "volume_24h":   50_000_000,  # very liquid
        "open_interest": 20_000_000, # deep OI
        "risk":         "LOW",
    }
    base.update(overrides)
    return base


def _make_pair(**overrides) -> dict:
    """Sensible defaults for a funding-arb pair (two legs)."""
    base = {
        "symbol":              "ETH",
        "venue_short":         "binance",
        "venue_long":          "hyperliquid",
        "net_apr":             60.0,
        "volume_24h_short":    30_000_000,
        "volume_24h_long":     20_000_000,
        "open_interest_short": 10_000_000,
        "open_interest_long":   8_000_000,
        "risk":                "LOW",
    }
    base.update(overrides)
    return base


# ─── Tests ───────────────────────────────────────────────────────────────────

def test_score_opp_all_fields_present():
    """Strong opportunity with all fields → GO, score ≥ 70."""
    opp = _make_opp()
    result = score_opp(opp)
    assert isinstance(result, ScoreResult)
    assert result.grade == "GO"
    assert result.score >= 70.0
    assert "net_apr" in result.factors


def test_score_opp_missing_volume():
    """volume_24h=None → weight redistributed, score lower but > 0."""
    full   = score_opp(_make_opp())
    no_vol = score_opp(_make_opp(volume_24h=None))
    assert no_vol.score > 0
    assert no_vol.score < full.score


def test_score_opp_all_missing():
    """Empty dict → score 0, grade SKIP."""
    result = score_opp({})
    assert result.score == 0.0
    assert result.grade == "SKIP"


def test_grade_threshold_boundary_skip():
    """Weak opportunity (low APR, low liquidity, HIGH risk) → SKIP."""
    opp = _make_opp(
        apr=5.0,
        volume_24h=200_000,
        open_interest=60_000,
        risk="HIGH",
        venue="paradex",  # reliability 90 → floor
    )
    result = score_opp(opp)
    assert result.grade == "SKIP"
    assert result.score < 40.0


def test_grade_threshold_boundary_go():
    """Excellent opportunity → GO, score ≥ 70."""
    opp = _make_opp(
        apr=150.0,
        volume_24h=100_000_000,
        open_interest=50_000_000,
        risk="LOW",
        venue="binance",
    )
    result = score_opp(opp)
    assert result.grade == "GO"
    assert result.score >= 70.0


def test_score_batch_parallel():
    """score_batch returns one result per opp; strong comes first when sorted."""
    strong = _make_opp(apr=120.0, volume_24h=80_000_000)
    weak   = _make_opp(apr=10.0,  volume_24h=300_000, risk="HIGH")
    results = score_batch([strong, weak])
    assert len(results) == 2
    # Order preserved (not auto-sorted) — caller sorts
    assert results[0].score > results[1].score


def test_arb_pair_weakest_link():
    """Weak leg drags pair score below a strong single-leg equivalent."""
    strong_pair = _make_pair()
    weak_pair   = _make_pair(
        volume_24h_long=50_000,      # tiny long leg → volume drags
        open_interest_long=30_000,
        venue_long="paradex",        # lowest reliability
    )
    r_strong = score_opp(strong_pair)
    r_weak   = score_opp(weak_pair)
    assert r_strong.score > r_weak.score


def test_weights_normalize():
    """Custom weights summing to 6.0 (not 1.0) still produce valid score."""
    big_weights = {
        "net_apr":  1.80,
        "volume":   1.20,
        "oi":       0.90,
        "risk":     0.90,
        "slippage": 0.60,
        "venue":    0.60,
    }
    cfg = {"weights": big_weights}
    result = score_opp(_make_opp(), cfg=cfg)
    assert 0.0 <= result.score <= 100.0
    assert result.grade in ("GO", "MAYBE", "SKIP")


def test_log_norm_boundaries():
    """_log_norm: at/below floor=0, at/above ceil=100, mid≈50."""
    assert _log_norm(0,   floor=100, ceil=10_000_000) == 0.0
    assert _log_norm(50,  floor=100, ceil=10_000_000) == 0.0   # below floor
    assert _log_norm(10_000_000, floor=100, ceil=10_000_000) == 100.0
    assert _log_norm(99_000_000, floor=100, ceil=10_000_000) == 100.0  # above ceil
    mid = _log_norm(1_000, floor=100, ceil=10_000_000)
    assert 0 < mid < 100


def test_linear_clamp_boundaries():
    """_linear_clamp: at/below floor=0, at/above ceil=100, mid linear."""
    assert _linear_clamp(0,   floor=0, ceil=100) == 0.0
    assert _linear_clamp(100, floor=0, ceil=100) == 100.0
    assert _linear_clamp(-5,  floor=0, ceil=100) == 0.0
    assert _linear_clamp(200, floor=0, ceil=100) == 100.0
    assert _linear_clamp(50,  floor=0, ceil=100) == pytest.approx(50.0)
