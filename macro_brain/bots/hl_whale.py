"""HL Whale Tracker — Hyperliquid large-position monitor (scaffold).

Intended sources (when wired):
  - HL /info type=userState for a curated list of known whale addresses
  - HL /info type=openOrders for limit order placement signals
  - HL leaderboard page scrape (public, weekly refresh) to find new whales

Watch list (seed):
  - Top 50 addresses by PnL from HL public leaderboard
  - Known market makers (identified via consistent book presence)

Signals it will emit (category="bot_hl_whale"):
  headline: "WHALE <short>: OPEN <LONG/SHORT> <SYMBOL> $<X>M  lev <Nx>"
  entities: [address, symbol]
  impact:   0.2..0.9 scaled by $ size and leverage

Status: planned — leaderboard scraper + address watchlist pending.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from macro_brain.bots.base import BotWatcher


class HLWhaleBot(BotWatcher):
    slug = "hl_whale"
    label = "WHALE TRACKER"
    network = "HYPE"
    tagline = "top-PnL address monitor · HL public info"
    color = "#1f7a8c"
    status = "planned"

    def fetch(self, since: datetime | None = None) -> Iterable[dict]:
        return
        yield  # pragma: no cover
