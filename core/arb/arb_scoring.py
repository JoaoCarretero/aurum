"""core/arb_scoring.py
AURUM Finance — 6-factor composite scoring engine for arbitrage opportunities.

Scores a single opportunity (or arb pair) on a 0-100 scale across six factors:
  net_apr · volume · oi · risk · slippage · venue

Returns a ScoreResult with score, grade (GO/MAYBE/SKIP), and per-factor breakdown.

Pure module: no I/O, no network, no side effects.
"""
from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

# ─── Defaults (overridden by params.py when available) ───────────────────────

_DEFAULT_WEIGHTS: dict[str, float] = {
    "net_apr":  0.30,
    "volume":   0.20,
    "oi":       0.15,
    "risk":     0.15,
    "slippage": 0.10,
    "venue":    0.10,
}

_DEFAULT_THRESHOLDS: dict[str, float] = {
    "go":    70.0,
    "maybe": 40.0,
}

# Reliability score 0-100 per venue (higher = more trusted)
_DEFAULT_VENUE_RELIABILITY: dict[str, float] = {
    "binance":      99.0,
    "bybit":        97.0,
    "gate":         95.0,
    "bitget":       94.0,
    "bingx":        92.0,
    "hyperliquid":  96.0,
    "dydx":         94.0,
    "paradex":      90.0,
}

_DEFAULT_POS_SIZE_REF = 1_000.0   # USD reference position for slippage ratio


def _resolve_cfg(cfg: dict | None) -> dict:
    """Merge user-supplied cfg with defaults from params.py (or hardcoded fallback)."""
    try:
        from config.params import (
            ARB_SCORE_WEIGHTS,
            ARB_SCORE_THRESHOLDS,
            ARB_VENUE_RELIABILITY,
            ARB_POS_SIZE_REF,
        )
        defaults = {
            "weights":          ARB_SCORE_WEIGHTS,
            "thresholds":       ARB_SCORE_THRESHOLDS,
            "venue_reliability": ARB_VENUE_RELIABILITY,
            "pos_size_ref":     ARB_POS_SIZE_REF,
        }
    except (ImportError, AttributeError):
        defaults = {
            "weights":          _DEFAULT_WEIGHTS,
            "thresholds":       _DEFAULT_THRESHOLDS,
            "venue_reliability": _DEFAULT_VENUE_RELIABILITY,
            "pos_size_ref":     _DEFAULT_POS_SIZE_REF,
        }

    if cfg:
        # Shallow-merge: caller can override individual sub-dicts
        merged = dict(defaults)
        for k, v in cfg.items():
            if isinstance(v, dict) and isinstance(merged.get(k), dict):
                merged[k] = {**merged[k], **v}
            else:
                merged[k] = v
        return merged
    return defaults


# ─── Normalisation primitives ─────────────────────────────────────────────────

def _linear_clamp(value: float | None, floor: float, ceil: float) -> float:
    """Linear 0-100 clamp between floor and ceil.

    Returns 0 if value <= floor, 100 if value >= ceil, linear between.
    None is treated as floor (returns 0).
    """
    if value is None:
        return 0.0
    if value <= floor:
        return 0.0
    if value >= ceil:
        return 100.0
    return (value - floor) / (ceil - floor) * 100.0


def _log_norm(value: float | None, floor: float, ceil: float) -> float:
    """Logarithmic 0-100 normalisation between floor and ceil.

    Returns 0 if value <= floor, 100 if value >= ceil, linear in log10 between.
    None is treated as <= floor (returns 0).
    """
    if value is None or value <= 0:
        return 0.0
    log_val  = math.log10(max(value, 1e-12))
    log_floor = math.log10(max(floor, 1e-12))
    log_ceil  = math.log10(max(ceil,  1e-12))
    if log_val <= log_floor:
        return 0.0
    if log_val >= log_ceil:
        return 100.0
    return (log_val - log_floor) / (log_ceil - log_floor) * 100.0


# ─── Factor scorers ──────────────────────────────────────────────────────────

def _score_net_apr(opp: dict) -> float | None:
    """net_apr or apr field → linear clamp 0-100% APR → 100."""
    apr = opp.get("net_apr") or opp.get("apr")
    if apr is None:
        return None
    return _linear_clamp(abs(apr), floor=0.0, ceil=100.0)


def _score_volume(opp: dict) -> float | None:
    """volume_24h (or min of pair legs) → log norm <100k→0, ≥10M→100."""
    if "volume_24h_short" in opp or "volume_24h_long" in opp:
        vs = opp.get("volume_24h_short")
        vl = opp.get("volume_24h_long")
        vol = _pair_min(vs, vl)
    else:
        vol = opp.get("volume_24h")

    if vol is None:
        return None
    return _log_norm(vol, floor=100_000, ceil=10_000_000)


