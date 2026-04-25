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

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
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

    # Drawdown velocity cap — % of equity lost per hour at which the
    # leading indicator trips soft_block. Caller computes this from a
    # rolling window of equity readings. CLAUDE.md kill-switch layer 1.
    # Default permissive (100%/hr ~ no-op) per module convention.
    max_dd_velocity_pct_per_hour: float = 100.0

    # API latency p99 cap (milliseconds) — anomaly detector. CLAUDE.md
    # kill-switch layer 3. Caller computes p99 over a rolling 5-min window
    # of API call latencies (REST request → response). When p99 climbs
    # above this threshold, the exchange is degrading (rate limited, sick,
    # or network blip): pause new entries before bad fills happen.
    # Default permissive (1e9 ms ~ no-op) per module convention.
    max_api_latency_ms: float = 1e9

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
            and self.max_dd_velocity_pct_per_hour == defaults.max_dd_velocity_pct_per_hour
            and self.max_api_latency_ms  == defaults.max_api_latency_ms
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
    # Drawdown velocity in %/hr. Caller computes from a rolling equity
    # window (e.g., (equity_now - equity_60min_ago) / equity_60min_ago * -100).
    # Positive = losing equity. 0.0 = stationary or recovering. Negative =
    # equity climbing. Provided per call so risk_gates stays stateless.
    dd_velocity_pct_per_hour: float = 0.0
    # API latency p99 in milliseconds. Caller computes p99 over a rolling
    # window of REST API call latencies. 0.0 = no data yet (insufficient
    # samples). Higher = exchange degrading. Provided per call so
    # risk_gates stays stateless.
    api_latency_ms_p99: float = 0.0


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


def gate_dd_velocity(state: RiskState, cfg: RiskGateConfig) -> GateDecision:
    """Soft-block when equity is bleeding faster than the configured rate.

    CLAUDE.md mandates kill-switch layer 1 as "drawdown velocity" — a leading
    indicator that should trip BEFORE the static daily DD threshold confirms.
    A 3% drop over 10 minutes implies an 18%/hr velocity: catastrophic if
    sustained. Pausing new entries gives the operator (or higher-level
    automation) a chance to investigate before the static gate flattens.

    The caller computes ``dd_velocity_pct_per_hour`` from a rolling window
    of equity readings (typically the last 30-60 minutes). risk_gates.py
    stays stateless — it just compares the reported value against the cap.
    """
    if state.account_equity <= 0:
        return _allow()
    velocity = state.dd_velocity_pct_per_hour
    if velocity <= 0:
        # Stationary or recovering equity — no cliff.
        return _allow()
    if velocity >= cfg.max_dd_velocity_pct_per_hour:
        return _soft("dd_velocity",
                     f"drawdown velocity {velocity:.2f}%/hr "
                     f"≥ {cfg.max_dd_velocity_pct_per_hour:.2f}%/hr",
                     velocity, cfg.max_dd_velocity_pct_per_hour)
    return _allow()


def gate_anomaly(state: RiskState, cfg: RiskGateConfig) -> GateDecision:
    """Soft-block when API latency p99 exceeds the configured threshold.

    CLAUDE.md mandates kill-switch layer 3 as "anomaly" detection. The
    simplest universal anomaly signal is API latency p99 — when the
    exchange's REST endpoint p99 climbs above a sane threshold, something
    is wrong: rate limited, network blip, exchange degraded, or DDOS in
    progress. Pausing new entries gives the operator (or higher-level
    automation) a chance to investigate before bad fills happen on a
    sick venue.

    The caller computes ``api_latency_ms_p99`` over a rolling 5-min window
    of REST call latencies (request → response). risk_gates.py stays
    stateless — it just compares the reported value against the cap.

    Same severity tier as gate_dd_velocity: a leading indicator that
    soft_blocks. We do not flatten on a latency spike alone — the
    operator decides whether to escalate.
    """
    if state.api_latency_ms_p99 <= 0:
        # No data yet (engine just started, no latency samples) — allow.
        return _allow()
    if state.api_latency_ms_p99 >= cfg.max_api_latency_ms:
        return _soft("anomaly",
                     f"API latency p99 {state.api_latency_ms_p99:.0f}ms "
                     f"≥ {cfg.max_api_latency_ms:.0f}ms",
                     state.api_latency_ms_p99, cfg.max_api_latency_ms)
    return _allow()


# ── Composite check ──────────────────────────────────────────────────

_ALL_GATES = (
    gate_daily_dd,
    gate_daily_loss,
    gate_consecutive_losses,
    gate_dd_velocity,
    gate_anomaly,
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


# ── Config loader ────────────────────────────────────────────────────

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "risk_gates.json"
_ALLOWED_KEYS = {
    "max_daily_dd_pct", "max_daily_loss_pct",
    "max_consecutive_losses", "soft_block_losses",
    "max_gross_notional_pct", "max_net_exposure_pct",
    "max_concurrent_positions", "freeze_hours_utc",
    "max_single_position_pct",
    "max_dd_velocity_pct_per_hour",
    "max_api_latency_ms",
}


_CONFIG_CACHE: dict[str, tuple[float, "RiskGateConfig"]] = {}


def load_gate_config(mode: str) -> RiskGateConfig:
    """Load RiskGateConfig for ``mode`` from config/risk_gates.json.

    Falls back to the permissive default if the file is absent, malformed,
    or the mode section is missing. Unknown keys are ignored (forward-compat).

    Cached per mode by file mtime: edits to risk_gates.json are picked up
    on next call, but unchanged files skip the JSON parse.
    """
    if not _CONFIG_PATH.exists():
        _CONFIG_CACHE.clear()
        return RiskGateConfig()
    try:
        mtime = _CONFIG_PATH.stat().st_mtime
    except OSError:
        return RiskGateConfig()
    cached = _CONFIG_CACHE.get(mode)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    try:
        raw = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return RiskGateConfig()
    if not isinstance(raw, dict):
        return RiskGateConfig()
    section = raw.get(mode, {})
    if not isinstance(section, dict):
        return RiskGateConfig()
    kwargs = {k: v for k, v in section.items() if k in _ALLOWED_KEYS}
    if "freeze_hours_utc" in kwargs and isinstance(kwargs["freeze_hours_utc"], list):
        kwargs["freeze_hours_utc"] = tuple(int(h) for h in kwargs["freeze_hours_utc"])
    try:
        cfg = RiskGateConfig(**kwargs)
    except TypeError:
        return RiskGateConfig()
    _CONFIG_CACHE[mode] = (mtime, cfg)
    return cfg


__all__ = [
    "RiskGateConfig",
    "RiskState",
    "GateDecision",
    "check_gates",
    "load_gate_config",
    "gate_daily_dd",
    "gate_daily_loss",
    "gate_consecutive_losses",
    "gate_dd_velocity",
    "gate_anomaly",
    "gate_gross_notional",
    "gate_net_exposure",
    "gate_concurrent_positions",
    "gate_freeze_window",
    "gate_single_position",
]
