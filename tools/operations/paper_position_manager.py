"""Paper position manager — MTM, intrabar exit detection, funding.

Mirrors ``core.signals.label_trade`` for streaming ticks: each new bar
runs the same intrabar logic backtest applies, but state (cur_stop,
be_done, trail_done) is carried on the Position between calls because
we see bars one-by-one instead of a full DataFrame.

For each bar, per position:
  1. LIQUIDATION [L7]: if bar wicked into liq_long (LONG) / liq_short
     (SHORT), position is closed at liq_price with reason "liquidation".
     When LEVERAGE=1.0 the sentinels make this a no-op.
  2. BREAK-EVEN: after price moves ``TRAIL_BE_MULT × risk`` in favour,
     cur_stop moves to entry. Tracked by ``be_done``.
  3. TRAILING: after price moves ``TRAIL_ACTIVATE_MULT × risk``, cur_stop
     follows ``bar_extreme ± TRAIL_DISTANCE_MULT × risk`` every bar.
     Tracked by ``trail_done``.
  4. STOP (at cur_stop): LONG low<=cur_stop / SHORT high>=cur_stop.
     Reason reflects phase: "stop_initial" | "breakeven" | "trailing".
  5. TARGET: LONG high>=target / SHORT low<=target → "target".
  6. Ties go to stop (conservative, matches backtest tie-break).
  7. If no exit, MTM with bar.close and apply pro-rata funding.

Calibration parity: paper now produces the same results as backtest
given the same OHLCV (modulo slippage/spread/commission, which both
systems apply identically). This closes the Sharpe-drift loophole where
paper sub-reported backtest edge because it lacked trailing stops.
"""
from __future__ import annotations

from dataclasses import dataclass

