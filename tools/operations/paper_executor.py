"""Paper executor — signal to open position with slippage/spread/commission.

Mirrors `engines.live.OrderManager.paper_fill` logic + commission deduction.
Size is scaled linearly from the scan's native size (calibrated for
base_account_size) to the runner's configured account_size. This is a
CALLER-side hack — core.portfolio.position_size is NOT touched (CORE
PROTECTED). If position_size ever becomes non-linear in equity, this hack
needs revisit.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass


@dataclass
class Position:
    id: str
    engine: str
    symbol: str
    direction: str          # "LONG" | "SHORT"
    entry_price: float
    stop: float
    target: float
    size: float
    notional: float
    opened_at: str          # ISO8601
    opened_at_idx: int
    commission_paid: float
    unrealized_pnl: float = 0.0
    mtm_price: float | None = None
    bars_held: int = 0


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

    def open(self, signal: dict, opened_at_idx: int, opened_at_iso: str) -> Position:
        direction = str(signal["direction"]).upper()
        entry_raw = float(signal["entry"])
        stop = float(signal["stop"])
        target = float(signal["target"])
        size_native = float(signal.get("size") or 0.0)
        size_scaled = size_native * self._scale()

        if direction == "LONG":
            entry_fill = entry_raw * (1.0 + self.slippage) + self.spread
        else:
            entry_fill = entry_raw * (1.0 - self.slippage) - self.spread

        commission_paid = entry_fill * size_scaled * self.commission
        notional = entry_fill * size_scaled

        return Position(
            id=_next_id(),
            engine=str(signal.get("strategy") or signal.get("engine") or "UNKNOWN").upper(),
            symbol=str(signal["symbol"]),
            direction=direction,
            entry_price=entry_fill,
            stop=stop,
            target=target,
            size=size_scaled,
            notional=notional,
            opened_at=opened_at_iso,
            opened_at_idx=opened_at_idx,
            commission_paid=commission_paid,
        )