def _score_oi(opp: dict) -> float | None:
    """open_interest (or min of pair legs) → log norm <50k→0, ≥5M→100."""
    if "open_interest_short" in opp or "open_interest_long" in opp:
        os_ = opp.get("open_interest_short")
        ol  = opp.get("open_interest_long")
        oi  = _pair_min(os_, ol)
    else:
        oi = opp.get("open_interest")

    if oi is None:
        return None
    return _log_norm(oi, floor=50_000, ceil=5_000_000)


def _score_risk(opp: dict) -> float | None:
    """risk field: LOW=100, MED=50, HIGH=0. None→None (missing)."""
    risk = opp.get("risk")
    if risk is None:
        return None
    mapping = {"LOW": 100.0, "MED": 50.0, "HIGH": 0.0}
    return mapping.get(str(risk).upper())


def _score_slippage(opp: dict, pos_size_ref: float) -> float | None:
    """volume_24h / pos_size_ref ratio → linear: ≤5x→0, ≥100x→100."""
    # Use worst-case volume for pairs
    if "volume_24h_short" in opp or "volume_24h_long" in opp:
        vs = opp.get("volume_24h_short")
        vl = opp.get("volume_24h_long")
        vol = _pair_min(vs, vl)
    else:
        vol = opp.get("volume_24h")

    if vol is None or pos_size_ref <= 0:
        return None
    ratio = vol / pos_size_ref
    return _linear_clamp(ratio, floor=5.0, ceil=100.0)


def _score_venue(opp: dict, venue_reliability: dict[str, float]) -> float | None:
    """Venue reliability lookup → linear: ≤90→0, ≥99→100."""
    # For pairs, use the worst (lowest reliability) venue. Accept both
    # short_venue/long_venue (arb_pairs output) and venue_short/venue_long
    # (legacy/basis output).
    venues = []
    for key in ("venue", "short_venue", "long_venue",
                "venue_short", "venue_long",
                "venue_perp", "venue_spot", "venue_a", "venue_b"):
        v = opp.get(key)
        if v:
            venues.append(str(v).lower())

    if not venues:
        return None

    scores = [venue_reliability.get(v) for v in venues]
    scores = [s for s in scores if s is not None]
    if not scores:
        return None

    worst = min(scores)
    return _linear_clamp(worst, floor=90.0, ceil=99.0)


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _pair_min(a: float | None, b: float | None) -> float | None:
    """Return min of two values; None if both are None."""
    vals = [v for v in (a, b) if v is not None]
    return min(vals) if vals else None


def _grade(score: float, thresholds: dict) -> str:
    if score >= thresholds["go"]:
        return "GO"
    if score >= thresholds["maybe"]:
        return "MAYBE"
    return "SKIP"


def _weighted_score(factor_scores: dict[str, float | None], weights: dict[str, float]) -> float:
    """Compute weighted composite score.

    Missing factors (None) have their weight redistributed proportionally
    to the present factors.
    """
    present = {k: v for k, v in factor_scores.items() if v is not None}
    if not present:
        return 0.0

    total_weight = sum(weights.get(k, 0.0) for k in present)
    if total_weight == 0.0:
        return 0.0

    score = sum(
        v * weights.get(k, 0.0) / total_weight
        for k, v in present.items()
    ) * 100.0 / 100.0  # already 0-100 scale

    # The weights are normalised internally; the raw factor scores are 0-100.
    # Weighted average of 0-100 values = 0-100 composite.
    return score


# ─── Public API ───────────────────────────────────────────────────────────────

# Default round-trip fees (both legs, both sides) used when computing
# breakeven hours at the scorer level. Matches SimpleArbEngine defaults
# of 10 bps entry_fee + 5 bps slippage × 2 (open + close) = 30 bps RT.
_DEFAULT_RT_FEE_BPS = 30.0


def _apr_from_opp(opp: dict) -> float | None:
    """Read APR from an opp record, preferring net_apr → apr → basis_apr.

    Uses explicit-None fallthrough so a leg with net_apr=0.0 (zero funding,
    meaningful value) is NOT silently upgraded to a sibling field's APR.
    Returns None only when every candidate is missing (None).
    """
    for key in ("net_apr", "apr", "basis_apr"):
        v = opp.get(key)
        if v is not None:
            return float(v)
    return None


def _breakeven_hours(opp: dict, rt_fee_bps: float = _DEFAULT_RT_FEE_BPS) -> float | None:
    """Hours to recover round-trip fees at this opp's current APR.

    bkevn_h = fee_bps * 8760 / (100 * net_apr)
            = fee_bps * 87.6 / net_apr   (APR in %)
    """
    apr = _apr_from_opp(opp)
    if apr is None:
        return None
    a = abs(apr)
    if a <= 0 or not math.isfinite(a):
        return None
    return round(rt_fee_bps * 87.6 / a, 2)


