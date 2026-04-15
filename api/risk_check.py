"""Pre-start risk gate evaluation for the /api/trading/start endpoint.

Thin adapter: takes the engine mode, pulls a best-effort account snapshot
from PortfolioMonitor, builds a RiskState, and calls check_gates with the
mode-specific RiskGateConfig. Returns a GateDecision the route can turn
into an HTTP response.

Fail-open semantics on snapshot errors: if the portfolio fetch fails
(network, missing keys), we pass equity=0/no positions — which is
effectively permissive for balance-based gates but still enforces
freeze_window, which is the most important pre-start guard.
"""
from __future__ import annotations

from datetime import datetime, timezone

from core.risk_gates import (
    GateDecision,
    RiskState,
    check_gates,
    load_gate_config,
)


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
        from core.portfolio_monitor import PortfolioMonitor
        return PortfolioMonitor().refresh(mode)
    except Exception:
        return None


def evaluate_start_gates(mode: str,
                         snapshot: dict | None = None) -> GateDecision:
    """Run check_gates for a pre-start decision.

    ``snapshot`` can be injected for tests; otherwise PortfolioMonitor
    is queried best-effort.
    """
    cfg = load_gate_config(mode)
    snap = snapshot if snapshot is not None else _fetch_snapshot(mode)
    state = build_start_state(snap)
    return check_gates(state, cfg)
