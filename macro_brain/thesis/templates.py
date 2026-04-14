"""Thesis templates — patterns hardcoded pro MVP.

Cada template é um dict com:
  name          identifier
  regime        regime(s) que ativa(m)
  direction     long|short
  min_score     threshold de score por ativo
  horizon_days  alvo
  rationale_fmt template pra rationale textual
  invalidation  lista de conditions que fecham a tese

Phase 2 substitui por LLM-generated rationale (GPT-4).
"""
from __future__ import annotations

from typing import Any

TEMPLATES: list[dict[str, Any]] = [
    {
        "name": "risk_off_short_alts",
        "regime": ["risk_off"],
        "direction": "short",
        "min_score": -0.35,
        "horizon_days": 30,
        "rationale_fmt": (
            "Macro risk-off: {regime_reason}. "
            "Altcoin {asset} tende a amplificar moves de BTC no downside. "
            "Score {score:+.2f} reflete bias negativo reforçado."
        ),
        "invalidation": [
            {"type": "regime_flip", "from": "risk_off",
             "to_any": ["risk_on", "transition"]},
            {"type": "feature_threshold", "feature": "e.fear_greed_latest",
             "op": ">=", "value": 60},
            {"type": "feature_threshold", "feature": "n.DXY_z30d",
             "op": "<", "value": 0.5},
        ],
    },
    {
        "name": "risk_on_long_alts",
        "regime": ["risk_on"],
        "direction": "long",
        "min_score": 0.35,
        "horizon_days": 45,
        "rationale_fmt": (
            "Macro risk-on: {regime_reason}. "
            "Altcoin {asset} com score {score:+.2f} favorecido por "
            "beta positivo a risk assets + liquidity conditions easing."
        ),
        "invalidation": [
            {"type": "regime_flip", "from": "risk_on",
             "to_any": ["risk_off", "transition"]},
            {"type": "feature_threshold", "feature": "e.fear_greed_latest",
             "op": "<=", "value": 30},
            {"type": "feature_threshold", "feature": "n.DXY_z30d",
             "op": ">", "value": 1.0},
        ],
    },
    {
        "name": "risk_on_long_btc_conservative",
        "regime": ["risk_on", "transition"],
        "direction": "long",
        "min_score": 0.25,
        "horizon_days": 60,
        "rationale_fmt": (
            "Risk-on setup (ou transition). BTC {asset} como exposure "
            "conservador vs altcoins — beta macro menor, liquidez maior. "
            "Score {score:+.2f}."
        ),
        "invalidation": [
            {"type": "regime_flip", "from_any": ["risk_on", "transition"],
             "to": "risk_off"},
            {"type": "feature_threshold", "feature": "e.fear_greed_latest",
             "op": "<=", "value": 20},
        ],
        "asset_filter": ["BTCUSDT"],  # só BTC
    },
    {
        "name": "extreme_fear_contrarian_btc",
        "regime": ["risk_off", "uncertainty", "transition"],
        "direction": "long",
        "min_score": -0.5,  # pode ser baixo porque é contrarian
        "horizon_days": 90,
        "rationale_fmt": (
            "Fear&Greed extreme fear ({fear_greed:.0f}) + regime {regime}. "
            "Contrarian long em BTC: historicamente leituras de F&G <20 "
            "precedem mean-reversion em 30-90d. Score ignorado pra contrarian."
        ),
        "invalidation": [
            {"type": "feature_threshold", "feature": "e.fear_greed_latest",
             "op": ">=", "value": 55},  # neutralidade = exit
            {"type": "time_stop", "days": 90},
        ],
        "asset_filter": ["BTCUSDT"],
        "requires_features": {"e.fg_is_extreme_fear": 1.0},
        "is_contrarian": True,
    },
    {
        "name": "extreme_greed_contrarian_short",
        "regime": ["risk_on", "transition"],
        "direction": "short",
        "min_score": 0.0,
        "horizon_days": 60,
        "rationale_fmt": (
            "Fear&Greed extreme greed ({fear_greed:.0f}). "
            "Crowd long demais — contrarian short em altcoins com maior beta. "
            "Mean-reversion esperada em 30-60d."
        ),
        "invalidation": [
            {"type": "feature_threshold", "feature": "e.fear_greed_latest",
             "op": "<=", "value": 45},
            {"type": "time_stop", "days": 60},
        ],
        "requires_features": {"e.fg_is_extreme_greed": 1.0},
        "is_contrarian": True,
    },
]
