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


# Socrata endpoints:
#   Legacy futures (commercial vs noncomm):   6dca-aqww
#   Disaggregated commodities (Producer/Merchant/Swap Dealer/Managed Money/Other): 72hh-3qpy
#   TFF financial futures (Dealer/Asset Manager/Leveraged/Other):                   gpe5-46if
#
# Legacy used for base NET_LONGS. Disaggregated + TFF capture "big banks"
# (swap dealers / dealer intermediaries).
_ENDPOINT_LEGACY = "https://publicreporting.cftc.gov/resource/6dca-aqww.json"
_ENDPOINT_DISAG  = "https://publicreporting.cftc.gov/resource/72hh-3qpy.json"
_ENDPOINT_TFF    = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"

_ENDPOINT = _ENDPOINT_LEGACY  # backwards-compat default


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
        # Fetch both Legacy + Disaggregated + TFF endpoints
        since_date = since or (datetime.utcnow() - timedelta(weeks=12))
        # Legacy (base data, 12 markets)
        yield from self._fetch_endpoint(_ENDPOINT_LEGACY, since_date,
                                         field_map="legacy")
        # Disaggregated (Producer/Swap Dealer/Managed Money/Other for commodities)
        yield from self._fetch_endpoint(_ENDPOINT_DISAG, since_date,
                                         field_map="disag")
        # TFF financial futures (Dealer = big banks, Asset Manager, Leveraged)
        yield from self._fetch_endpoint(_ENDPOINT_TFF, since_date,
                                         field_map="tff")

    def _fetch_endpoint(self, endpoint: str, since_date: datetime,
                         field_map: str) -> Iterable[dict]:
        where = f"report_date_as_yyyy_mm_dd >= '{since_date.strftime('%Y-%m-%d')}'"
        params = {
            "$where": where,
            "$limit": 1000,
            "$order": "report_date_as_yyyy_mm_dd DESC",
        }
        url = f"{endpoint}?{urlencode(params)}"
        try:
            req = Request(url, headers={"User-Agent": "AURUM-MacroBrain/0.1"})
            with urlopen(req, timeout=20) as resp:
                data = _json.loads(resp.read())
        except Exception as e:
            log.warning(f"{field_map} fetch failed: {e}")
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

            if field_map == "legacy":
                nc_long = _to_float(row.get("noncomm_positions_long_all"))
                nc_short = _to_float(row.get("noncomm_positions_short_all"))
                comm_long = _to_float(row.get("comm_positions_long_all"))
                comm_short = _to_float(row.get("comm_positions_short_all"))
                swap_long = swap_short = None
                mm_long = mm_short = None
                other_long = other_short = None
            elif field_map == "disag":
                nc_long = nc_short = None
                comm_long = comm_short = None
                swap_long = _to_float(row.get("swap_positions_long_all"))
                swap_short = _to_float(row.get("swap__positions_short_all")
                                       or row.get("swap_positions_short_all"))
                mm_long = _to_float(row.get("m_money_positions_long_all"))
                mm_short = _to_float(row.get("m_money_positions_short_all"))
                other_long = _to_float(row.get("other_rept_positions_long"))
                other_short = _to_float(row.get("other_rept_positions_short"))
            elif field_map == "tff":
                # TFF: Dealer = big banks, Asset Manager, Leveraged Funds
                nc_long = nc_short = None
                comm_long = comm_short = None
                swap_long = _to_float(row.get("dealer_positions_long_all"))
                swap_short = _to_float(row.get("dealer_positions_short_all"))
                mm_long = _to_float(row.get("lev_money_positions_long"))
                mm_short = _to_float(row.get("lev_money_positions_short"))
                # Asset manager as "other" here
                other_long = _to_float(row.get("asset_mgr_positions_long"))
                other_short = _to_float(row.get("asset_mgr_positions_short"))
            else:
                continue
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

            # Swap Dealers = big banks positioning (JPM/GS/etc)
            if swap_long is not None and swap_short is not None:
                swap_net = swap_long - swap_short
                yield {"type": "macro_data", "ts": ts, "metric": f"{label}_SWAP_NET",
                       "value": swap_net, "source": self.name}
                yield {"type": "macro_data", "ts": ts, "metric": f"{label}_SWAP_LONG",
                       "value": swap_long, "source": self.name}
                yield {"type": "macro_data", "ts": ts, "metric": f"{label}_SWAP_SHORT",
                       "value": swap_short, "source": self.name}

            # Managed Money = hedge funds
            if mm_long is not None and mm_short is not None:
                mm_net = mm_long - mm_short
                yield {"type": "macro_data", "ts": ts, "metric": f"{label}_MM_NET",
                       "value": mm_net, "source": self.name}

            # Other Reportables = prop trading firms, family offices
            if other_long is not None and other_short is not None:
                other_net = other_long - other_short
                yield {"type": "macro_data", "ts": ts, "metric": f"{label}_OTHER_NET",
                       "value": other_net, "source": self.name}

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
