"""Macro Brain — bots layer.

Watchers/signal-emitters that produce events/alerts feeding the cérebro.
Not execution engines. Zero order placement here. They observe on-chain,
order flow, insider feeds — and publish events into the macro store.

Layered brain:
  data_ingestion  →  macro feeds (news, rates, TVL, CFTC)
  bots            →  surgical watchers (whale tx, new launches, liquidations)
  thesis          →  regime + theses generator
  position        →  paper portfolio from theses
"""
from __future__ import annotations

from macro_brain.bots.base import BotWatcher, BotDescriptor
from macro_brain.bots.sol_sniper import SolSniperBot
from macro_brain.bots.sol_insider import SolInsiderBot
from macro_brain.bots.hl_liquidation import HLLiquidationBot
from macro_brain.bots.hl_whale import HLWhaleBot

ALL_BOTS: list[type[BotWatcher]] = [
    SolSniperBot,
    SolInsiderBot,
    HLLiquidationBot,
    HLWhaleBot,
]


def list_descriptors() -> list[BotDescriptor]:
    return [cls().describe() for cls in ALL_BOTS]


__all__ = [
    "BotWatcher", "BotDescriptor", "ALL_BOTS", "list_descriptors",
    "SolSniperBot", "SolInsiderBot", "HLLiquidationBot", "HLWhaleBot",
]
