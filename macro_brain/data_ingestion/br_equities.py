"""Brazilian equities collector — Ibovespa + main BR stocks + BRL.

Yahoo Finance com sufixo .SA para B3 (Bolsa). Free, no key.

Cobertura:
  Indices:    IBOV (^BVSP), Small Caps (SMLL11.SA), IFIX (real estate)
  BRL:        USD/BRL, EUR/BRL
  Top stocks: PETR4, VALE3, ITUB4, BBDC4, BBAS3, ABEV3, B3SA3, MGLU3,
              WEGE3, RENT3, PRIO3, BRAP4, SUZB3, JBSS3, KLBN11, ELET3
  ADRs (US-listed Brazilian): VALE, ITUB, PBR, BBD
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

log = logging.getLogger("macro_brain.ingest.br")

_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/"


_SYMBOLS = {
    # Indices
    "^BVSP":        ("IBOVESPA", "br_equity"),
    "SMLL11.SA":    ("BR_SMALL_CAPS", "br_equity"),
    "IFIX.SA":      ("BR_REAL_ESTATE", "br_equity"),
    # BRL forex
    "BRL=X":        ("USD_BRL", "br_forex"),
    "EURBRL=X":     ("EUR_BRL", "br_forex"),
    # Top 16 B3 stocks by float
    "PETR4.SA":     ("PETR4_PETROBRAS", "br_equity"),
    "VALE3.SA":     ("VALE3_VALE", "br_equity"),
    "ITUB4.SA":     ("ITUB4_ITAU", "br_equity"),
    "BBDC4.SA":     ("BBDC4_BRADESCO", "br_equity"),
    "BBAS3.SA":     ("BBAS3_BB", "br_equity"),
    "ABEV3.SA":     ("ABEV3_AMBEV", "br_equity"),
    "B3SA3.SA":     ("B3SA3_B3", "br_equity"),
    "WEGE3.SA":     ("WEGE3_WEG", "br_equity"),
    "RENT3.SA":     ("RENT3_LOCALIZA", "br_equity"),
    "PRIO3.SA":     ("PRIO3_PRIO", "br_equity"),
    "BRAP4.SA":     ("BRAP4_BRADESPAR", "br_equity"),
    "SUZB3.SA":     ("SUZB3_SUZANO", "br_equity"),
    "JBSS3.SA":     ("JBSS3_JBS", "br_equity"),
    "KLBN11.SA":    ("KLBN11_KLABIN", "br_equity"),
    "ELET3.SA":     ("ELET3_ELETROBRAS", "br_equity"),
    "MGLU3.SA":     ("MGLU3_MAGALU", "br_equity"),
    # US-listed BR ADRs
    "VALE":         ("VALE_ADR", "br_equity"),
    "ITUB":         ("ITUB_ADR", "br_equity"),
    "PBR":          ("PBR_ADR", "br_equity"),
    "BBD":          ("BBD_ADR", "br_equity"),
}


class BREquitiesCollector(Collector):
    name = "yahoo_br"
    category = "br_equity"

    def fetch(self, since: datetime | None = None) -> Iterable[dict]:
        days = 400 if since is None else max(5, (datetime.utcnow() - since).days + 2)
        for symbol, (label, _cat) in _SYMBOLS.items():
            try:
                yield from self._fetch_symbol(symbol, label, days=days)
                time.sleep(0.15)
            except Exception as e:
                log.warning(f"  {symbol}: {e}")

    def _fetch_symbol(self, symbol: str, label: str, days: int) -> Iterable[dict]:
        params = {
            "interval": "1d",
            "range": f"{max(30, days)}d" if days <= 365 else "2y",
            "includePrePost": "false",
        }
        url = _CHART + symbol + "?" + urlencode(params)
        req = Request(url, headers={
            "User-Agent": "Mozilla/5.0 AURUM-MacroBrain",
        })
        with urlopen(req, timeout=15) as resp:
            data = _json.loads(resp.read())
        chart = (data.get("chart") or {}).get("result") or []
        if not chart: return
        payload = chart[0]
        timestamps = payload.get("timestamp") or []
        quote = (payload.get("indicators", {}).get("quote") or [{}])[0]
        closes = quote.get("close") or []
        prev = None
        for ts_unix, close in zip(timestamps, closes):
            if close is None: continue
            try:
                ts = datetime.utcfromtimestamp(int(ts_unix)).strftime("%Y-%m-%d")
                value = float(close)
            except (TypeError, ValueError):
                continue
            yield {"type": "macro_data", "ts": ts, "metric": label,
                   "value": value, "prev": prev, "source": self.name}
            prev = value


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from macro_brain.persistence.store import init_db, latest_macro
    init_db()
    r = BREquitiesCollector().run()
    print(f"\nResult: {r}")
    print("\nLatest BR:")
    for sym, (label, _) in _SYMBOLS.items():
        lat = latest_macro(label, n=1)
        if lat:
            print(f"  {label:<22} {lat[0]['ts']}  {lat[0]['value']:>12,.2f}")
