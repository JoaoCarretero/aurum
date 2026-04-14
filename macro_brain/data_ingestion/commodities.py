"""CoinGecko commodities collector — crypto + market aggregates.

Free tier: 10-30 req/min. No API key required.

Pulls:
  - BTC/ETH/etc prices + market cap
  - BTC dominance
  - Total crypto market cap
  - 24h global volume

Docs: https://www.coingecko.com/en/api/documentation
"""
from __future__ import annotations

import json as _json
import logging
import time
from datetime import datetime
from typing import Iterable
from urllib.request import Request, urlopen

from macro_brain.data_ingestion.base import Collector

log = logging.getLogger("macro_brain.ingest.commodities")

_GLOBAL = "https://api.coingecko.com/api/v3/global"
_PRICE = "https://api.coingecko.com/api/v3/simple/price"

# CoinGecko IDs para nosso universe
_COIN_IDS = {
    "bitcoin":     "BTC_SPOT",
    "ethereum":    "ETH_SPOT",
    "solana":      "SOL_SPOT",
    "binancecoin": "BNB_SPOT",
}


class CoinGeckoCollector(Collector):
    """Crypto prices + global dominance. Snapshot every fetch."""

    name = "coingecko"
    category = "commodities"

    def fetch(self, since: datetime | None = None) -> Iterable[dict]:
        ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")

        # Global: BTC dominance, total market cap
        try:
            req = Request(_GLOBAL, headers={"User-Agent": "AURUM-MacroBrain/0.1"})
            with urlopen(req, timeout=15) as resp:
                g = _json.loads(resp.read()).get("data", {})
        except Exception as e:
            log.warning(f"global fetch failed: {e}")
            g = {}

        if g:
            btc_dom = g.get("market_cap_percentage", {}).get("btc")
            total_mcap = g.get("total_market_cap", {}).get("usd")
            total_vol = g.get("total_volume", {}).get("usd")

            if btc_dom is not None:
                yield {"type": "macro_data", "ts": ts, "metric": "BTC_DOMINANCE",
                       "value": float(btc_dom), "source": self.name}
            if total_mcap is not None:
                yield {"type": "macro_data", "ts": ts, "metric": "TOTAL_CRYPTO_MCAP",
                       "value": float(total_mcap), "source": self.name}
            if total_vol is not None:
                yield {"type": "macro_data", "ts": ts, "metric": "TOTAL_CRYPTO_VOL_24H",
                       "value": float(total_vol), "source": self.name}

        # Per-coin prices
        time.sleep(1.1)  # be nice to rate limit
        try:
            ids = ",".join(_COIN_IDS.keys())
            url = f"{_PRICE}?ids={ids}&vs_currencies=usd&include_24hr_change=true"
            req = Request(url, headers={"User-Agent": "AURUM-MacroBrain/0.1"})
            with urlopen(req, timeout=15) as resp:
                prices = _json.loads(resp.read())
        except Exception as e:
            log.warning(f"price fetch failed: {e}")
            prices = {}

        for coin_id, metric in _COIN_IDS.items():
            entry = prices.get(coin_id, {})
            usd = entry.get("usd")
            change_24h = entry.get("usd_24h_change")
            if usd is not None:
                yield {"type": "macro_data", "ts": ts, "metric": metric,
                       "value": float(usd), "source": self.name}
            if change_24h is not None:
                yield {"type": "macro_data", "ts": ts, "metric": f"{metric}_CHG_24H",
                       "value": float(change_24h), "source": self.name}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-5s  %(message)s")
    from macro_brain.persistence.store import init_db, latest_macro

    init_db()
    result = CoinGeckoCollector().run()
    print(f"\nCoinGecko result: {result}")

    for m in ["BTC_DOMINANCE", "TOTAL_CRYPTO_MCAP", "BTC_SPOT", "ETH_SPOT"]:
        latest = latest_macro(m, n=1)
        if latest:
            r = latest[0]
            print(f"  {m:<22} {r['ts'][:19]}  {r['value']:>14,.2f}")