def _profit_usd_per_1k_24h(opp: dict, rt_fee_bps: float = _DEFAULT_RT_FEE_BPS) -> float | None:
    """Net 24h profit on a $1,000 notional, after round-trip fees.

    gross = apr/100 * $1000 * 24/8760
    fees_rt_usd = rt_fee_bps/10_000 * $1000  (= $3 at 30 bps default)
    net = gross - fees_rt_usd

    Returns None if APR is missing. Can be negative (signals the edge
    doesn't cover fees at this size). Non-finite APR returns None.
    """
    apr = _apr_from_opp(opp)
    if apr is None or not math.isfinite(apr):
        return None
    gross = abs(apr) / 100.0 * 1000.0 * (24.0 / 8760.0)
    fees_usd = rt_fee_bps / 10_000.0 * 1000.0
    return round(gross - fees_usd, 4)


def _depth_pct_at_1k(opp: dict) -> float | None:
    """Slippage bps for a $1,000 notional against the shallowest leg book.

    Expects ``book_depth_usd`` (min of both legs) in the pair record.
    Returns None if absent — the UI shows ``—`` and the DEPTH column
    stays empty until the scanner enriches records.

    Linear model: bps = 10_000 / (book_depth_usd / 1_000). A book of
    $1k matches 100% slippage (10_000 bps); $50k → 200 bps; $10M → 1 bps.
    Non-finite or non-positive depth returns None.
    """
    depth = opp.get("book_depth_usd")
    if depth is None:
        return None
    try:
        d = float(depth)
    except (TypeError, ValueError):
        return None
    if d <= 0 or not math.isfinite(d):
        return None
    return round(10_000.0 / (d / 1000.0), 4)


def _viab(score: float, breakeven_h: float | None, vol_score: float | None) -> str:
    """GO / WAIT / SKIP from composite signal.

    GO   = score >= 70  AND bkevn <= 24h   AND vol_score >= 40
    WAIT = score >= 40  AND (bkevn <= 72h  OR  vol_score >= 20)
    SKIP = anything else
    """
    vol = vol_score if vol_score is not None else 0.0
    be = breakeven_h if breakeven_h is not None else 9999.0
    if score >= 70 and be <= 24.0 and vol >= 40.0:
        return "GO"
    if score >= 40 and (be <= 72.0 or vol >= 20.0):
        return "WAIT"
    return "SKIP"


@dataclass
class ScoreResult:
    """Result of scoring a single opportunity."""
    score:   float          # 0-100
    grade:   str            # GO / MAYBE / SKIP (legacy)
    viab:    str = "SKIP"   # GO / WAIT / SKIP (new — viability flag)
    breakeven_h: float | None = None
    # v2 density columns (2026-04-23):
    profit_usd_per_1k_24h: float | None = None   # net $ on $1k over 24h (fees_rt = _DEFAULT_RT_FEE_BPS)
    depth_pct_at_1k: float | None = None         # slippage bps for $1k notional, from book_depth_usd
    factors: dict = field(default_factory=dict)  # per-factor raw scores (0-100 or None)


def score_opp(opp: dict, cfg: dict | None = None) -> ScoreResult:
    """Score a single opportunity or arb pair.

    Args:
        opp: dict with opportunity fields (see module docstring for keys).
        cfg: optional config overrides (weights, thresholds, venue_reliability, pos_size_ref).

    Returns:
        ScoreResult with score (0-100), grade, viab, breakeven_h, and factors breakdown.
    """
    resolved = _resolve_cfg(cfg)
    weights          = resolved["weights"]
    thresholds       = resolved["thresholds"]
    venue_reliability = resolved["venue_reliability"]
    pos_size_ref     = resolved["pos_size_ref"]

    factor_scores: dict[str, float | None] = {
        "net_apr":  _score_net_apr(opp),
        "volume":   _score_volume(opp),
        "oi":       _score_oi(opp),
        "risk":     _score_risk(opp),
        "slippage": _score_slippage(opp, pos_size_ref),
        "venue":    _score_venue(opp, venue_reliability),
    }

    score = _weighted_score(factor_scores, weights)
    grade = _grade(score, thresholds)
    be = _breakeven_hours(opp)
    viab = _viab(score, be, factor_scores.get("volume"))
    profit = _profit_usd_per_1k_24h(opp)
    depth = _depth_pct_at_1k(opp)

    return ScoreResult(
        score=round(score, 2),
        grade=grade,
        viab=viab,
        breakeven_h=be,
        profit_usd_per_1k_24h=profit,
        depth_pct_at_1k=depth,
        factors=factor_scores,
    )


def score_batch(opps: list[dict], cfg: dict | None = None) -> list[ScoreResult]:
    """Score a list of opportunities in parallel, preserving order.

    Args:
        opps: list of opportunity dicts.
        cfg:  optional shared config overrides for all opps.

    Returns:
        list of ScoreResult in same order as input.
    """
    if not opps:
        return []

    results: list[ScoreResult | None] = [None] * len(opps)

    with ThreadPoolExecutor(max_workers=min(len(opps), 8)) as executor:
        futures = {executor.submit(score_opp, opp, cfg): i for i, opp in enumerate(opps)}
        for future in as_completed(futures):
            idx = futures[future]
            results[idx] = future.result()

    return results  # type: ignore[return-value]
