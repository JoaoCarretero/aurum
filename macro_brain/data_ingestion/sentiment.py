"""Sentiment collectors — Fear & Greed Index etc.

Alternative.me Fear & Greed Index (crypto) é free sem API key.
Update frequency: daily.

Docs: https://alternative.me/crypto/fear-and-greed-index/
"""
from __future__ import annotations

import json as _json
import logging
from datetime import datetime, timedelta
from typing import Iterable
from urllib.request import urlopen

from macro_brain.data_ingestion.base import Collector

log = logging.getLogger("macro_brain.ingest.sentiment")

_FNG_ENDPOINT = "https://api.alternative.me/fng/"


class FearGreedCollector(Collector):
    """Crypto Fear & Greed Index daily. Classifies market sentiment 0-100."""

    name = "alternative.me"
    category = "sentiment"

    def fetch(self, since: datetime | None = None) -> Iterable[dict]:
        # Fear & Greed is daily; fetch last 365d to backfill on first run
        days = 365 if since is None else max(
            1, (datetime.utcnow() - since).days + 1
        )
        url = f"{_FNG_ENDPOINT}?limit={min(days, 2000)}&format=json"
        try:
            with urlopen(url, timeout=15) as resp:
                data = _json.loads(resp.read())
        except Exception as e:
            log.warning(f"Fear&Greed fetch failed: {e}")
            return

        for entry in data.get("data", []):
            try:
                # timestamp is unix seconds, as string
                ts_unix = int(entry["timestamp"])
                ts = datetime.utcfromtimestamp(ts_unix).strftime("%Y-%m-%d")
                value = float(entry["value"])  # 0-100
                # Normalize to -1..+1 for sentiment scale (0=-1 extreme fear, 100=+1 extreme greed)
                normalized = (value - 50) / 50.0
                classification = entry.get("value_classification", "?")
            except (KeyError, ValueError, TypeError) as e:
                log.warning(f"  parse error: {e} · {entry}")
                continue

            # Persist as macro_data (numeric series) — FNG raw 0-100
            yield {
                "type": "macro_data",
                "ts": ts,
                "metric": "CRYPTO_FEAR_GREED",
                "value": value,
                "source": self.name,
            }
            # Also as event (qualitative sentiment snapshot)
            yield {
                "type": "event",
                "ts": ts + "T00:00:00",
                "source": self.name,
                "category": "sentiment",
                "headline": f"Crypto Fear & Greed: {value:.0f} ({classification})",
                "sentiment": normalized,
                "impact": abs(normalized),  # extreme readings have higher impact
                "raw": entry,
            }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-5s  %(message)s")
    from macro_brain.persistence.store import init_db, latest_macro, recent_events

    init_db()
    collector = FearGreedCollector()
    result = collector.run(since=datetime.utcnow() - timedelta(days=30))
    print(f"\nFear&Greed result: {result}")

    latest = latest_macro("CRYPTO_FEAR_GREED", n=3)
    print("\nLatest 3 readings:")
    for r in latest:
        print(f"  {r['ts']}  {r['value']:>5.1f}")

    events = recent_events(category="sentiment", source="alternative.me", limit=3)
    print(f"\nLast 3 events: {len(events)}")
    for e in events:
        print(f"  {e['ts'][:10]}  sentiment={e['sentiment']:+.2f}  {e['headline']}")
