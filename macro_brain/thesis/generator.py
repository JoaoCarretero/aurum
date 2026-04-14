"""Thesis generator — combina regime + scores + templates em theses.

Pipeline:
  1. Classify regime + score universe
  2. For each template aplicável (regime match):
     - For each asset que bate min_score threshold:
       - Build rationale via template.rationale_fmt
       - Build Thesis com invalidation conditions
  3. Validator final (MIN_CONFIDENCE, correlação, exposure caps)
  4. Persist theses aprovadas
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from config.macro_params import (
    MACRO_MAX_CONCURRENT_THESES,
    MACRO_MAX_CORRELATED_THESES,
    MACRO_MIN_THESIS_CONFIDENCE,
)
from macro_brain.ml_engine.features import FeatureVector, build_features
from macro_brain.ml_engine.regime import RegimeSnapshot, classify
from macro_brain.ml_engine.scoring import AssetScore, score_universe
from macro_brain.persistence.store import (
    active_theses, insert_thesis, latest_regime,
)
from macro_brain.thesis.templates import TEMPLATES

log = logging.getLogger("macro_brain.thesis.generator")


@dataclass
class GeneratedThesis:
    """Tese pendente antes de persistir."""
    template_name: str
    direction: str
    asset: str
    confidence: float
    rationale: str
    horizon_days: int
    invalidation: list[dict]
    regime_id: str | None = None
    score_details: dict = field(default_factory=dict)


# ── TEMPLATE MATCHING ────────────────────────────────────────

def _template_matches(
    tmpl: dict[str, Any], regime: RegimeSnapshot, asset: str, score: AssetScore,
    fv: FeatureVector,
) -> bool:
    """Check if template aplica pra este (regime, asset, score, features)."""
    # Regime match
    if regime.regime not in tmpl["regime"]:
        return False

    # Asset filter
    asset_filter = tmpl.get("asset_filter")
    if asset_filter and asset not in asset_filter:
        return False

    # Required features (e.g. fg_is_extreme_fear == 1.0)
    req = tmpl.get("requires_features", {})
    feats = fv.flat()
    for fk, fv_expected in req.items():
        if feats.get(fk) != fv_expected:
            return False

    # Score threshold
    min_score = tmpl["min_score"]
    is_contrarian = tmpl.get("is_contrarian", False)
    if is_contrarian:
        return True  # contrarian ignora score direction
    if tmpl["direction"] == "long":
        if score.score < min_score:
            return False
    else:  # short
        if score.score > min_score:
            return False

    return True


def _build_rationale(tmpl: dict, regime: RegimeSnapshot,
                    asset: str, score: AssetScore, fv: FeatureVector) -> str:
    fmt = tmpl.get("rationale_fmt", "")
    feats = fv.flat()
    try:
        return fmt.format(
            regime=regime.regime,
            regime_reason=regime.reason,
            asset=asset,
            score=score.score,
            confidence=score.confidence,
            fear_greed=feats.get("e.fear_greed_latest", "?"),
        )
    except (KeyError, ValueError) as e:
        return f"[template render error: {e}] {tmpl.get('name')}"


# ── VALIDATORS ───────────────────────────────────────────────

def _validate(candidates: list[GeneratedThesis]) -> list[GeneratedThesis]:
    """Aplica guards globais — confidence mín, concurrency, correlação."""
    active = active_theses()
    active_assets = [t["asset"] for t in active]
    active_count = len(active)

    approved: list[GeneratedThesis] = []

    for c in candidates:
        # Min confidence
        if c.confidence < MACRO_MIN_THESIS_CONFIDENCE:
            log.info(f"  REJECT {c.asset}/{c.template_name}: "
                     f"conf {c.confidence:.2%} < min {MACRO_MIN_THESIS_CONFIDENCE:.2%}")
            continue

        # Concurrent cap
        if active_count + len(approved) >= MACRO_MAX_CONCURRENT_THESES:
            log.info(f"  REJECT {c.asset}/{c.template_name}: "
                     f"concurrent cap ({MACRO_MAX_CONCURRENT_THESES}) reached")
            continue

        # Dedup: já temos tese no mesmo ativo?
        all_assets = active_assets + [a.asset for a in approved]
        if c.asset in all_assets:
            log.info(f"  REJECT {c.asset}/{c.template_name}: duplicate asset")
            continue

        # Correlation cap (MVP simplificado: max_correlated é só count absoluto)
        # Mesma direção em alts correlacionadas contam. Phase 2: matriz corr real.
        same_side = sum(1 for a in approved if a.direction == c.direction)
        active_side = sum(1 for a in active if a.get("direction") == c.direction)
        if same_side + active_side >= MACRO_MAX_CORRELATED_THESES:
            log.info(f"  REJECT {c.asset}/{c.template_name}: "
                     f"correlated cap ({MACRO_MAX_CORRELATED_THESES} same-side)")
            continue

        approved.append(c)

    return approved


# ── MAIN ENTRY ───────────────────────────────────────────────

def generate(
    regime: RegimeSnapshot | None = None,
    fv: FeatureVector | None = None,
    persist: bool = True,
) -> list[GeneratedThesis]:
    """Generate theses from current state. Persisted ones get inserted to DB."""
    if fv is None:
        fv = build_features()
    if regime is None:
        regime = classify(fv=fv, persist=False)

    scores = score_universe(regime, fv)
    score_by_asset = {s.asset: s for s in scores}

    candidates: list[GeneratedThesis] = []

    for tmpl in TEMPLATES:
        for asset in score_by_asset:
            score = score_by_asset[asset]
            if not _template_matches(tmpl, regime, asset, score, fv):
                continue

            # Confidence final = regime_conf × (|score| normalized) × 0.8-1.0 boost
            # Contrarian theses get flat 0.55 conf (low bar p/ enter; high conviction bar)
            if tmpl.get("is_contrarian", False):
                conf = 0.55
            else:
                conf = round(regime.confidence * max(abs(score.score), 0.3) * 1.2, 3)
                conf = min(conf, 0.95)

            rationale = _build_rationale(tmpl, regime, asset, score, fv)

            candidates.append(GeneratedThesis(
                template_name=tmpl["name"],
                direction=tmpl["direction"],
                asset=asset,
                confidence=conf,
                rationale=rationale,
                horizon_days=tmpl["horizon_days"],
                invalidation=tmpl["invalidation"],
                score_details={"score": score.score, "direction": score.direction,
                               "score_reason": score.reason},
            ))

    # Sort by confidence desc before validation
    candidates.sort(key=lambda c: c.confidence, reverse=True)

    approved = _validate(candidates)

    # Persist
    if persist and approved:
        regime_row = latest_regime()
        regime_id = regime_row["id"] if regime_row else None
        for c in approved:
            tid = insert_thesis(
                direction=c.direction, asset=c.asset, confidence=c.confidence,
                regime_id=regime_id, rationale=c.rationale,
                target_horizon_days=c.horizon_days, invalidation=c.invalidation,
            )
            log.info(f"  [persist] {tid[:8]} {c.direction:<5} {c.asset} conf {c.confidence:.2%}")

    return approved


def describe(theses: list[GeneratedThesis]) -> str:
    if not theses:
        return "No theses approved."
    lines = [f"GENERATED THESES ({len(theses)}):"]
    for t in theses:
        lines.append(f"\n  [{t.template_name}]  {t.direction.upper():<5} {t.asset:<10} "
                     f"conf {t.confidence:.2%}  ({t.horizon_days}d)")
        lines.append(f"     {t.rationale}")
    return "\n".join(lines)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-5s  %(message)s")
    from macro_brain.persistence.store import init_db
    init_db()

    theses = generate(persist=False)
    print(describe(theses))
