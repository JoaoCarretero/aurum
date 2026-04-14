"""CFTC Commitments of Traders (COT) collector.

Dados de positioning institucional (non-commercial, commercial, non-reportable)
por contrato futuro. Free via Socrata API (publicreporting.cftc.gov).

Weekly release toda sexta-feira com dados da terça anterior. Markets cobertos:
  Currencies: DXY, EUR, JPY, GBP, CAD, AUD
  Commodities: Gold, Silver, WTI, Nat Gas, Copper
  Indices: E-mini S&P 500, Nasdaq, Russell
  Rates: Treasury futures
  Crypto: Bitcoin (CME), Ether (CME)

Cada row emite métricas derivadas:
  <MARKET>_NET_LONGS       non-commercial net position (long - short)
  <MARKET>_COMM_NET        commercial net position
  <MARKET>_OI              total open interest
  <MARKET>_NC_LONG_PCT     % of OI non-commercial long
  <MARKET>_NC_SHORT_PCT    % of OI non-commercial short
"""
from __future__ import annotations

import json as _json
import logging
from datetime import datetime, timedelta
from typing import Iterable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from macro_brain.data_ingestion.base import Collector

log = logging.getLogger("macro_brain.ingest.cftc")


# Socrata endpoint p/ Disaggregated Futures Only (mais granular que Legacy)
_ENDPOINT = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"


# CFTC market name substrings → our label (grep match em "market_and_exchange_names")
_MARKET_MAP = [
    ("USD INDEX",                "DXY"),
    ("EURO FX",                  "EUR_FX"),
    ("JAPANESE YEN",             "JPY_FX"),
    ("BRITISH POUND",            "GBP_FX"),
    ("CANADIAN DOLLAR",          "CAD_FX"),
    ("AUSTRALIAN DOLLAR",        "AUD_FX"),
    ("GOLD",                     "GOLD"),
    ("SILVER",                   "SILVER"),
    ("COPPER",                   "COPPER"),
    ("WTI-PHYSICAL",             "WTI"),
    ("CRUDE OIL, LIGHT SWEET",   "CRUDE"),
    ("NATURAL GAS",              "NAT_GAS"),
    ("BITCOIN",                  "BTC_CME"),
    ("ETHER",                    "ETH_CME"),
    ("E-MINI S&P 500",           "SP500_ES"),
    ("E-MINI NASDAQ",            "NASDAQ_NQ"),
    ("E-MINI RUSSELL",           "RUSSELL_RTY"),
    ("UST 10-YEAR NOTE",         "UST_10Y"),
    ("UST 2-YEAR NOTE",          "UST_2Y"),
    ("UST BOND",                 "UST_30Y"),
    ("UST 30Y BOND",             "UST_30Y"),
]


def _match_market(name: str) -> str | None:
    up = (name or "").upper()
    for needle, label in _MARKET_MAP:
        if needle in up:
            return label
    return None


def _to_float(v) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class CFTCCollector(Collector):
    name = "cftc"
    category = "positioning"

    def fetch(self, since: datetime | None = None) -> Iterable[dict]:
        # Fetch last 12 weeks (ou desde `since`)
        since_date = since or (datetime.utcnow() - timedelta(weeks=12))
        where = f"report_date_as_yyyy_mm_dd >= '{since_date.strftime('%Y-%m-%d')}'"
        params = {
            "$where": where,
            "$limit": 1000,
            "$order": "report_date_as_yyyy_mm_dd DESC",
        }
        url = f"{_ENDPOINT}?{urlencode(params)}"
        try:
            req = Request(url, headers={"User-Agent": "AURUM-MacroBrain/0.1"})
            with urlopen(req, timeout=20) as resp:
                data = _json.loads(resp.read())
        except Exception as e:
            log.warning(f"fetch failed: {e}")
            return

        for row in data:
            name = row.get("market_and_exchange_names") or row.get("market_and_exchange")
            label = _match_market(name or "")
            if not label:
                continue

            report_date = row.get("report_date_as_yyyy_mm_dd") or row.get("report_date")
            if not report_date:
                continue
            ts = report_date[:10]

            # Non-commercial positions (speculators)
            nc_long = _to_float(row.get("noncomm_positions_long_all"))
            nc_short = _to_float(row.get("noncomm_positions_short_all"))
            # Commercial (hedgers / producers)
            comm_long = _to_float(row.get("comm_positions_long_all"))
            comm_short = _to_float(row.get("comm_positions_short_all"))
            # Open interest
            oi = _to_float(row.get("open_interest_all"))

            if nc_long is not None and nc_short is not None:
                net_nc = nc_long - nc_short
                yield {"type": "macro_data", "ts": ts, "metric": f"{label}_NET_LONGS",
                       "value": net_nc, "source": self.name}
                yield {"type": "macro_data", "ts": ts, "metric": f"{label}_NC_LONG",
                       "value": nc_long, "source": self.name}
                yield {"type": "macro_data", "ts": ts, "metric": f"{label}_NC_SHORT",
                       "value": nc_short, "source": self.name}
                if oi and oi > 0:
                    yield {"type": "macro_data", "ts": ts,
                           "metric": f"{label}_NC_LONG_PCT",
                           "value": nc_long / oi * 100, "source": self.name}
                    yield {"type": "macro_data", "ts": ts,
                           "metric": f"{label}_NC_SHORT_PCT",
                           "value": nc_short / oi * 100, "source": self.name}

            if comm_long is not None and comm_short is not None:
                comm_net = comm_long - comm_short
                yield {"type": "macro_data", "ts": ts, "metric": f"{label}_COMM_NET",
                       "value": comm_net, "source": self.name}

            if oi is not None:
                yield {"type": "macro_data", "ts": ts, "metric": f"{label}_OI",
                       "value": oi, "source": self.name}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from macro_brain.persistence.store import init_db, latest_macro
    init_db()
    r = CFTCCollector().run()
    print(f"\nResult: {r}")
    print("\nLatest positioning:")
    for _, label in _MARKET_MAP[:8]:
        net = latest_macro(f"{label}_NET_LONGS", n=1)
        oi = latest_macro(f"{label}_OI", n=1)
        if net:
            n = net[0]
            o_val = oi[0]["value"] if oi else None
            oi_str = f"OI {int(o_val):,}" if o_val else ""
            print(f"  {label:<14} {n['ts']}  net={n['value']:>+12,.0f}  {oi_str}")
