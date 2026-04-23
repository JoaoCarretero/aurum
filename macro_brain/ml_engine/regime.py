"""Regime classifier — rule-based v1.

Classifica ambiente macro em 4 regimes:
  risk_on       — ativos de risco (crypto, equities) tendem a subir
  risk_off      — fuga pra safe-haven (DXY, ouro, bonds)
  transition    — sinais mistos, regime mudando
  uncertainty   — dados insuficientes ou conflitantes

Thresholds em config/macro_params.py::REGIME_THRESHOLDS.
Fase 2 substitui por logistic regression ou GBM treinado em labels ex-post.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

from config.macro_params import REGIME_THRESHOLDS
from macro_brain.ml_engine.features import FeatureVector, build_features
from macro_brain.persistence.store import insert_regime

log = logging.getLogger("macro_brain.ml.regime")

Regime = Literal["risk_on", "risk_off", "transition", "uncertainty"]


@dataclass
class RegimeSnapshot:
    ts: str
    regime: Regime
    confidence: float  # 0-1
    features: dict
    reason: str
    rules_matched: list[str] = field(default_factory=list)


# ── RULES (MVP) ──────────────────────────────────────────────

def _match_risk_off(fv: FeatureVector) -> tuple[float, list[str]]:
    """Retorna (score 0-1, rules triggered)."""
    rules: list[str] = []
    thr = REGIME_THRESHOLDS["risk_off"]
    feats = fv.flat()

    dxy_z = feats.get("n.DXY_z30d")
    vix_z = feats.get("n.VIX_z30d")
    sent_ema = feats.get("e.news_sentiment_ema")
    fg_fear = feats.get("e.fg_is_extreme_fear", 0.0)

    score = 0.0
    if dxy_z is not None and dxy_z >= thr["dxy_z_min"]:
        rules.append(f"DXY_z30d={dxy_z:.2f} ≥ {thr['dxy_z_min']}")
        score += 0.3
    if vix_z is not None and vix_z >= thr["vix_z_min"]:
        rules.append(f"VIX_z30d={vix_z:.2f} ≥ {thr['vix_z_min']}")
        score += 0.3
    if sent_ema is not None and sent_ema <= thr["sentiment_ema_max"]:
        rules.append(f"news_sent_ema={sent_ema:.2f} ≤ {thr['sentiment_ema_max']}")
        score += 0.2
    if fg_fear >= 1.0:
        rules.append("Fear&Greed = Extreme Fear")
        score += 0.2

    return min(score, 1.0), rules


def _match_risk_on(fv: FeatureVector) -> tuple[float, list[str]]:
    rules: list[str] = []
    thr = REGIME_THRESHOLDS["risk_on"]
    feats = fv.flat()

    dxy_z = feats.get("n.DXY_z30d")
    vix_z = feats.get("n.VIX_z30d")
    sent_ema = feats.get("e.news_sentiment_ema")
    fg_greed = feats.get("e.fg_is_extreme_greed", 0.0)

    score = 0.0
    if dxy_z is not None and dxy_z <= thr["dxy_z_max"]:
        rules.append(f"DXY_z30d={dxy_z:.2f} ≤ {thr['dxy_z_max']}")
        score += 0.3
    if vix_z is not None and vix_z <= thr["vix_z_max"]:
        rules.append(f"VIX_z30d={vix_z:.2f} ≤ {thr['vix_z_max']}")
        score += 0.3
    if sent_ema is not None and sent_ema >= thr["sentiment_ema_min"]:
        rules.append(f"news_sent_ema={sent_ema:.2f} ≥ {thr['sentiment_ema_min']}")
        score += 0.2
    if fg_greed >= 1.0:
        rules.append("Fear&Greed = Extreme Greed")
        score += 0.2

    return min(score, 1.0), rules


def _data_coverage(fv: FeatureVector) -> float:
    """Quantos dos signals críticos temos? Usado p/ confidence inicial."""
    critical = ["n.DXY_z30d", "n.VIX_z30d", "e.news_sentiment_ema",
                "e.fear_greed_latest"]
    feats = fv.flat()
    present = sum(1 for k in critical if k in feats)
    return present / len(critical)


# ── CLASSIFIER ───────────────────────────────────────────────

def classify(fv: FeatureVector | None = None,
             persist: bool = True) -> RegimeSnapshot:
    """Classify current regime. If `fv` None, builds fresh."""
    if fv is None:
        fv = build_features()

    off_score, off_rules = _match_risk_off(fv)
    on_score, on_rules = _match_risk_on(fv)
    coverage = _data_coverage(fv)

    # Decision logic:
    # - Both scores alto → transition (regime conflicted)
    # - Um domina (diferença ≥ 0.3) → that regime
    # - Ambos baixos → uncertainty
    # - Coverage baixo → uncertainty

    if coverage < 0.5:
        regime: Regime = "uncertainty"
        confidence = 0.3 * coverage
        reason = f"data coverage insufficient ({coverage:.0%})"
        rules = []
    elif off_score >= 0.6 and (off_score - on_score) >= 0.3:
        regime = "risk_off"
        confidence = off_score * coverage
        reason = "; ".join(off_rules) or "risk_off rules triggered"
        rules = off_rules
    elif on_score >= 0.6 and (on_score - off_score) >= 0.3:
        regime = "risk_on"
        confidence = on_score * coverage
        reason = "; ".join(on_rules) or "risk_on rules triggered"
        rules = on_rules
    elif max(off_score, on_score) >= 0.4:
        regime = "transition"
        confidence = max(off_score, on_score) * 0.7 * coverage
        reason = f"mixed signals (off={off_score:.2f}, on={on_score:.2f})"
        rules = off_rules + on_rules
    else:
        regime = "uncertainty"
        confidence = 0.2 * coverage
        reason = f"no strong signal (off={off_score:.2f}, on={on_score:.2f})"
        rules = []

    snapshot = RegimeSnapshot(
        ts=fv.ts, regime=regime, confidence=round(confidence, 3),
        features=fv.flat(), reason=reason, rules_matched=rules,
    )

    if persist:
        # Detectar mudança de regime pra alert
        from macro_brain.persistence.store import latest_regime as _lr
        prev = _lr()
        insert_regime(
            regime=regime, confidence=snapshot.confidence,
            features=snapshot.features, model_version="rule-based-v1",
            reason=reason,
        )
        if prev and prev.get("regime") != regime:
            try:
                from macro_brain.notify import notify_regime_change
                notify_regime_change(prev.get("regime"), regime,
                                      snapshot.confidence, reason)
            except Exception as e:
                log.debug(f"notify_regime_change failed: {e}")

    return snapshot


def describe(snap: RegimeSnapshot) -> str:
    lines = [
        f"REGIME: {snap.regime.upper()}  (conf {snap.confidence:.0%})",
        f"  ts: {snap.ts}",
        f"  reason: {snap.reason}",
    ]
    if snap.rules_matched:
        lines.append("  rules:")
        for r in snap.rules_matched:
            lines.append(f"    · {r}")
    return "\n".join(lines)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from macro_brain.persistence.store import init_db, latest_regime
    init_db()

    snap = classify()
    print(describe(snap))

    print("\n--- latest persisted ---")
    latest = latest_regime()
    if latest:
        print(f"  {latest['ts']}  {latest['regime']}  conf {latest['confidence']:.2%}")
        print(f"  model: {latest['model_version']}")
