"""AURUM — risk gates (circuit breakers) for live trading.

Passive utility module. Engines opt in by calling ``check_gates(state)``
before placing orders and reacting to the returned decision dict. Nothing
in this file reaches into exchange APIs or live state on its own — the
caller is responsible for feeding it a snapshot and honoring the result.

Design notes
------------
- **No global state.** Every call passes a full ``RiskState`` snapshot.
  That makes the checks idempotent, testable without mocks, and safe to
  run from any thread.
- **Hard vs soft.** Each gate returns one of ``"allow" | "soft_block" |
  "hard_block"``. ``soft_block`` means "pause new entries, do not flatten
  existing"; ``hard_block`` means "pause new AND flatten" (the kill
  switch). The caller decides how to act — this module just reports.
- **No defaults-on for live.** Every gate has a threshold that defaults
  to the MOST permissive value (effectively no-op). The caller must
  opt into tighter values via config. An engine with unconfigured gates
  behaves as it did before this module existed.
- **Audit-ready.** Each check returns a reason string suitable for
  writing to the order audit trail (core.audit_trail).

Usage
-----

    from core.risk_gates import RiskGateConfig, RiskState, check_gates

    cfg = RiskGateConfig(
        max_daily_loss_pct=5.0,          # 5% of account equity
        max_consecutive_losses=6,
        max_gross_notional_pct=300.0,    # 3× account
        max_net_exposure_pct=150.0,      # 1.5× account
    )
    state = RiskState(
        account_equity=10_000.0,
        daily_pnl=-420.0,
        consecutive_losses=3,
        open_positions=[
            {"symbol": "BTCUSDT", "side": "LONG", "notional": 8_000.0},
            {"symbol": "ETHUSDT", "side": "SHORT", "notional": 4_000.0},
        ],
    )
    decision = check_gates(state, cfg)
    if decision.severity == "hard_block":
        kill_switch_trigger(decision.reason)
    elif decision.severity == "soft_block":
        skip_new_entries(decision.reason)
    else:
        place_order(...)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Literal

log = logging.getLogger(__name__)

# Module-level flag — warn only once per session
_warned_permissive_defaults: bool = False


Severity = Literal["allow", "soft_block", "hard_block"]


# ── Config ────────────────────────────────────────────────────────────

@dataclass
class RiskGateConfig:
    """Thresholds for every gate.

    All defaults are permissive on purpose — an engine that constructs
    a default ``RiskGateConfig()`` gets the pre-module behavior. The user
    must dial these down explicitly to activate the circuit breakers.
    """

    # Daily drawdown / loss caps
    max_daily_dd_pct:    float = 100.0   # % of peak equity. 100 = off.
    max_daily_loss_pct:  float = 100.0   # % of start-of-day equity
    max_consecutive_losses: int = 999    # streak before soft_block

    # Aggregate exposure caps (across open positions, not per trade)
    max_gross_notional_pct:  float = 1e9   # sum |notional| / equity
    max_net_exposure_pct:    float = 1e9   # (longs - shorts) / equity

    # Max # of concurrent positions — bounded safety net
    max_concurrent_positions: int = 999

    # Trading-window freeze (UTC hour range where new entries are blocked)
    freeze_hours_utc: tuple[int, ...] = field(default_factory=tuple)

    # When consecutive_losses ≥ this, go to soft_block instead of allow
    soft_block_losses: int = 3

    # Per-trade notional cap (% of account equity). Default 10%.
    max_single_position_pct: float = 10.0

    def is_default(self) -> bool:
        """Return True if all values are still at factory defaults (no config loaded)."""
        defaults = RiskGateConfig()
        return (
            self.max_daily_dd_pct        == defaults.max_daily_dd_pct
            and self.max_daily_loss_pct  == defaults.max_daily_loss_pct
            and self.max_consecutive_losses == defaults.max_consecutive_losses
            and self.max_gross_notional_pct == defaults.max_gross_notional_pct
            and self.max_net_exposure_pct   == defaults.max_net_exposure_pct
            and self.max_concurrent_positions == defaults.max_concurrent_positions
            and self.freeze_hours_utc    == defaults.freeze_hours_utc
            and self.soft_block_losses   == defaults.soft_block_losses
            and self.max_single_position_pct == defaults.max_single_position_pct
        )


# ── State snapshot ────────────────────────────────────────────────────

@dataclass
class RiskState:
    """Point-in-time state the caller passes to check_gates()."""

    account_equity:       float
    peak_equity:          float = 0.0
    start_of_day_equity:  float = 0.0
    daily_pnl:            float = 0.0
    consecutive_losses:   int   = 0
    open_positions:       list[dict] = field(default_factory=list)
    # open_positions items: {"symbol": str, "side": "LONG"|"SHORT",
    #                        "notional": float, "unrealized": float}
    current_hour_utc:     int   = -1
    proposed_notional:    float = 0.0   # notional of the order being evaluated


# ── Decision ──────────────────────────────────────────────────────────

@dataclass
class GateDecision:
    """What the caller should do and why."""
    severity: Severity
    reason:   str
    gate:     str = ""      # which gate fired (empty if allow)
    metric:   float = 0.0   # observed value (for the audit trail)
    threshold: float = 0.0  # configured limit


def _allow() -> GateDecision:
    return GateDecision(severity="allow", reason="ok")


def _soft(gate: str, reason: str, m: float, th: float) -> GateDecision:
    return GateDecision(severity="soft_block", reason=reason,
                        gate=gate, metric=m, threshold=th)


def _hard(gate: str, reason: str, m: float, th: float) -> GateDecision:
    return GateDecision(severity="hard_block", reason=reason,
                        gate=gate, metric=m, threshold=th)


# ── Individual gates ──────────────────────────────────────────────────

def gate_daily_dd(state: RiskState, cfg: RiskGateConfig) -> GateDecision:
    if state.peak_equity <= 0:
        return _allow()
    dd_pct = (state.peak_equity - state.account_equity) / state.peak_equity * 100.0
    if dd_pct >= cfg.max_daily_dd_pct:
        return _hard("daily_dd",
                     f"daily drawdown {dd_pct:.2f}% ≥ {cfg.max_daily_dd_pct:.2f}%",
                     dd_pct, cfg.max_daily_dd_pct)
    return _allow()


def gate_daily_loss(state: RiskState, cfg: RiskGateConfig) -> GateDecision:
    if state.start_of_day_equity <= 0:
        return _allow()
    loss_pct = -state.daily_pnl / state.start_of_day_equity * 100.0
    if loss_pct >= cfg.max_daily_loss_pct:
        return _hard("daily_loss",
                     f"daily loss {loss_pct:.2f}% ≥ {cfg.max_daily_loss_pct:.2f}%",
                     loss_pct, cfg.max_daily_loss_pct)
    return _allow()


def gate_consecutive_losses(state: RiskState,
                            cfg: RiskGateConfig) -> GateDecision:
    n = state.consecutive_losses
    if n >= cfg.max_consecutive_losses:
        return _hard("consecutive_losses",
                     f"consecutive losses {n} ≥ {cfg.max_consecutive_losses}",
                     float(n), float(cfg.max_consecutive_losses))
    if n >= cfg.soft_block_losses:
        return _soft("consecutive_losses",
                     f"consecutive losses {n} ≥ soft threshold {cfg.soft_block_losses}",
                     float(n), float(cfg.soft_block_losses))
    return _allow()


def gate_gross_notional(state: RiskState,
                        cfg: RiskGateConfig) -> GateDecision:
    if state.account_equity <= 0:
        return _allow()
    gross = sum(abs(p.get("notional", 0.0)) for p in state.open_positions)
    pct = gross / state.account_equity * 100.0
    if pct >= cfg.max_gross_notional_pct:
        return _soft("gross_notional",
                     f"gross notional {pct:.0f}% ≥ {cfg.max_gross_notional_pct:.0f}%",
                     pct, cfg.max_gross_notional_pct)
    return _allow()


def gate_net_exposure(state: RiskState, cfg: RiskGateConfig) -> GateDecision:
    if state.account_equity <= 0:
        return _allow()
    net = sum(
        p.get("notional", 0.0) * (1 if p.get("side") == "LONG" else -1)
        for p in state.open_positions
    )
    pct = abs(net) / state.account_equity * 100.0
    if pct >= cfg.max_net_exposure_pct:
        return _soft("net_exposure",
                     f"net exposure {pct:.0f}% ≥ {cfg.max_net_exposure_pct:.0f}%",
                     pct, cfg.max_net_exposure_pct)
    return _allow()


def gate_concurrent_positions(state: RiskState,
                              cfg: RiskGateConfig) -> GateDecision:
    n = len(state.open_positions)
    if n >= cfg.max_concurrent_positions:
        return _soft("concurrent_positions",
                     f"concurrent positions {n} ≥ {cfg.max_concurrent_positions}",
                     float(n), float(cfg.max_concurrent_positions))
    return _allow()


def gate_freeze_window(state: RiskState, cfg: RiskGateConfig) -> GateDecision:
    if not cfg.freeze_hours_utc or state.current_hour_utc < 0:
        return _allow()
    if state.current_hour_utc in cfg.freeze_hours_utc:
        return _soft("freeze_window",
                     f"hour {state.current_hour_utc}h UTC is in freeze list",
                     float(state.current_hour_utc), 0.0)
    return _allow()


def gate_single_position(state: RiskState,
                         cfg: RiskGateConfig) -> GateDecision:
    """Block if proposed_notional exceeds max_single_position_pct of equity."""
    if state.account_equity <= 0 or state.proposed_notional <= 0:
        return _allow()
    cap = cfg.max_single_position_pct / 100.0 * state.account_equity
    if state.proposed_notional > cap:
        pct = state.proposed_notional / state.account_equity * 100.0
        return _soft("single_position",
                     f"proposed notional {pct:.1f}% > cap {cfg.max_single_position_pct:.1f}% of equity",
                     state.proposed_notional, cap)
    return _allow()


# ── Composite check ──────────────────────────────────────────────────

_ALL_GATES = (
    gate_daily_dd,
    gate_daily_loss,
    gate_consecutive_losses,
    gate_gross_notional,
    gate_net_exposure,
    gate_concurrent_positions,
    gate_freeze_window,
    gate_single_position,
)


def check_gates(state: RiskState,
                cfg: RiskGateConfig | None = None) -> GateDecision:
    """Run every gate in order and return the FIRST non-allow result.

    A ``hard_block`` always wins over a ``soft_block``: we iterate once
    and early-exit on hard, then take the first soft if no hard fired.
    The gate ordering above goes from most-severe (daily dd / loss) to
    least-severe (freeze window). Calling this with ``cfg=None`` uses
    the permissive default config and therefore always returns
    ``allow`` — a safe no-op that a caller can plug in today without
    changing behavior until they populate a real config.
    """
    global _warned_permissive_defaults
    cfg = cfg or RiskGateConfig()

    if cfg.is_default() and not _warned_permissive_defaults:
        log.warning("risk gates using permissive defaults — no config loaded")
        _warned_permissive_defaults = True

    soft_decision: GateDecision | None = None

    for gate_fn in _ALL_GATES:
        d = gate_fn(state, cfg)
        if d.severity == "hard_block":
            return d
        if d.severity == "soft_block" and soft_decision is None:
            soft_decision = d

    return soft_decision or _allow()


__all__ = [
    "RiskGateConfig",
    "RiskState",
    "GateDecision",
    "check_gates",
    "gate_daily_dd",
    "gate_daily_loss",
    "gate_consecutive_losses",
    "gate_gross_notional",
    "gate_net_exposure",
    "gate_concurrent_positions",
    "gate_freeze_window",
    "gate_single_position",
]
