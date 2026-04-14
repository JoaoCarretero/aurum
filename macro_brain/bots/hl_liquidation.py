"""HL Liquidation Bot — Hyperliquid liquidation cascade detector (scaffold).

Intended sources (when wired):
  - HL WebSocket subscription: {"type":"liquidations"} (all symbols)
  - HL /info type=clearinghouseState per whale subaccount for stress view
  - OI + funding from existing macro_brain.data_ingestion.hyperliquid

Signals it will emit (category="bot_hl_liq"):
  headline: "LIQ CASCADE <SYMBOL>: $<X>M in <N>m (OI -<Y>%)"
  entities: [symbol]
  impact:   0.3..1.0 scaled by $ volume + cascade speed

Detection rule (first version):
  window = last 5 min
  if sum(liq_notional) > 3M USD and OI drop > 2% → emit

Status: planned — HL WS client not built yet.
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from macro_brain.bots.base import BotWatcher


class HLLiquidationBot(BotWatcher):
    slug = "hl_liquidation"
    label = "LIQUIDATION BOT"
    network = "HYPE"
    tagline = "cascade detector · HL websocket"
    color = "#1f7a8c"
    status = "planned"

    def fetch(self, since: datetime | None = None) -> Iterable[dict]:
        return
        yield  # pragma: no cover
