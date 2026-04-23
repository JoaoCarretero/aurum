"""News collectors — NewsAPI (freemium) + GDELT (free).

NewsAPI requires NEWSAPI_KEY env var. Free tier: 500 req/day.
GDELT 2.0 Doc API requires no key. 15-min global coverage.

Both emit `events` rows with category derived from query keywords.
"""
from __future__ import annotations

import json as _json
import logging
from datetime import datetime, timedelta
from typing import Iterable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config.macro_params import NEWSAPI_KEY
from macro_brain.data_ingestion.base import Collector

log = logging.getLogger("macro_brain.ingest.news")


# Categorias alvo (macro-relevant) com keywords pra GDELT theme filter
_CATEGORIES = {
    "monetary":    ["Fed", "ECB", "interest rates", "monetary policy", "FOMC"],
    "macro":       ["CPI", "inflation", "GDP", "unemployment", "recession"],
    "geopolitics": ["war", "sanctions", "election", "NATO", "China", "Russia"],
    "commodities": ["oil price", "gold", "OPEC", "commodity"],
    "crypto":      ["bitcoin", "ethereum", "crypto regulation", "SEC"],
}


def _simple_sentiment(text: str) -> float:
    """Crude sentiment proxy: -1 to +1 based on keyword scoring.

    MVP only. Phase 2 substitui por BERT ou GPT API.
    """
    pos_words = {"surge", "soar", "rally", "gains", "beat", "strong", "positive",
                 "growth", "bullish", "record", "rise", "boost"}
    neg_words = {"plunge", "crash", "slump", "fall", "miss", "weak", "negative",
                 "recession", "bearish", "drop", "cut", "fear", "concern", "war",
                 "crisis", "sanction"}
    t = text.lower()
    pos = sum(1 for w in pos_words if w in t)
    neg = sum(1 for w in neg_words if w in t)
    total = pos + neg
    if total == 0:
        return 0.0
    return (pos - neg) / total


class NewsAPICollector(Collector):
    """NewsAPI.org — curated headlines. 500 req/day free tier."""

    name = "newsapi"
    category = "news"

    def fetch(self, since: datetime | None = None) -> Iterable[dict]:
        if not NEWSAPI_KEY:
            log.warning("NEWSAPI_KEY not set — skipping. Get free at newsapi.org")
            return

        since_str = (since or (datetime.utcnow() - timedelta(days=1))).strftime("%Y-%m-%d")

        for cat, keywords in _CATEGORIES.items():
            query = " OR ".join(f'"{k}"' for k in keywords[:3])  # budget: 3 keywords/cat
            params = {
                "q": query,
                "from": since_str,
                "sortBy": "publishedAt",
                "language": "en",
                "pageSize": 20,
                "apiKey": NEWSAPI_KEY,
            }
            url = f"https://newsapi.org/v2/everything?{urlencode(params)}"
            try:
                with urlopen(url, timeout=15) as resp:
                    data = _json.loads(resp.read())
            except Exception as e:
                log.warning(f"  {cat} fetch failed: {e}")
                continue

            for art in data.get("articles", []):
                headline = art.get("title") or ""
                body = art.get("description") or ""
                combined = f"{headline}. {body}"
                yield {
                    "type": "event",
                    "ts": art.get("publishedAt", "").replace("Z", ""),
                    "source": f"newsapi:{(art.get('source') or {}).get('name','?')}",
                    "category": cat,
                    "headline": headline,
                    "body": body,
                    "entities": [],
                    "sentiment": _simple_sentiment(combined),
                    "impact": min(1.0, len(combined) / 500),  # proxy: length
                    "raw": art,
                }


class GDELTCollector(Collector):
    """GDELT 2.0 Doc API — global news, 15min latency, no key required.

    Uses ArtList mode which returns JSON.
    """

    name = "gdelt"
    category = "news"

    def fetch(self, since: datetime | None = None) -> Iterable[dict]:
        # GDELT date format: YYYYMMDDHHMMSS (UTC)
        start = (since or (datetime.utcnow() - timedelta(hours=24))).strftime("%Y%m%d%H%M%S")
        end = datetime.utcnow().strftime("%Y%m%d%H%M%S")

        for cat, keywords in _CATEGORIES.items():
            # Join keywords with OR for broader match
            query = " OR ".join(keywords[:3])
            params = {
                "query": query,
                "mode": "ArtList",
                "format": "json",
                "maxrecords": 25,
                "startdatetime": start,
                "enddatetime": end,
            }
            url = f"https://api.gdeltproject.org/api/v2/doc/doc?{urlencode(params)}"
            try:
                req = Request(url, headers={"User-Agent": "AURUM-MacroBrain/0.1"})
                with urlopen(req, timeout=20) as resp:
                    payload = resp.read().decode("utf-8", errors="replace")
                # GDELT sometimes returns non-JSON; be defensive
                if not payload.strip().startswith("{"):
                    log.warning(f"  {cat}: GDELT returned non-JSON")
                    continue
                data = _json.loads(payload)
            except Exception as e:
                log.warning(f"  {cat} fetch failed: {e}")
                continue

            for art in data.get("articles", []):
                title = art.get("title") or ""
                seendate = art.get("seendate") or ""  # YYYYMMDDHHMMSSZ
                try:
                    ts = datetime.strptime(seendate[:14], "%Y%m%d%H%M%S").isoformat()
                except (ValueError, TypeError):
                    ts = datetime.utcnow().isoformat()

                yield {
                    "type": "event",
                    "ts": ts,
                    "source": f"gdelt:{art.get('domain','?')}",
                    "category": cat,
                    "headline": title,
                    "body": "",
                    "entities": [],
                    "sentiment": _simple_sentiment(title),
                    "impact": min(1.0, float(art.get("socialimage", "")) != "" and 0.7 or 0.3),
                    "raw": art,
                }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-5s  %(message)s")
    from macro_brain.persistence.store import init_db, recent_events

    init_db()

    print("\n--- NewsAPI ---")
    r1 = NewsAPICollector().run()
    print(r1)

    print("\n--- GDELT ---")
    r2 = GDELTCollector().run()
    print(r2)

    print("\nLast 5 news events:")
    for e in recent_events(limit=5):
        src = e["source"][:20]
        cat = e["category"]
        sent = e["sentiment"]
        print(f"  [{cat:<12}] {src:<22} {sent:+.2f}  {e['headline'][:60]}")
