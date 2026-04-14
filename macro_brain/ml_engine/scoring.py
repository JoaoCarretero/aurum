"""Per-asset directional scoring.

Converte regime + features em score direcional por ativo do universo.
Output: {asset: score ∈ [-1, +1]} onde +1 = long conviction, -1 = short.

Design MVP: rule-based mapping regime → asset bias + perturb por
signals específicos do ativo (dominance, pct changes, sentiment).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from config.macro_params import MACRO_UNIVERSE
from macro_brain.ml_engine.features import FeatureVector
from macro_brain.ml_engine.regime import RegimeSnapshot

log = logging.getLogger("macro_brain.ml.scoring")


@dataclass
class AssetScore:
    asset: str
    score: float               # -1..+1
    direction: Literal["long", "short", "flat"]
    confidence: float          # 0-1
    reason: str
    key_signals: dict          # features that drove decision


# ── REGIME → ASSET BIAS ──────────────────────────────────────
# Bias base por ativo em cada regime. Altcoins > BTC em risk-on;
# BTC relativamente mais resiliente em risk-off que alts.
_REGIME_BIAS = {
    "risk_on": {
        "BTCUSDT": +0.4,
        "ETHUSDT": +0.5,
        "SOLUSDT": +0.7,
        "BNBUSDT": +0.5,
    },
    "risk_off": {
        "BTCUSDT": -0.4,
        "ETHUSDT": -0.5,
        "SOLUSDT": -0.7,
        "BNBUSDT": -0.5,
    },
    "transition": {  # regime flip → reduzido sizing
        "BTCUSDT": 0.0,
        "ETHUSDT": 0.0,
        "SOLUSDT": -0.2,
        "BNBUSDT": 0.0,
    },
    "uncertainty": {
        "BTCUSDT": 0.0,
        "ETHUSDT": 0.0,
        "SOLUSDT": 0.0,
        "BNBUSDT": 0.0,
    },
}


def _asset_specific_signal(asset: str, fv: FeatureVector) -> tuple[float, list[str]]:
    """Perturbação baseada em signals do próprio ativo. Retorna (perturb, reasons)."""
    feats = fv.flat()
    perturb = 0.0
    reasons: list[str] = []

    # Map asset → feature prefix (BTCUSDT → BTC_SPOT)
    prefix_map = {
        "BTCUSDT": "BTC_SPOT",
        "ETHUSDT": "ETH_SPOT",
        "SOLUSDT": "SOL_SPOT",
        "BNBUSDT": "BNB_SPOT",
    }
    px_prefix = prefix_map.get(asset)
    if not px_prefix:
        return 0.0, []

    # 7d pct change — momentum continuation (low weight, MVP)
    pct7 = feats.get(f"n.{px_prefix}_pct7d")
    if pct7 is not None:
        # Strong 7d up → small long bias (+0.05 per 5% move, capped)
        perturb += max(-0.15, min(0.15, pct7 / 100 * 3))
        if abs(pct7) > 5:
            reasons.append(f"{px_prefix}_pct7d={pct7:+.1f}%")

    # BTC dominance (relevant p/ altcoins)
    if asset != "BTCUSDT":
        dom_pct7 = feats.get("n.BTC_DOMINANCE_pct7d")
        if dom_pct7 is not None and abs(dom_pct7) > 2:
            # Dominance subindo → alts sofrem
            perturb += -dom_pct7 / 100 * 2
            reasons.append(f"BTC_dom_pct7d={dom_pct7:+.1f}%")

    return perturb, reasons


def score_universe(
    regime: RegimeSnapshot,
    fv: FeatureVector,
    universe: list[str] | None = None,
) -> list[AssetScore]:
    """Score cada asset do universe. Returns sorted by |score| desc."""
    universe = universe or MACRO_UNIVERSE
    bias_map = _REGIME_BIAS.get(regime.regime, _REGIME_BIAS["uncertainty"])
    out: list[AssetScore] = []

    for asset in universe:
        base_bias = bias_map.get(asset, 0.0)
        perturb, perturb_reasons = _asset_specific_signal(asset, fv)
        score = max(-1.0, min(1.0, base_bias + perturb))

        # Scale confidence by regime confidence — uncertain regime → lower asset confidence
        conf = abs(score) * regime.confidence

        # Direction threshold — scores tiny → flat (no trade)
        if abs(score) < 0.25:
            direction = "flat"
        elif score > 0:
            direction = "long"
        else:
            direction = "short"

        reasons = [f"{regime.regime}_base={base_bias:+.2f}"] + perturb_reasons
        key_signals = {k: v for k, v in fv.flat().items()
                       if asset.replace("USDT", "") in k or "regime" in k}

        out.append(AssetScore(
            asset=asset, score=round(score, 3), direction=direction,
            confidence=round(conf, 3), reason=" · ".join(reasons),
            key_signals=key_signals,
        ))

    out.sort(key=lambda s: abs(s.score), reverse=True)
    return out


def describe(scores: list[AssetScore]) -> str:
    lines = ["ASSET SCORES (sorted by |score|):"]
    lines.append(f"  {'ASSET':<10} {'SCORE':>7} {'DIR':<7} {'CONF':>6}  REASON")
    lines.append(f"  {'-'*10} {'-'*7} {'-'*7} {'-'*6}  {'-'*40}")
    for s in scores:
        lines.append(
            f"  {s.asset:<10} {s.score:>+7.3f} {s.direction:<7} "
            f"{s.confidence:>6.2%}  {s.reason[:50]}"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from macro_brain.ml_engine.features import build_features
    from macro_brain.ml_engine.regime import classify
    from macro_brain.persistence.store import init_db
    init_db()

    fv = build_features()
    regime = classify(fv=fv, persist=False)
    print(f"Regime: {regime.regime} (conf {regime.confidence:.2%})\n")
    scores = score_universe(regime, fv)
    print(describe(scores))
