"""Paper position manager — MTM, intrabar exit detection, funding.

Walks new OHLCV bars since last check. For each open position:
  - LONG:  stop hit if bar.low <= stop;   target hit if bar.high >= target
  - SHORT: stop hit if bar.high >= stop;  target hit if bar.low <= target
  - Both hit same bar -> stop wins (conservative, matches backtest tie-break)
  - Neither -> mark-to-market with bar.close + apply funding pro-rata

PnL accounting (on close):
  gross = (exit - entry) * size * dir_sign
  exit_commission = exit_price * size * commission
  pnl_after_fees = gross - pos.commission_paid - exit_commission

Entry commission was deducted by PaperExecutor at open-time; the returned
ClosedTrade tracks both entry and exit commission explicitly so the caller
can audit. The account's realized_pnl ingests pnl_after_fees directly.
"""
from __future__ import annotations

from dataclasses import dataclass
from tools.operations.paper_executor import Position


@dataclass
class ClosedTrade:
    id: str
    engine: str
    symbol: str
    direction: str
    entry_price: float
    exit_price: float
    stop: float
    target: float
    size: float
    opened_at: str
    closed_at: str
    exit_reason: str        # "stop" | "target" | "ks_abort" | "manual_flatten"
    pnl: float              # gross price delta * size
    pnl_after_fees: float   # gross - entry_commission - exit_commission
    r_multiple: float
    bars_held: int
    entry_commission: float
    exit_commission: float
    funding_paid: float


@dataclass
class PositionManager:
    commission: float = 0.0004
    funding_per_8h: float = 0.0001
    tick_sec: int = 900

    def _dir_sign(self, direction: str) -> int:
        return 1 if direction == "LONG" else -1

    def _apply_funding(self, pos: Position) -> float:
        """Apply funding for one tick pro-rata; returns funding paid (signed)."""
        delta = pos.notional * self.funding_per_8h * (self.tick_sec / (8 * 3600))
        if pos.direction == "LONG":
            pos.unrealized_pnl -= delta
            return delta
        else:
            pos.unrealized_pnl += delta
            return -delta

    def _close(self, pos: Position, exit_price: float, reason: str,
               closed_at: str) -> ClosedTrade:
        sign = self._dir_sign(pos.direction)
        gross = (exit_price - pos.entry_price) * pos.size * sign
        exit_commission = exit_price * pos.size * self.commission
        risk_per_unit = abs(pos.entry_price - pos.stop)
        r_multiple = 0.0
        if risk_per_unit > 0:
            r_multiple = (exit_price - pos.entry_price) * sign / risk_per_unit
        pnl_after_fees = gross - pos.commission_paid - exit_commission
        return ClosedTrade(
            id=pos.id, engine=pos.engine, symbol=pos.symbol,
            direction=pos.direction,
            entry_price=pos.entry_price, exit_price=exit_price,
            stop=pos.stop, target=pos.target, size=pos.size,
            opened_at=pos.opened_at, closed_at=closed_at,
            exit_reason=reason,
            pnl=round(gross, 4),
            pnl_after_fees=round(pnl_after_fees, 4),
            r_multiple=round(r_multiple, 3),
            bars_held=pos.bars_held,
            entry_commission=round(pos.commission_paid, 4),
            exit_commission=round(exit_commission, 4),
            funding_paid=0.0,
        )

    def check_exits(self, positions: list[Position], bars: list[dict]) -> list[ClosedTrade]:
        """Check each position against each bar. Returns closed trades.

        Side-effects on positions still open: updates mtm_price, unrealized_pnl,
        bars_held, and applies funding. Closed positions are NOT removed from
        the input list — caller filters via the returned ClosedTrade list.
        """
        closed: list[ClosedTrade] = []
        for pos in positions:
            closed_this = None
            for bar in bars:
                hi = float(bar["high"])
                lo = float(bar["low"])
                ts = str(bar.get("time") or "")
                if pos.direction == "LONG":
                    hit_stop = lo <= pos.stop
                    hit_tgt = hi >= pos.target
                else:
                    hit_stop = hi >= pos.stop
                    hit_tgt = lo <= pos.target
                # Both-hit tie -> stop wins (conservative, matches backtest)
                if hit_stop:
                    closed_this = self._close(pos, pos.stop, "stop", ts)
                    break
                if hit_tgt:
                    closed_this = self._close(pos, pos.target, "target", ts)
                    break
            if closed_this is not None:
                closed.append(closed_this)
            else:
                # MTM with last bar close
                last = bars[-1] if bars else None
                if last is not None:
                    mtm = float(last["close"])
                    sign = self._dir_sign(pos.direction)
                    pos.mtm_price = mtm
                    pos.unrealized_pnl = (mtm - pos.entry_price) * pos.size * sign
                    pos.bars_held += len(bars)
                    self._apply_funding(pos)
        return closed
