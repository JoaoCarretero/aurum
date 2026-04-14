"""Hyperliquid metrics collector — public API, no key.

Endpoints:
  https://api.hyperliquid.xyz/info         POST info requests

Metrics pulled:
  HL_TOTAL_OI                   total open interest across perps (USD)
  HL_24H_VOLUME                 24h volume
  HL_<TICKER>_FUNDING           funding rate per symbol
  HL_<TICKER>_OI                open interest per symbol
  HL_<TICKER>_PRICE             mid price

Tracks top 20 perps by volume.
"""
from __future__ import annotations

import json as _json
import logging
from datetime import datetime
from typing import Iterable
from urllib.request import Request, urlopen

from macro_brain.data_ingestion.base import Collector

log = logging.getLogger("macro_brain.ingest.hl")

_API = "https://api.hyperliquid.xyz/info"


def _post(body: dict, timeout: int = 15):
    data = _json.dumps(body).encode("utf-8")
    req = Request(_API, data=data, method="POST",
                  headers={"Content-Type": "application/json",
                           "User-Agent": "AURUM-MacroBrain/0.1"})
    with urlopen(req, timeout=timeout) as resp:
        return _json.loads(resp.read())


# Top perps on HL (by volume)
_TRACK = [
    "BTC", "ETH", "SOL", "HYPE", "XRP", "DOGE", "AVAX", "LINK",
    "ARB", "OP", "BNB", "ADA", "NEAR", "SUI", "APT", "TRX",
    "LTC", "UNI", "PEPE", "WIF",
]


class HyperliquidCollector(Collector):
    name = "hyperliquid"
    category = "hyperliquid"

    def fetch(self, since: datetime | None = None) -> Iterable[dict]:
        ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")

        # metaAndAssetCtxs retorna metadata + contexto por asset (OI, funding, mark price)
        try:
            response = _post({"type": "metaAndAssetCtxs"})
        except Exception as e:
            log.warning(f"metaAndAssetCtxs failed: {e}")
            return

        if not isinstance(response, list) or len(response) != 2:
            log.warning(f"unexpected response shape: {type(response)}")
            return

        meta, ctxs = response
        universe = meta.get("universe", []) if isinstance(meta, dict) else []

        total_oi_usd = 0.0
        for asset, ctx in zip(universe, ctxs):
            name = asset.get("name")
            if not name or name not in _TRACK:
                continue
            try:
                mark = float(ctx.get("markPx") or 0)
                funding = float(ctx.get("funding") or 0)
                oi = float(ctx.get("openInterest") or 0)  # size in asset units
                day_vol = float(ctx.get("dayNtlVlm") or 0)
            except (TypeError, ValueError):
                continue

            oi_usd = oi * mark
            total_oi_usd += oi_usd

            # Funding rates are hourly; annualize approximately (× 24 × 365)
            # Store the raw hourly rate per cycle.
            yield {"type": "macro_data", "ts": ts,
                   "metric": f"HL_{name}_PRICE",
                   "value": mark, "source": self.name}
            yield {"type": "macro_data", "ts": ts,
                   "metric": f"HL_{name}_FUNDING",
                   "value": funding * 100,  # as pct
                   "source": self.name}
            yield {"type": "macro_data", "ts": ts,
                   "metric": f"HL_{name}_OI_USD",
                   "value": oi_usd, "source": self.name}
            yield {"type": "macro_data", "ts": ts,
                   "metric": f"HL_{name}_VOL_24H",
                   "value": day_vol, "source": self.name}

        if total_oi_usd:
            yield {"type": "macro_data", "ts": ts,
                   "metric": "HL_TOTAL_OI",
                   "value": total_oi_usd, "source": self.name}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from macro_brain.persistence.store import init_db, latest_macro
    init_db()
    r = HyperliquidCollector().run()
    print(f"\nResult: {r}")
    print("\nHL snapshot:")
    total = latest_macro("HL_TOTAL_OI", n=1)
    if total:
        print(f"  TOTAL OI ${total[0]['value']:,.0f}")
    for name in ["BTC", "ETH", "SOL", "HYPE", "XRP"]:
        price = latest_macro(f"HL_{name}_PRICE", n=1)
        oi = latest_macro(f"HL_{name}_OI_USD", n=1)
        fund = latest_macro(f"HL_{name}_FUNDING", n=1)
        if price:
            p = price[0]['value']
            o_val = oi[0]['value'] if oi else 0
            f_val = fund[0]['value'] if fund else 0
            print(f"  {name:<6} ${p:>10,.3f}  OI ${o_val:>10,.0f}  funding {f_val:+.4f}%")
