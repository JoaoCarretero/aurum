"""DeFi collector — TVL + protocol rankings per chain via DefiLlama.

Free, no key. APIs:
  /v2/chains                     TVL por chain
  /v2/historicalChainTvl/{chain} histórico
  /protocols                     rankings top protocols (heavy — grab top 20)

Métricas ingested:
  DEFI_<CHAIN>_TVL              e.g. DEFI_ETHEREUM_TVL
  DEFI_<CHAIN>_TVL_CHG_1D       daily change %
  DEFI_TOTAL_TVL                aggregated
  DEFI_BTC_LOCKED               BTC in DeFi across chains (Llama tracks)
"""
from __future__ import annotations

import json as _json
import logging
import time
from datetime import datetime
from typing import Iterable
from urllib.request import Request, urlopen

from macro_brain.data_ingestion.base import Collector

log = logging.getLogger("macro_brain.ingest.defi")

_BASE = "https://api.llama.fi"

# Chains que interessam — traduz nome Llama → our label
_CHAINS = {
    "Ethereum":   "ETHEREUM",
    "Solana":     "SOLANA",
    "Hyperliquid L1": "HYPERLIQUID",
    "Hyperliquid": "HYPERLIQUID",
    "BSC":        "BSC",
    "Base":       "BASE",
    "Arbitrum":   "ARBITRUM",
    "Tron":       "TRON",
    "Polygon":    "POLYGON",
    "Avalanche":  "AVALANCHE",
    "Optimism":   "OPTIMISM",
    "Bitcoin":    "BITCOIN",
    "Sui":        "SUI",
    "TON":        "TON_CHAIN",
    "Aptos":      "APTOS",
    "Near":       "NEAR_CHAIN",
}


class DeFiLlamaCollector(Collector):
    name = "defillama"
    category = "defi"

    def fetch(self, since: datetime | None = None) -> Iterable[dict]:
        ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")

        # Chains TVL
        try:
            req = Request(f"{_BASE}/v2/chains",
                          headers={"User-Agent": "AURUM-MacroBrain/0.1"})
            with urlopen(req, timeout=20) as resp:
                chains = _json.loads(resp.read())
        except Exception as e:
            log.warning(f"chains fetch failed: {e}")
            chains = []

        total_tvl = 0.0
        for c in chains:
            name = c.get("name") or c.get("chain") or ""
            tvl = c.get("tvl") or c.get("totalTvl") or 0
            try: tvl = float(tvl)
            except (TypeError, ValueError): continue
            total_tvl += tvl
            label = _CHAINS.get(name)
            if label:
                yield {"type": "macro_data", "ts": ts,
                       "metric": f"DEFI_{label}_TVL",
                       "value": tvl, "source": self.name}
                # 1d change if available
                chg = c.get("change_1d")
                if chg is not None:
                    try:
                        yield {"type": "macro_data", "ts": ts,
                               "metric": f"DEFI_{label}_TVL_CHG_1D",
                               "value": float(chg), "source": self.name}
                    except (TypeError, ValueError): pass

        if total_tvl:
            yield {"type": "macro_data", "ts": ts,
                   "metric": "DEFI_TOTAL_TVL",
                   "value": total_tvl, "source": self.name}

        # Top protocols (heavy — limit)
        time.sleep(1.0)
        try:
            req = Request(f"{_BASE}/protocols",
                          headers={"User-Agent": "AURUM-MacroBrain/0.1"})
            with urlopen(req, timeout=30) as resp:
                protos = _json.loads(resp.read())
        except Exception as e:
            log.warning(f"protocols failed: {e}")
            return

        # Sort by TVL and emit top 15 as events (not macro_data to avoid bloat)
        try:
            protos_sorted = sorted(
                protos, key=lambda p: (p.get("tvl") or 0), reverse=True
            )[:15]
        except Exception:
            protos_sorted = []

        for p in protos_sorted:
            yield {
                "type": "event", "ts": ts,
                "source": self.name, "category": "defi",
                "headline": f"TOP PROTO: {p.get('name', '?')[:40]}  "
                            f"TVL ${p.get('tvl', 0):,.0f}  "
                            f"chain {(p.get('chain') or '?')[:20]}",
                "body": (p.get("description") or "")[:200],
                "entities": [p.get("name", "?"), p.get("chain", "?")],
                "sentiment": 0.0,
                "impact": min(1.0, (p.get("tvl") or 0) / 10e9),
            }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from macro_brain.persistence.store import init_db, latest_macro, recent_events
    init_db()
    r = DeFiLlamaCollector().run()
    print(f"\nResult: {r}")
    print("\nTop chains TVL:")
    for label in ["ETHEREUM", "SOLANA", "BSC", "BASE", "ARBITRUM",
                  "TRON", "POLYGON", "HYPERLIQUID"]:
        lat = latest_macro(f"DEFI_{label}_TVL", n=1)
        if lat:
            print(f"  {label:<14} ${lat[0]['value']:>14,.0f}")
    total = latest_macro("DEFI_TOTAL_TVL", n=1)
    if total:
        print(f"  {'TOTAL':<14} ${total[0]['value']:>14,.0f}")

    print("\nTop protocols (recent events):")
    for e in recent_events(category="defi", limit=5):
        print(f"  {e['headline']}")
