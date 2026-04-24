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


# ─── New v2 fields: profit_usd_per_1k_24h + depth_pct_at_1k ──────────

def test_score_result_has_profit_field():
    res = score_opp(_make_pair())
    assert hasattr(res, "profit_usd_per_1k_24h")
    assert hasattr(res, "depth_pct_at_1k")


def test_profit_usd_per_1k_24h_formula():
    """profit = apr/100 * $1000 * 24/8760 - $3 (30bps fees_rt on $1k)."""
    # apr=60%  →  0.6 * 1000 * 24/8760 = 1.6438; fees_rt = 3  →  net ≈ -1.356
    res = score_opp(_make_pair(net_apr=60.0))
    expected = 0.60 * 1000.0 * (24.0 / 8760.0) - 3.0
    assert res.profit_usd_per_1k_24h == pytest.approx(expected, rel=1e-3)


def test_profit_high_apr_positive():
    # 300% APR → gross = 8.22/day, minus $3 fees = ~$5.22 net
    res = score_opp(_make_pair(net_apr=300.0))
    assert res.profit_usd_per_1k_24h is not None
    assert res.profit_usd_per_1k_24h > 0


def test_profit_none_when_apr_missing():
    res = score_opp({"symbol": "X"})
    assert res.profit_usd_per_1k_24h is None


def test_depth_pct_none_when_book_depth_missing():
    res = score_opp(_make_pair())
    # No book_depth field in the _make_pair fixture → None.
    assert res.depth_pct_at_1k is None


def test_depth_pct_computed_from_book_depth():
    # If book_depth_usd is present, return slippage-in-bps estimate.
    # Simple linear model: bps = 10_000 / (book_depth_usd / 1000)
    # book=$50k → 10_000/50 = 200 bps
    pair = _make_pair(book_depth_usd=50_000.0)
    res = score_opp(pair)
    assert res.depth_pct_at_1k == pytest.approx(200.0, rel=1e-3)


def test_depth_pct_deep_book_low_slippage():
    pair = _make_pair(book_depth_usd=10_000_000.0)
    res = score_opp(pair)
    # 10_000 / 10_000 = 1.0 bps
    assert res.depth_pct_at_1k == pytest.approx(1.0, rel=1e-3)


# ─── Robustness patches (2026-04-24): NaN guards + explicit-None APR fallthrough

def test_profit_explicit_none_apr_fallthrough():
    """net_apr=0.0 must NOT fallthrough to sibling apr field.

    With `or`-chain fallthrough, 0.0 is falsy and silently upgrades to the
    next candidate. The explicit-None helper keeps zero-APR zero.
    """
    # opp with net_apr=0.0 but apr=100.0 — the "or" chain used to return apr.
    # Explicit-None fallthrough keeps net_apr=0 → profit = -$3 (just the fees).
    res = score_opp({
        "symbol": "BTC", "short_venue": "binance", "long_venue": "bybit",
        "_type": "CC",
        "net_apr": 0.0,  # explicit zero — must win over sibling apr
        "apr": 100.0,
        "volume_24h_short": 30_000_000, "volume_24h_long": 30_000_000,
        "open_interest_short": 10_000_000, "open_interest_long": 10_000_000,
        "risk": "LOW",
    })
    # Zero APR → gross=0 → net = -fees_usd = -$3
    assert res.profit_usd_per_1k_24h == pytest.approx(-3.0, abs=1e-3)


def test_profit_nan_apr_returns_none():
    import math
    res = score_opp({
        "symbol": "X", "short_venue": "binance", "long_venue": "bybit",
        "_type": "CC", "net_apr": math.nan,
    })
    assert res.profit_usd_per_1k_24h is None


def test_depth_nan_returns_none():
    import math
    res = score_opp(_make_pair(book_depth_usd=math.nan))
    assert res.depth_pct_at_1k is None


def test_depth_inf_returns_none():
    import math
    res = score_opp(_make_pair(book_depth_usd=math.inf))
    assert res.depth_pct_at_1k is None


def test_breakeven_nan_apr_returns_none():
    import math
    res = score_opp({
        "symbol": "X", "short_venue": "binance", "long_venue": "bybit",
        "_type": "CC", "net_apr": math.nan,
    })
    assert res.breakeven_h is None
