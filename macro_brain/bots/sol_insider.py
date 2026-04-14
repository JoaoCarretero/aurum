"""SOL Insider Wallet — follow large traders on Solana (scaffold).

Intended sources (when wired):
  - Helius Enhanced Transactions (parsed swap events per watched wallet)
  - Solana RPC getSignaturesForAddress for raw activity
  - Birdeye/DeFiLlama for token context

Watch list (seed — will be learned over time):
  - Top PnL wallets from Dune dashboards (refreshed weekly)
  - Known VC treasury wallets (Multicoin, Jump, FTX estate)
  - Breakout traders flagged by on-chain analytics

Signals it will emit (category="bot_sol_insider"):
  headline: "WALLET <short>: BUY <token> $<X>k  (PnL tier <A/B/C>)"
  entities: [wallet, token_mint]
  impact:   0.2..0.9 based on wallet tier + size

Status: planned — watchlist bootstrap + Helius key pending.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from macro_brain.bots.base import BotWatcher


class SolInsiderBot(BotWatcher):
    slug = "sol_insider"
    label = "INSIDER WALLET"
    network = "SOL"
    tagline = "follow smart-money wallets · helius"
    color = "#5a2f88"
    status = "planned"

    def fetch(self, since: datetime | None = None) -> Iterable[dict]:
        return
        yield  # pragma: no cover
