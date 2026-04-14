"""Position sizing — convicção × regime × cap.

Formula MVP:
  size_usd = MACRO_ACCOUNT_SIZE × BASE_RISK_PER_THESIS
           × (0.5 + confidence × MAX_CONFIDENCE_MULT)   # 0.5-2.5x
           × regime_alignment
  capped at MAX_SINGLE_POSITION
"""
from __future__ import annotations

from config.macro_params import (
    MACRO_ACCOUNT_SIZE,
    MACRO_BASE_RISK_PER_THESIS,
    MACRO_MAX_CONFIDENCE_MULT,
    MACRO_MAX_SINGLE_POSITION,
)


def calc_size_usd(
    confidence: float,
    account_equity: float | None = None,
    regime_alignment: float = 1.0,
) -> float:
    """Calculate position size in USD.

    Args:
      confidence:      0-1, from thesis
      account_equity:  current equity (uses initial if None)
      regime_alignment: 1.0 alinhado, 0.5 transição, 0.3 uncertain
    """
    equity = account_equity if account_equity is not None else MACRO_ACCOUNT_SIZE
    conf_mult = 0.5 + max(0.0, min(confidence, 1.0)) * MACRO_MAX_CONFIDENCE_MULT
    raw = equity * MACRO_BASE_RISK_PER_THESIS * conf_mult * regime_alignment
    cap = equity * MACRO_MAX_SINGLE_POSITION
    return round(min(raw, cap), 2)
