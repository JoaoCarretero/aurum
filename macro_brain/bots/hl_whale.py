"""HL Whale Tracker — Hyperliquid large-position monitor.

Uses Hyperliquid's public /info endpoint (no key required):
  POST {"type":"clearinghouseState","user":"0x..."}

Returns that user's full portfolio — assetPositions with size/side/entry/pnl.

Behavior:
  1. For each address in HL_WHALE_WATCH_ADDRESSES (config/macro_params.py),
     fetch clearinghouseState.
  2. Snapshot each non-zero position into whale_snapshots.
  3. Diff vs prior snapshot for same (address, asset). Emit event when
     |size_usd_now - size_usd_prev| >= HL_WHALE_MIN_DELTA_USD.
  4. Also emit on a brand-new position opening (prev size 0).

Status lifecycle:
  - empty watchlist          → scaffolded
  - watchlist set + fetch OK → live
  - fetch errors on all addr → degraded
"""
from __future__ import annotations

import json as _json
import logging
from datetime import datetime
from typing import Iterable
from urllib.request import Request, urlopen

from config.macro_params import (
    HL_WHALE_WATCH_ADDRESSES, HL_WHALE_MIN_DELTA_USD,
)
from macro_brain.bots.base import BotWatcher, BotDescriptor
from macro_brain.persistence.store import (
    insert_whale_snapshot, latest_whale_snapshot,
)

log = logging.getLogger("macro_brain.bots.hl_whale")

_API = "https://api.hyperliquid.xyz/info"
_VENUE = "hyperliquid"


def _post(body: dict, timeout: int = 15) -> dict | list | None:
    data = _json.dumps(body).encode("utf-8")
    req = Request(_API, data=data, method="POST",
                  headers={"Content-Type": "application/json",
                           "User-Agent": "AURUM-MacroBrain/0.1"})
    with urlopen(req, timeout=timeout) as resp:
        return _json.loads(resp.read())


def _short(addr: str) -> str:
    return f"{addr[:6]}…{addr[-4:]}" if len(addr) > 12 else addr


class HLWhaleBot(BotWatcher):
    slug = "hl_whale"
    label = "WHALE TRACKER"
    network = "HYPE"
    tagline = "top-PnL address monitor · HL public info"
    color = "#06B6D4"

    @property  # type: ignore[override]
    def status(self):  # dynamic status
        if not HL_WHALE_WATCH_ADDRESSES:
            return "scaffolded"
        return self._last_status

    _last_status: str = "scaffolded"

    def describe(self) -> BotDescriptor:
        notes = (
            f"{len(HL_WHALE_WATCH_ADDRESSES)} addresses watched"
            if HL_WHALE_WATCH_ADDRESSES
            else "no watch addresses — set AURUM_HL_WHALES env or config"
        )
        return BotDescriptor(
            slug=self.slug, label=self.label, network=self.network,
            status=self.status, tagline=self.tagline, color=self.color,
            notes=notes,
        )

    def fetch(self, since: datetime | None = None) -> Iterable[dict]:
        addresses = list(HL_WHALE_WATCH_ADDRESSES)
        if not addresses:
            return
        ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
        successes = 0
        failures = 0

        for addr in addresses:
            try:
                state = _post({"type": "clearinghouseState", "user": addr})
            except Exception as e:
                log.warning(f"whale {_short(addr)}: state fetch failed: {e}")
                failures += 1
                continue
            if not isinstance(state, dict):
                failures += 1
                continue
            successes += 1
            yield from self._process_state(ts, addr, state)

        if successes == 0 and failures > 0:
            self._last_status = "degraded"
        else:
            self._last_status = "live"

    def _process_state(self, ts: str, addr: str, state: dict) -> Iterable[dict]:
        positions = state.get("assetPositions") or []
        for entry in positions:
            pos = entry.get("position") or {}
            coin = pos.get("coin")
            if not coin:
                continue
            try:
                szi = float(pos.get("szi") or 0)          # signed size (asset)
                entry_px = float(pos.get("entryPx") or 0) or None
                mark_px = float(pos.get("positionValue") or 0) / abs(szi) \
                          if szi else None
                size_usd = abs(float(pos.get("positionValue") or 0))
                lev_info = pos.get("leverage") or {}
                lev = float(lev_info.get("value") or 0) or None
            except (TypeError, ValueError):
                continue

            side = "LONG" if szi > 0 else ("SHORT" if szi < 0 else "FLAT")
            if side == "FLAT" or size_usd < 1.0:
                continue

            prev = latest_whale_snapshot(_VENUE, addr, coin)
            prev_size = float(prev["size_usd"]) if prev else 0.0
            prev_side = prev["side"] if prev else None

            insert_whale_snapshot(
                venue=_VENUE, address=addr, asset=coin, side=side,
                size_usd=size_usd, leverage=lev,
                entry_px=entry_px, mark_px=mark_px, raw=pos,
            )

            delta = size_usd - prev_size
            flipped = prev_side and prev_side != side
            opened = prev_size == 0.0
            # Emit on open, flip, or absolute delta over threshold
            if not (opened or flipped or abs(delta) >= HL_WHALE_MIN_DELTA_USD):
                continue

            verb = (
                "OPEN" if opened
                else "FLIP" if flipped
                else ("ADD" if delta > 0 else "CUT")
            )
            headline = (
                f"WHALE {_short(addr)}: {verb} {side} {coin} "
                f"${size_usd:,.0f}  (Δ${delta:+,.0f})"
            )
            if lev:
                headline += f"  lev {lev:.1f}x"

            # Impact scaling: $100k→0.2, $1M→0.5, $10M→0.8, cap 0.9
            import math
            impact = min(0.9, 0.2 + 0.3 * max(0.0, math.log10(
                max(abs(delta), 1.0) / 100_000.0
            )))

            yield {
                "type": "event", "ts": ts,
                "source": self.slug, "category": "bot_hl_whale",
                "headline": headline[:240],
                "body": "",
                "entities": [addr, coin],
                "sentiment": 0.0,
                "impact": round(impact, 3),
            }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from macro_brain.persistence.store import init_db, recent_events
    init_db()
    bot = HLWhaleBot()
    desc = bot.describe()
    print(f"{desc.slug} — status={desc.status} — {desc.notes}")
    r = bot.run()
    print(f"result: {r}")
    for e in recent_events(source="hl_whale", limit=10):
        print(f"  {e['ts']}  {e['headline']}")
