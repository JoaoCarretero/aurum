"""Pre-start risk gate evaluation for the /api/trading/start endpoint.

Thin adapter: takes the engine mode, pulls a best-effort account snapshot
from PortfolioMonitor, builds a RiskState, and calls check_gates with the
mode-specific RiskGateConfig. Returns a GateDecision the route can turn
into an HTTP response.

Fetch-failure semantics:
  * paper / demo / testnet / arbitrage_paper / arbitrage_demo /
    arbitrage_testnet: fail-open (legacy behavior). equity=0 + no
    positions makes balance gates effectively no-op; freeze_window is
    still enforced and is the most important pre-start guard for
    non-real-money modes.
  * live / arbitrage_live: fail-CLOSED with soft_block. Flying blind on
    real capital is unsafe — if PortfolioMonitor cannot return a
    snapshot, balance circuit breakers cannot be evaluated, and we
    refuse to start a new entry.

Audit 2026-04-25 Lane 5: prior to this split, a network blip during
PortfolioMonitor.refresh() silently disabled every balance-based circuit
breaker on real capital, since equity=0 made each gate's `<= 0` guard
early-return allow.
"""
from __future__ import annotations

from datetime import datetime, timezone

from core.risk.risk_gates import (
    GateDecision,
    RiskState,
    check_gates,
    load_gate_config,
)


_FAIL_CLOSED_MODES: frozenset[str] = frozenset({"live", "arbitrage_live"})


def _snapshot_positions(snapshot: dict) -> list[dict]:
    out: list[dict] = []
    for p in snapshot.get("positions", []) or []:
        size = float(p.get("size", 0) or 0)
        mark = float(p.get("mark", 0) or 0)
        out.append({
            "symbol":   p.get("symbol", ""),
            "side":     p.get("side", "LONG"),
            "notional": size * mark,
        })
    return out


def build_start_state(snapshot: dict | None) -> RiskState:
    snap = snapshot or {}
    return RiskState(
        account_equity=float(snap.get("equity", 0) or 0),
        open_positions=_snapshot_positions(snap),
        current_hour_utc=datetime.now(timezone.utc).hour,
    )


def _fetch_snapshot(mode: str) -> dict | None:
    try:
        from core.ui.portfolio_monitor import PortfolioMonitor
        return PortfolioMonitor().refresh(mode)
    except Exception:
        return None


def evaluate_start_gates(mode: str,
                         snapshot: dict | None = None) -> GateDecision:
    """Run check_gates for a pre-start decision.

    ``snapshot`` can be injected for tests; otherwise PortfolioMonitor is
    queried best-effort. When the caller does NOT inject a snapshot AND
    PortfolioMonitor returns None, ``mode`` decides:

      * fail-closed for ``live`` / ``arbitrage_live`` → soft_block with
        gate ``snapshot_fetch``. Routes turn this into 403.
      * fail-open for everything else → empty state, balance gates no-op.
    """
    cfg = load_gate_config(mode)
    if snapshot is None:
        snap = _fetch_snapshot(mode)
        if snap is None and mode in _FAIL_CLOSED_MODES:
            return GateDecision(
                severity="soft_block",
                reason=f"portfolio snapshot unavailable for {mode!r} — failing closed",
                gate="snapshot_fetch",
            )
    else:
        snap = snapshot
    state = build_start_state(snap)
    return check_gates(state, cfg)
