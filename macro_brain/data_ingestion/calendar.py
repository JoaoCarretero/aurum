"""Economic Calendar — próximos releases macroeconômicos.

Pull do FRED release calendar (free, API key opcional para rate).
Como MVP backup sem FRED: hardcoded schedule dos principais releases
recorrentes (CPI, FOMC, NFP, etc).

Phase 2: integrar TradingEconomics calendar (freemium), Investing.com,
ou webscraping de ForexFactory.
"""
from __future__ import annotations

import json as _json
import logging
from datetime import datetime, timedelta
from typing import Iterable
from urllib.parse import urlencode
from urllib.request import urlopen

from config.macro_params import FRED_API_KEY
from macro_brain.data_ingestion.base import Collector

log = logging.getLogger("macro_brain.ingest.calendar")


# Releases de alta importância + cadência típica
# (FRED release_id, nossa label, impact 0-1)
_FRED_RELEASES = [
    (13,   "FOMC_STATEMENT",      1.0),   # H.15 release cycle touches FOMC decisions
    (10,   "CPI",                 0.95),  # Consumer Price Index
    (50,   "NFP",                 0.95),  # Employment Situation (NFP)
    (82,   "PPI",                 0.7),
    (53,   "GDP",                 0.85),
    (46,   "RETAIL_SALES",        0.6),
    (49,   "INDUSTRIAL_PRODUCTION", 0.55),
    (45,   "PERSONAL_INCOME",     0.55),
    (151,  "UNIVERSITY_MICHIGAN_SENTIMENT", 0.5),
]


class EconomicCalendarCollector(Collector):
    """FRED release calendar. Next ~14 days of scheduled releases."""

    name = "fred_calendar"
    category = "calendar"

    def fetch(self, since: datetime | None = None) -> Iterable[dict]:
        if not FRED_API_KEY:
            log.info("FRED_API_KEY not set — emitting hardcoded fallback calendar")
            yield from self._fallback_calendar()
            return

        # Next 14 days
        start = datetime.utcnow().strftime("%Y-%m-%d")
        end = (datetime.utcnow() + timedelta(days=30)).strftime("%Y-%m-%d")

        for rel_id, label, impact in _FRED_RELEASES:
            params = {
                "release_id": rel_id,
                "api_key": FRED_API_KEY,
                "file_type": "json",
                "realtime_start": start,
                "realtime_end": end,
            }
            url = f"https://api.stlouisfed.org/fred/release/dates?{urlencode(params)}"
            try:
                with urlopen(url, timeout=15) as resp:
                    data = _json.loads(resp.read())
            except Exception as e:
                log.warning(f"  {label} fetch failed: {e}")
                continue

            for date_entry in data.get("release_dates", []):
                rdate = date_entry.get("date")
                if not rdate:
                    continue
                yield {
                    "type": "event",
                    "ts": f"{rdate}T14:30:00",  # default release time (EST approximation)
                    "source": f"fred:release_{rel_id}",
                    "category": "calendar",
                    "headline": f"UPCOMING: {label} release",
                    "body": "Scheduled economic release",
                    "entities": [label],
                    "sentiment": 0.0,  # calendar events are neutral until released
                    "impact": impact,
                    "raw": date_entry,
                }

    def _fallback_calendar(self) -> Iterable[dict]:
        """Hardcoded next releases (approximate dates, MVP fallback).

        Use when FRED key not available. Not as precise but shows signal.
        """
        today = datetime.utcnow()

        # Approximate next occurrences based on typical monthly cadence
        approximations = [
            ("CPI",                    10,  0.95),  # ~10th of month
            ("PPI",                    13,  0.70),  # ~2 days after CPI
            ("RETAIL_SALES",           15,  0.60),
            ("FOMC_STATEMENT",         None, 1.0),  # 8x/year, can't approximate
            ("INDUSTRIAL_PRODUCTION",  17,  0.55),
            ("NFP",                    None, 0.95),  # 1st Friday of month
            ("GDP",                    None, 0.85),  # ~last Thu of month (quarterly)
        ]

        for label, day_of_month, impact in approximations:
            if day_of_month is None:
                # Next Friday for NFP, etc
                if label == "NFP":
                    days_ahead = (4 - today.weekday()) % 7 + 7
                    release_date = today + timedelta(days=days_ahead)
                else:
                    continue  # skip quarterly/irregular ones in fallback
            else:
                # Next occurrence of this day_of_month
                target = today.replace(day=min(day_of_month, 28), hour=14, minute=30)
                if target < today:
                    if target.month == 12:
                        target = target.replace(year=target.year + 1, month=1)
                    else:
                        target = target.replace(month=target.month + 1)
                release_date = target

            yield {
                "type": "event",
                "ts": release_date.strftime("%Y-%m-%dT%H:%M:%S"),
                "source": "fallback:calendar",
                "category": "calendar",
                "headline": f"UPCOMING: {label} release (approximate)",
                "body": "Approximate date — verify via FRED calendar",
                "entities": [label],
                "sentiment": 0.0,
                "impact": impact,
                "raw": {"fallback": True, "day_of_month": day_of_month},
            }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from macro_brain.persistence.store import init_db, recent_events
    init_db()
    r = EconomicCalendarCollector().run()
    print(r)
    print("\nUpcoming releases:")
    for e in recent_events(category="calendar", limit=10):
        print(f"  {e['ts'][:16]}  impact={e['impact']:.2f}  {e['headline']}")
