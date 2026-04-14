"""RSS news collector — agrega feeds institucionais.

Sem API key. Pulls direto dos RSS públicos de:
  - Federal Reserve press releases
  - ECB press
  - US Treasury press
  - Bank of Japan (limitado)
  - CoinDesk (crypto news)
  - Cointelegraph (crypto policy)
  - MarketWatch top stories

Categoriza automaticamente por feed source + keyword matching.
Stdlib-only: xml.etree.ElementTree + urllib.
"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from macro_brain.data_ingestion.base import Collector

log = logging.getLogger("macro_brain.ingest.rss")


# Feed registry: (url, source_tag, default_category, priority_keywords)
_FEEDS = [
    ("https://www.federalreserve.gov/feeds/press_all.xml",
     "fed", "monetary",
     ["rate", "FOMC", "policy", "inflation", "employment"]),
    ("https://www.ecb.europa.eu/rss/press.html",
     "ecb", "monetary",
     ["rate", "policy", "inflation", "euro"]),
    ("https://home.treasury.gov/news/press-releases/feed",
     "treasury", "monetary",
     ["Treasury", "debt", "sanctions", "tariff"]),
    ("https://www.coindesk.com/arc/outboundfeeds/rss",
     "coindesk", "crypto",
     ["bitcoin", "ethereum", "SEC", "ETF", "regulation"]),
    ("https://cointelegraph.com/rss",
     "cointelegraph", "crypto",
     ["bitcoin", "regulation", "SEC", "CBDC"]),
    ("https://feeds.content.dowjones.io/public/rss/mw_topstories",
     "marketwatch", "macro",
     ["market", "fed", "recession", "inflation", "earnings"]),
    ("https://www.bis.org/rss/home.rss",
     "bis", "monetary",
     ["banking", "systemic", "risk"]),
]


_POS_WORDS = {"surge", "soar", "rally", "gains", "beat", "strong", "positive",
              "growth", "bullish", "record", "rise", "boost", "optimism"}
_NEG_WORDS = {"plunge", "crash", "slump", "fall", "miss", "weak", "negative",
              "recession", "bearish", "drop", "cut", "fear", "concern", "war",
              "crisis", "sanction", "warning", "decline", "slow", "risk"}


def _sentiment(text: str) -> float:
    t = text.lower()
    pos = sum(1 for w in _POS_WORDS if w in t)
    neg = sum(1 for w in _NEG_WORDS if w in t)
    if pos + neg == 0:
        return 0.0
    return (pos - neg) / (pos + neg)


def _impact(headline: str, body: str, priority_keywords: list[str]) -> float:
    """Score 0-1: hit em keyword prioritário + length."""
    combined = f"{headline} {body}".lower()
    hits = sum(1 for k in priority_keywords if k.lower() in combined)
    kw_boost = min(hits * 0.2, 0.6)
    length_boost = min(len(combined) / 1000, 0.4)
    return round(min(kw_boost + length_boost, 1.0), 3)


def _parse_ts(raw: str) -> str:
    """Best-effort RFC822 / ISO 8601 → ISO string."""
    if not raw:
        return datetime.utcnow().isoformat()
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(raw)
        return dt.replace(tzinfo=None).isoformat()
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(raw.replace("Z", "")).isoformat()
    except ValueError:
        return datetime.utcnow().isoformat()


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").strip()


class RSSCollector(Collector):
    name = "rss"
    category = "news"

    def fetch(self, since: datetime | None = None) -> Iterable[dict]:
        since = since or (datetime.utcnow() - timedelta(days=2))
        for url, source_tag, default_cat, keywords in _FEEDS:
            try:
                yield from self._fetch_feed(url, source_tag, default_cat, keywords, since)
            except (HTTPError, URLError, ET.ParseError, OSError) as e:
                log.warning(f"  {source_tag}: {e}")

    def _fetch_feed(
        self, url: str, source_tag: str, default_cat: str,
        keywords: list[str], since: datetime,
    ) -> Iterable[dict]:
        req = Request(url, headers={"User-Agent": "AURUM-MacroBrain/0.1"})
        with urlopen(req, timeout=15) as resp:
            payload = resp.read()

        root = ET.fromstring(payload)

        # RSS 2.0: channel → item[], Atom: feed → entry[]
        items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")

        for item in items:
            def _find(tag: str) -> str:
                el = item.find(tag)
                if el is not None and el.text:
                    return el.text
                # Atom namespace fallback
                el = item.find(f"{{http://www.w3.org/2005/Atom}}{tag}")
                if el is not None and el.text:
                    return el.text
                return ""

            title = _strip_html(_find("title"))
            desc = _strip_html(_find("description") or _find("summary"))
            link = _find("link") or ""
            pub = _find("pubDate") or _find("published") or _find("updated")

            ts = _parse_ts(pub)
            try:
                dt = datetime.fromisoformat(ts[:19])
            except ValueError:
                dt = datetime.utcnow()
            if dt < since:
                continue

            combined = f"{title}. {desc}"
            yield {
                "type": "event",
                "ts": ts,
                "source": f"rss:{source_tag}",
                "category": default_cat,
                "headline": title[:300],
                "body": desc[:500],
                "entities": [],
                "sentiment": round(_sentiment(combined), 3),
                "impact": _impact(title, desc, keywords),
                "raw": {"link": link, "feed": source_tag},
            }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-5s  %(message)s")
    from macro_brain.persistence.store import init_db, recent_events
    init_db()
    r = RSSCollector().run(since=datetime.utcnow() - timedelta(hours=48))
    print(f"\nResult: {r}")
    print("\nLast 8 events:")
    for e in recent_events(limit=8):
        if not e["source"].startswith("rss:"): continue
        print(f"  [{e['category']:<10}] {e['source'][:20]:<20} "
              f"sent={e['sentiment']:+.2f}  imp={e['impact']:.2f}  "
              f"{e['headline'][:70]}")