from config.params import (
    TRAIL_BE_MULT,
    TRAIL_ACTIVATE_MULT,
    TRAIL_DISTANCE_MULT,
)
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
        """Accumulate funding for one tick pro-rata into pos.funding_accumulated.

        For LONG, funding is a cost (positive delta drains equity). For SHORT,
        funding is a credit (negative accumulated value). Returns the signed
        delta applied this tick for caller observability (not used for PnL —
        the cumulative value lives on the Position and is subtracted at close).
        """
        delta = pos.notional * self.funding_per_8h * (self.tick_sec / (8 * 3600))
        if pos.direction == "LONG":
            pos.funding_accumulated += delta
            return delta
        else:
            pos.funding_accumulated -= delta
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
        # Subtract funding_accumulated: for LONG it's positive (drain), for
        # SHORT it's negative (credit increases pnl_after_fees).
        pnl_after_fees = gross - pos.commission_paid - exit_commission - pos.funding_accumulated
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
            funding_paid=round(pos.funding_accumulated, 4),
        )

    def check_exits(self, positions: list[Position], bars: list[dict]) -> list[ClosedTrade]:
        """Walk bars for each position, mirroring label_trade semantics.

        Updates position state (cur_stop, be_done, trail_done, funding,
        bars_held, mtm_price, unrealized_pnl) in place. Closed positions
        produce a ClosedTrade in the return list; the caller is
        responsible for removing them from `positions`.

        Returned trades' `exit_reason` matches the backtest vocabulary:
        "stop_initial" | "breakeven" | "trailing" | "target" |
        "liquidation". Paper layer (`millennium_paper._flatten_all`) may
        also emit "ks_abort" or "manual_flatten" through `_close` directly.
        """
        closed: list[ClosedTrade] = []
        for pos in positions:
            events: list[tuple[str, str, float | None]] = []  # (event, ts, new_stop)
            closed_this = self._walk_bars(pos, bars, events)
            if closed_this is not None:
                closed.append(closed_this)
            else:
                last = bars[-1] if bars else None
                if last is not None:
                    self._apply_funding(pos)
                    mtm = float(last["close"])
                    sign = self._dir_sign(pos.direction)
                    pos.mtm_price = mtm
                    gross_mtm = (mtm - pos.entry_price) * pos.size * sign
                    pos.unrealized_pnl = gross_mtm - pos.funding_accumulated
                    pos.bars_held += len(bars)
            # Expose stop-management events on the Position so the caller
            # (paper runner) can notify Telegram. Not persisted — consumed
            # on the next tick.
            pos._pending_stop_events = events  # type: ignore[attr-defined]
        return closed

    def _walk_bars(self, pos: Position, bars: list[dict],
                   events: list) -> ClosedTrade | None:
        """Intrabar processing. Returns the ClosedTrade or None.

        Implements the same ordering as label_trade: liquidation check
        first, then BE/trail trigger updates, then current-stop check,
        then target check. Both-hit in the same bar → stop wins.
        """
        risk = abs(pos.entry_price - pos.stop)
        for bar in bars:
            hi = float(bar["high"])
            lo = float(bar["low"])
            ts = str(bar.get("time") or "")

            if pos.direction == "LONG":
                # [L7] Liquidation precedes anything else
                if lo <= pos.liq_long:
                    return self._close(pos, pos.liq_long, "liquidation", ts)

                # Break-even: after price travelled TRAIL_BE_MULT × risk
                if not pos.be_done and risk > 0 and \
                        hi >= pos.entry_price + TRAIL_BE_MULT * risk:
                    pos.cur_stop = pos.entry_price
                    pos.be_done = True
                    events.append(("breakeven", ts, pos.cur_stop))

                # Trail activation + every-bar update
                if pos.be_done and not pos.trail_done and \
                        hi >= pos.entry_price + TRAIL_ACTIVATE_MULT * risk:
                    new_stop = max(pos.cur_stop, hi - TRAIL_DISTANCE_MULT * risk)
                    pos.cur_stop = new_stop
                    pos.trail_done = True
                    events.append(("trail_start", ts, pos.cur_stop))
                elif pos.trail_done:
                    new_stop = max(pos.cur_stop, hi - TRAIL_DISTANCE_MULT * risk)
                    if new_stop > pos.cur_stop:
                        pos.cur_stop = new_stop
                        events.append(("trail_update", ts, pos.cur_stop))

                # Stop check (uses cur_stop, not initial stop)
                if lo <= pos.cur_stop:
                    reason = ("trailing" if pos.trail_done else
                              ("breakeven" if pos.be_done else "stop_initial"))
                    return self._close(pos, pos.cur_stop, reason, ts)

                # Target
                if hi >= pos.target:
                    return self._close(pos, pos.target, "target", ts)

            else:  # SHORT
                # [L7] Liquidation
                if hi >= pos.liq_short:
                    return self._close(pos, pos.liq_short, "liquidation", ts)

                if not pos.be_done and risk > 0 and \
                        lo <= pos.entry_price - TRAIL_BE_MULT * risk:
                    pos.cur_stop = pos.entry_price
                    pos.be_done = True
                    events.append(("breakeven", ts, pos.cur_stop))

                if pos.be_done and not pos.trail_done and \
                        lo <= pos.entry_price - TRAIL_ACTIVATE_MULT * risk:
                    new_stop = min(pos.cur_stop, lo + TRAIL_DISTANCE_MULT * risk)
                    pos.cur_stop = new_stop
                    pos.trail_done = True
                    events.append(("trail_start", ts, pos.cur_stop))
                elif pos.trail_done:
                    new_stop = min(pos.cur_stop, lo + TRAIL_DISTANCE_MULT * risk)
                    if new_stop < pos.cur_stop:
                        pos.cur_stop = new_stop
                        events.append(("trail_update", ts, pos.cur_stop))

                if hi >= pos.cur_stop:
                    reason = ("trailing" if pos.trail_done else
                              ("breakeven" if pos.be_done else "stop_initial"))
                    return self._close(pos, pos.cur_stop, reason, ts)

                if lo <= pos.target:
                    return self._close(pos, pos.target, "target", ts)
        return None
