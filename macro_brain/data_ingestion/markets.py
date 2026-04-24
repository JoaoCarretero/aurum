"""Yahoo Finance markets collector — commodities, forex, rates, indices.

Usa chart API pública (unofficial): query1.finance.yahoo.com/v7/finance/chart
Sem API key. Cobertura:

  Commodities:   Gold (GC=F), Silver (SI=F), WTI (CL=F), Copper (HG=F),
                 Nat Gas (NG=F), Brent (BZ=F)
  Rates:         2Y (^IRX/5Y sub), 10Y (^TNX), 30Y (^TYX)
  Forex:         DXY (DX-Y.NYB), EUR/USD, USD/JPY, GBP/USD, USD/CNY
  Equity vol:    VIX (^VIX)
  Index:         SP500 (^GSPC), Nasdaq (^IXIC)
  International: Nikkei (^N225), DAX (^GDAXI), FTSE (^FTSE), HSI (^HSI)

Failure modes:
  - Yahoo pode bloquear UA/throttle — collector é robusto, skip individual
  - Symbols ocasionalmente reprocessam; retry manual se precisar
"""
from __future__ import annotations

import json as _json
import logging
import time
from datetime import datetime
from typing import Iterable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from macro_brain.data_ingestion.base import Collector

log = logging.getLogger("macro_brain.ingest.markets")

_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/"

# symbol → (our_metric_label, category)
_SYMBOLS = {
    # Commodities
    "GC=F":       ("GOLD", "commodities"),
    "SI=F":       ("SILVER", "commodities"),
    "CL=F":       ("WTI_OIL", "commodities"),
    "BZ=F":       ("BRENT_OIL", "commodities"),
    "HG=F":       ("COPPER", "commodities"),
    "NG=F":       ("NAT_GAS", "commodities"),
    # Rates
    "^TNX":       ("US10Y", "rates"),
    "^TYX":       ("US30Y", "rates"),
    "^FVX":       ("US5Y", "rates"),
    "^IRX":       ("US13W", "rates"),
    # FX + vol
    "DX-Y.NYB":   ("DXY", "forex"),
    "EURUSD=X":   ("EUR_USD", "forex"),
    "JPY=X":      ("USD_JPY", "forex"),
    "GBPUSD=X":   ("GBP_USD", "forex"),
    "CNY=X":      ("USD_CNY", "forex"),
    "^VIX":       ("VIX", "volatility"),
    # Equity indices
    "^GSPC":      ("SP500", "equity_index"),
    "^IXIC":      ("NASDAQ", "equity_index"),
    "^N225":      ("NIKKEI", "equity_index"),
    "^GDAXI":     ("DAX", "equity_index"),
    "^FTSE":      ("FTSE", "equity_index"),
    "^HSI":       ("HSI", "equity_index"),
}


class YahooMarketsCollector(Collector):
    name = "yahoo"
    category = "markets"

    def fetch(self, since: datetime | None = None) -> Iterable[dict]:
        # Default: pull last year of daily data to backfill. Incremental after.
        days = 400 if since is None else max(5, (datetime.utcnow() - since).days + 2)

        for symbol, (label, _cat) in _SYMBOLS.items():
            try:
                yield from self._fetch_symbol(symbol, label, days=days)
                time.sleep(0.2)  # gentle pacing
            except Exception as e:
                log.warning(f"  {symbol}: {e}")

    def _fetch_symbol(self, symbol: str, label: str, days: int) -> Iterable[dict]:
        params = {
            "interval": "1d",
            "range": f"{max(30, days)}d" if days <= 365 else "2y",
            "includePrePost": "false",
            "events": "div,splits",
        }
        url = _CHART_URL + symbol + "?" + urlencode(params)
        req = Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 AURUM-MacroBrain",
        })
        with urlopen(req, timeout=15) as resp:
            data = _json.loads(resp.read())

        chart = (data.get("chart") or {}).get("result") or []
        if not chart:
            return

        payload = chart[0]
        timestamps = payload.get("timestamp") or []
        indicators = payload.get("indicators") or {}
        quote = (indicators.get("quote") or [{}])[0]
        closes = quote.get("close") or []

        prev_val = None
        for ts_unix, close in zip(timestamps, closes):
            if close is None:
                continue
            try:
                ts = datetime.utcfromtimestamp(int(ts_unix)).strftime("%Y-%m-%d")
                value = float(close)
            except (TypeError, ValueError):
                continue

            yield {
                "type": "macro_data",
                "ts": ts,
                "metric": label,
                "value": value,
                "prev": prev_val,
                "source": self.name,
            }
            prev_val = value


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-5s  %(message)s")
    from macro_brain.persistence.store import init_db, latest_macro
    init_db()
    r = YahooMarketsCollector().run()
    print(f"\nResult: {r}")
    print("\nLatest prices per metric:")
    for sym, (label, _) in _SYMBOLS.items():
        latest = latest_macro(label, n=1)
        if latest:
            v = latest[0]["value"]
            t = latest[0]["ts"]
            print(f"  {label:<14} {t[:10]}  {v:>14,.4f}")
