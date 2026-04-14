"""SOL Sniper — new token launch detector (scaffold).

Intended sources (when wired):
  - pump.fun /coins (recent launches, bonding curve state)
  - Raydium new-pool events via Solana RPC getSignaturesForAddress
  - Jupiter price API for initial liquidity sanity check

Signals it will emit (category="bot_sol_sniper"):
  headline: "NEW LAUNCH: <TICKER> mcap $<X>k liq $<Y>k"
  entities: [mint_address, deployer]
  impact:   0.1..0.9 based on liquidity + deployer reputation

Status: planned — no live polling yet.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from macro_brain.bots.base import BotWatcher


class SolSniperBot(BotWatcher):
    slug = "sol_sniper"
    label = "SNIPER BOT"
    network = "SOL"
    tagline = "new token launches · pump.fun + raydium"
    color = "#5a2f88"
    status = "planned"

    def fetch(self, since: datetime | None = None) -> Iterable[dict]:
        return
        yield  # pragma: no cover
