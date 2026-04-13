"""Typed read-only access wrappers for config.params.

This module does not redefine strategy configuration. It exposes the current
values in ``config.params`` through frozen dataclasses so infrastructure code
can depend on typed snapshots instead of ad hoc wildcard imports.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from config import params as _params


@dataclass(frozen=True)
class MarketCosts:
    slippage: float
    spread: float
    commission: float
    funding_per_8h: float


@dataclass(frozen=True)
class RiskConfig:
    account_size: float
    leverage: float
    base_risk: float
    max_risk: float
    kelly_frac: float
    max_open_positions: int
    corr_threshold: float
    corr_soft_threshold: float
    corr_soft_mult: float


@dataclass(frozen=True)
class EntryConfig:
    entry_tf: str
    score_threshold: float
    stop_atr_m: float
    target_rr: float
    rr_min: float
    max_hold: int


@dataclass(frozen=True)
class RuntimeConfigSnapshot:
    market_costs: MarketCosts
    risk: RiskConfig
    entry: EntryConfig
    symbols: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "market_costs": {
                "slippage": self.market_costs.slippage,
                "spread": self.market_costs.spread,
                "commission": self.market_costs.commission,
                "funding_per_8h": self.market_costs.funding_per_8h,
            },
            "risk": {
                "account_size": self.risk.account_size,
                "leverage": self.risk.leverage,
                "base_risk": self.risk.base_risk,
                "max_risk": self.risk.max_risk,
                "kelly_frac": self.risk.kelly_frac,
                "max_open_positions": self.risk.max_open_positions,
                "corr_threshold": self.risk.corr_threshold,
                "corr_soft_threshold": self.risk.corr_soft_threshold,
                "corr_soft_mult": self.risk.corr_soft_mult,
            },
            "entry": {
                "entry_tf": self.entry.entry_tf,
                "score_threshold": self.entry.score_threshold,
                "stop_atr_m": self.entry.stop_atr_m,
                "target_rr": self.entry.target_rr,
                "rr_min": self.entry.rr_min,
                "max_hold": self.entry.max_hold,
            },
            "symbols": list(self.symbols),
        }


def market_costs() -> MarketCosts:
    return MarketCosts(
        slippage=float(_params.SLIPPAGE),
        spread=float(_params.SPREAD),
        commission=float(_params.COMMISSION),
        funding_per_8h=float(_params.FUNDING_PER_8H),
    )


def risk_config() -> RiskConfig:
    return RiskConfig(
        account_size=float(_params.ACCOUNT_SIZE),
        leverage=float(_params.LEVERAGE),
        base_risk=float(_params.BASE_RISK),
        max_risk=float(_params.MAX_RISK),
        kelly_frac=float(_params.KELLY_FRAC),
        max_open_positions=int(_params.MAX_OPEN_POSITIONS),
        corr_threshold=float(_params.CORR_THRESHOLD),
        corr_soft_threshold=float(_params.CORR_SOFT_THRESHOLD),
        corr_soft_mult=float(_params.CORR_SOFT_MULT),
    )


def entry_config() -> EntryConfig:
    return EntryConfig(
        entry_tf=str(_params.ENTRY_TF),
        score_threshold=float(_params.SCORE_THRESHOLD),
        stop_atr_m=float(_params.STOP_ATR_M),
        target_rr=float(_params.TARGET_RR),
        rr_min=float(_params.RR_MIN),
        max_hold=int(_params.MAX_HOLD),
    )


def snapshot() -> RuntimeConfigSnapshot:
    return RuntimeConfigSnapshot(
        market_costs=market_costs(),
        risk=risk_config(),
        entry=entry_config(),
        symbols=tuple(getattr(_params, "SYMBOLS", ()) or ()),
    )
