"""On-chain metrics collector — Bitcoin network state.

Free APIs sem key:
  blockchain.info/stats         hashrate, difficulty, blocks, unconfirmed tx
  api.blockchain.info/charts    historical time-series
  mempool.space/api/v1          fee recommendations, mempool stats

Métricas coletadas:
  BTC_HASH_RATE      network hashrate (TH/s)
  BTC_DIFFICULTY     mining difficulty
  BTC_BLOCK_HEIGHT   latest block
  BTC_MEMPOOL_SIZE   unconfirmed txs count
  BTC_TX_FEE         avg tx fee (sats/vByte)
  BTC_MARKET_CAP     calculated from supply × spot
  BTC_24H_TX_VOLUME  24h on-chain USD volume
"""
from __future__ import annotations

import json as _json
import logging
from datetime import datetime
from typing import Iterable
from urllib.request import Request, urlopen

from macro_brain.data_ingestion.base import Collector

log = logging.getLogger("macro_brain.ingest.onchain")


class OnChainCollector(Collector):
    name = "onchain"
    category = "onchain"

    def fetch(self, since: datetime | None = None) -> Iterable[dict]:
        ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
        yield from self._blockchain_info(ts)
        yield from self._mempool_space(ts)

    def _blockchain_info(self, ts: str) -> Iterable[dict]:
        try:
            req = Request(
                "https://api.blockchain.info/stats",
                headers={"User-Agent": "AURUM-MacroBrain/0.1"},
            )
            with urlopen(req, timeout=15) as resp:
                data = _json.loads(resp.read())
        except Exception as e:
            log.warning(f"blockchain.info failed: {e}")
            return

        mapping = [
            ("hash_rate",        "BTC_HASH_RATE"),
            ("difficulty",       "BTC_DIFFICULTY"),
            ("n_blocks_total",   "BTC_BLOCK_HEIGHT"),
            ("minutes_between_blocks", "BTC_AVG_BLOCK_TIME_MIN"),
            ("n_tx",             "BTC_24H_TX_COUNT"),
            ("total_fees_btc",   "BTC_24H_FEES_BTC"),
            ("market_price_usd", "BTC_BC_INFO_PRICE"),
            ("trade_volume_usd", "BTC_24H_TRADE_VOLUME_USD"),
            ("miners_revenue_usd", "BTC_24H_MINER_REVENUE_USD"),
            ("n_btc_mined",      "BTC_24H_MINED"),
        ]
        for src_key, our_label in mapping:
            val = data.get(src_key)
            try: v = float(val)
            except (TypeError, ValueError): continue
            yield {"type": "macro_data", "ts": ts, "metric": our_label,
                   "value": v, "source": "blockchain.info"}

    def _mempool_space(self, ts: str) -> Iterable[dict]:
        try:
            req = Request(
                "https://mempool.space/api/v1/fees/recommended",
                headers={"User-Agent": "AURUM-MacroBrain/0.1"},
            )
            with urlopen(req, timeout=15) as resp:
                fees = _json.loads(resp.read())
        except Exception as e:
            log.warning(f"mempool.space fees failed: {e}")
            fees = {}

        fee_map = [
            ("fastestFee",   "BTC_FEE_FASTEST_SATVB"),
            ("halfHourFee",  "BTC_FEE_30MIN_SATVB"),
            ("hourFee",      "BTC_FEE_1H_SATVB"),
            ("economyFee",   "BTC_FEE_ECONOMY_SATVB"),
            ("minimumFee",   "BTC_FEE_MIN_SATVB"),
        ]
        for src_key, our_label in fee_map:
            val = fees.get(src_key)
            try: v = float(val)
            except (TypeError, ValueError): continue
            yield {"type": "macro_data", "ts": ts, "metric": our_label,
                   "value": v, "source": "mempool.space"}

        # Mempool size
        try:
            req = Request(
                "https://mempool.space/api/mempool",
                headers={"User-Agent": "AURUM-MacroBrain/0.1"},
            )
            with urlopen(req, timeout=15) as resp:
                mp = _json.loads(resp.read())
            if isinstance(mp, dict):
                if "count" in mp:
                    yield {"type": "macro_data", "ts": ts,
                           "metric": "BTC_MEMPOOL_COUNT",
                           "value": float(mp["count"]), "source": "mempool.space"}
                if "vsize" in mp:
                    yield {"type": "macro_data", "ts": ts,
                           "metric": "BTC_MEMPOOL_VSIZE",
                           "value": float(mp["vsize"]), "source": "mempool.space"}
        except Exception as e:
            log.warning(f"mempool.space mempool failed: {e}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from macro_brain.persistence.store import init_db, latest_macro
    init_db()
    r = OnChainCollector().run()
    print(f"\nResult: {r}")
    print("\nLatest on-chain:")
    for m in ["BTC_HASH_RATE", "BTC_DIFFICULTY", "BTC_BLOCK_HEIGHT",
              "BTC_MEMPOOL_COUNT", "BTC_FEE_FASTEST_SATVB",
              "BTC_24H_TX_COUNT", "BTC_24H_MINER_REVENUE_USD"]:
        latest = latest_macro(m, n=1)
        if latest:
            v = latest[0]["value"]
            print(f"  {m:<34} {v:>18,.2f}")
