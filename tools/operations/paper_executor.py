"""Paper executor — signal to open position with slippage/spread/commission.

Mirrors `engines.live.OrderManager.paper_fill` logic + commission deduction.
Size is scaled linearly from the scan's native size (calibrated for
base_account_size) to the runner's configured account_size. This is a
CALLER-side hack — core.portfolio.position_size is NOT touched (CORE
PROTECTED). If position_size ever becomes non-linear in equity, this hack
needs revisit.

Live price override:
    ``open(..., live_price_fn=fn)`` can be passed a ``(symbol) -> float |
    None`` callable. When it returns a non-None price, that price is used
    as the entry baseline instead of the signal's ``entry`` field (which
    in a 15m system is ``open[idx+1]`` of the bar after the signal — up
    to 15 minutes stale relative to execution moment). Slippage/spread
    still apply on top of the live price. The runner wires this to a
    WebSocket markPrice feed; unit tests pass a plain lambda.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Callable


def canonical_direction(d: str) -> str:
    """Normalize engine/signal direction to {LONG, SHORT}.

    Engines emit "BULLISH"/"BEARISH"; some call sites pass "LONG"/"SHORT"
    directly. Everything downstream assumes LONG/SHORT, so we collapse
    here. Unknown forms pass through so the caller sees the failure.
    """
    up = str(d).upper()
    if up in ("LONG", "BULLISH", "BULL"):
        return "LONG"
    if up in ("SHORT", "BEARISH", "BEAR"):
        return "SHORT"
    return up


@dataclass
class Position:
    id: str
    engine: str
    symbol: str
    direction: str          # "LONG" | "SHORT" (normalized via canonical_direction)
    entry_price: float
    stop: float               # initial stop — NEVER modified; reference for risk math
    target: float
    size: float
    notional: float
    opened_at: str          # ISO8601
    opened_at_idx: int
    commission_paid: float
    unrealized_pnl: float = 0.0
    mtm_price: float | None = None
    bars_held: int = 0
    funding_accumulated: float = 0.0  # cumulative funding cost (positive drains LONG, credits SHORT)
    # Streaming-version of label_trade state — mutated tick-by-tick by
    # PositionManager. cur_stop rides up (LONG) / down (SHORT) as BE +
    # trailing trigger.
    cur_stop: float = 0.0
    be_done: bool = False
    trail_done: bool = False
    liq_long: float = -1.0     # sentinel; set at open for LONG when LEVERAGE>1
    liq_short: float = 0.0     # sentinel; set at open for SHORT when LEVERAGE>1


_id_counter = itertools.count(1)


def _next_id() -> str:
    return f"pos_{next(_id_counter):06d}"


@dataclass
class PaperExecutor:
    account_size: float = 10_000.0
    base_account_size: float = 10_000.0
    slippage: float = 0.0002
    spread: float = 0.0001
    commission: float = 0.0004

    def _scale(self) -> float:
        if self.base_account_size <= 0:
            return 1.0
        return self.account_size / self.base_account_size

    def open(
        self,
        signal: dict,
        opened_at_idx: int,
        opened_at_iso: str,
        live_price_fn: Callable[[str], float | None] | None = None,
    ) -> Position:
        direction = canonical_direction(signal["direction"])
        stop = float(signal["stop"])
        target = float(signal["target"])
        size_native = float(signal.get("size") or 0.0)
        size_scaled = size_native * self._scale()
        symbol = str(signal["symbol"])

        signal_entry = float(signal["entry"])
        entry_raw = signal_entry
        if live_price_fn is not None:
            try:
                live_px = live_price_fn(symbol)
            except Exception:  # noqa: BLE001 — never let a bad feed crash opens
                live_px = None
            if live_px is not None and live_px > 0:
                entry_raw = float(live_px)

        if direction == "LONG":
            entry_fill = entry_raw * (1.0 + self.slippage) + self.spread
        else:
            entry_fill = entry_raw * (1.0 - self.slippage) - self.spread

        commission_paid = entry_fill * size_scaled * self.commission
        notional = entry_fill * size_scaled

        # Liquidation thresholds — reuse core.signals._liq_prices so paper
        # matches backtest exactly. Note _liq_prices speaks BULLISH/BEARISH.
        from core.signals import _liq_prices
        liq_long, liq_short = _liq_prices(
            entry_fill, "BULLISH" if direction == "LONG" else "BEARISH")

        return Position(
            id=_next_id(),
            engine=str(signal.get("strategy") or signal.get("engine") or "UNKNOWN").upper(),
            symbol=symbol,
            direction=direction,
            entry_price=entry_fill,
            stop=stop,
            target=target,
            size=size_scaled,
            notional=notional,
            opened_at=opened_at_iso,
            opened_at_idx=opened_at_idx,
            commission_paid=commission_paid,
            cur_stop=stop,
            liq_long=liq_long,
            liq_short=liq_short,
        )
