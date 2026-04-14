"""FRED collector — Fed / Treasury / macro time-series.

Pulls FRED series listed in config.macro_params.FRED_SERIES.
Requires FRED_API_KEY env var (free, ~1min signup at stlouisfed.org).

Docs: https://fred.stlouisfed.org/docs/api/fred/series_observations.html
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Iterable
from urllib.parse import urlencode
from urllib.request import urlopen

from config.macro_params import FRED_API_KEY, FRED_SERIES
from macro_brain.data_ingestion.base import Collector

log = logging.getLogger("macro_brain.ingest.fred")

_ENDPOINT = "https://api.stlouisfed.org/fred/series/observations"


class FREDCollector(Collector):
    name = "FRED"
    category = "monetary"  # covers macro + monetary via same source

    def fetch(self, since: datetime | None = None) -> Iterable[dict]:
        if not FRED_API_KEY:
            log.warning("FRED_API_KEY not set — skipping. Get free key at stlouisfed.org")
            return

        since_str = (since or (datetime.utcnow() - timedelta(days=30))).strftime("%Y-%m-%d")

        for fred_id, our_label in FRED_SERIES.items():
            try:
                yield from self._fetch_series(fred_id, our_label, since_str)
            except Exception as e:
                log.warning(f"  {fred_id} fetch failed: {e}")

    def _fetch_series(self, fred_id: str, label: str, since: str) -> Iterable[dict]:
        import json as _json

        params = {
            "series_id": fred_id,
            "api_key": FRED_API_KEY,
            "file_type": "json",
            "observation_start": since,
            "sort_order": "asc",
        }
        url = f"{_ENDPOINT}?{urlencode(params)}"
        with urlopen(url, timeout=15) as resp:
            data = _json.loads(resp.read())

        observations = data.get("observations", [])
        for i, obs in enumerate(observations):
            val_str = obs.get("value", ".")
            if val_str == "." or val_str == "":
                continue
            try:
                value = float(val_str)
            except (TypeError, ValueError):
                continue

            prev = None
            if i > 0:
                prev_str = observations[i - 1].get("value", ".")
                try:
                    prev = float(prev_str) if prev_str != "." else None
                except (TypeError, ValueError):
                    prev = None

            yield {
                "type": "macro_data",
                "ts": obs.get("date"),       # YYYY-MM-DD
                "metric": label,
                "value": value,
                "prev": prev,
                "source": self.name,
            }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-5s  %(message)s")
    from macro_brain.persistence.store import init_db, latest_macro
    init_db()

    collector = FREDCollector()
    result = collector.run(since=datetime.utcnow() - timedelta(days=365))
    print(f"\nFRED fetch result: {result}")

    # Sanity: latest point per metric
    print("\nLatest per metric:")
    for fred_id, label in FRED_SERIES.items():
        latest = latest_macro(label, n=1)
        if latest:
            r = latest[0]
            print(f"  {label:<20} {r['ts']}  {r['value']:>12.4f}")
        else:
            print(f"  {label:<20} (no data)")
