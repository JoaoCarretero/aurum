"""Paper runner account state — balance, equity, drawdown tracking.

Source of truth consumed by KSLiveGate (drawdown thresholds),
MetricsStreamer (snapshot -> account.json), and Telegram pings.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PaperAccount:
    initial_balance: float
    balance: float = field(init=False)
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    peak_equity: float = field(init=False)

    def __post_init__(self) -> None:
        self.balance = self.initial_balance
        self.peak_equity = self.initial_balance

    @property
    def equity(self) -> float:
        return self.balance + self.unrealized_pnl

    @property
    def drawdown(self) -> float:
        return max(0.0, self.peak_equity - self.equity)

    @property
    def drawdown_pct(self) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return self.drawdown / self.peak_equity * 100.0

    def apply_realized(self, pnl_after_fees: float) -> None:
        """Called on position close. Updates balance and peak."""
        self.balance += pnl_after_fees
        self.realized_pnl += pnl_after_fees
        if self.equity > self.peak_equity:
            self.peak_equity = self.equity

    def set_unrealized(self, total_unrealized: float) -> None:
        """Called each tick with sum of open-position unrealized PnL."""
        self.unrealized_pnl = total_unrealized
        if self.equity > self.peak_equity:
            self.peak_equity = self.equity

    def snapshot(self) -> dict:
        return {
            "initial_balance": round(self.initial_balance, 2),
            "current_balance": round(self.balance, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "equity": round(self.equity, 2),
            "peak_equity": round(self.peak_equity, 2),
            "drawdown": round(self.drawdown, 2),
            "drawdown_pct": round(self.drawdown_pct, 3),
        }
