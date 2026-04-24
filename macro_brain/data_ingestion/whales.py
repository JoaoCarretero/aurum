"""Whales collector — insider trading + institutional flows.

Fontes free:
  SEC EDGAR Form 4 (insider transactions real-time RSS)
  SEC EDGAR Form 13F (quarterly institutional holdings)

Sem key required.

Events emitted:
  source=sec:form4  category=insider  — insider buy/sell/option
  source=sec:13f    category=institutional — 13F amendments

Phase 2 additions:
  - Congress stock trading (Senate + House disclosures)
  - ETF flow aggregation (SPDR/iShares/Vanguard holdings deltas)
"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Iterable
from urllib.request import Request, urlopen

from macro_brain.data_ingestion.base import Collector

log = logging.getLogger("macro_brain.ingest.whales")


_SEC_FORM4_RSS = (
    "https://www.sec.gov/cgi-bin/browse-edgar"
    "?action=getcurrent&type=4&company=&dateb=&owner=include"
    "&count=40&output=atom"
)
_SEC_FORM4_RECENT = (
    "https://www.sec.gov/cgi-bin/browse-edgar"
    "?action=getcurrent&type=4&company=&dateb=&owner=include"
    "&count=40"
)

# SEC requires User-Agent identifying you
_UA = "AURUM-MacroBrain research contact@aurum.finance"


def _parse_ts(raw: str) -> str:
    if not raw: return datetime.utcnow().isoformat()
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


class SECInsiderCollector(Collector):
    """Pull recent SEC Form 4 filings — insider trading real-time."""

    name = "sec:form4"
    category = "insider"

    def fetch(self, since: datetime | None = None) -> Iterable[dict]:
        try:
            req = Request(_SEC_FORM4_RSS, headers={"User-Agent": _UA})
            with urlopen(req, timeout=20) as resp:
                payload = resp.read()
        except Exception as e:
            log.warning(f"form4 fetch failed: {e}")
            return

        try:
            root = ET.fromstring(payload)
        except ET.ParseError as e:
            log.warning(f"form4 XML parse failed: {e}")
            return

        # Atom namespace
        ns = {"a": "http://www.w3.org/2005/Atom"}
        entries = root.findall("a:entry", ns)

        for entry in entries[:40]:
            title = (entry.findtext("a:title", default="", namespaces=ns) or "").strip()
            updated = entry.findtext("a:updated", default="", namespaces=ns) or ""
            summary = entry.findtext("a:summary", default="", namespaces=ns) or ""
            link_el = entry.find("a:link", ns)
            link = link_el.get("href") if link_el is not None else ""

            if not title:
                continue

            # Title typical: "4 - COMPANY NAME (0001234567) (Filer)"
            # Extract company name and CIK
            m = re.match(r"(\d+)\s*-\s*([^(]+)\s*\(", title)
            company = m.group(2).strip() if m else title[:60]

            # Sentiment: can't infer without fetching the actual filing.
            # Impact: high if large company (length heuristic).
            impact = min(1.0, len(company) / 50 + 0.5)

            ts = _parse_ts(updated)
            yield {
                "type": "event",
                "ts": ts,
                "source": self.name,
                "category": "insider",
                "headline": f"INSIDER: {company[:80]}",
                "body": summary[:400],
                "entities": [company],
                "sentiment": 0.0,
                "impact": round(impact, 3),
                "raw": {"link": link, "title": title},
            }


class SEC13FCollector(Collector):
    """Pull recent 13F filings — quarterly institutional holdings."""

    name = "sec:13f"
    category = "institutional"

    def fetch(self, since: datetime | None = None) -> Iterable[dict]:
        url = (
            "https://www.sec.gov/cgi-bin/browse-edgar"
            "?action=getcurrent&type=13F-HR&company=&dateb=&owner=include"
            "&count=40&output=atom"
        )
        try:
            req = Request(url, headers={"User-Agent": _UA})
            with urlopen(req, timeout=20) as resp:
                payload = resp.read()
        except Exception as e:
            log.warning(f"13f fetch failed: {e}")
            return
        try:
            root = ET.fromstring(payload)
        except ET.ParseError as e:
            log.warning(f"13f XML parse: {e}")
            return

        ns = {"a": "http://www.w3.org/2005/Atom"}
        for entry in root.findall("a:entry", ns)[:20]:
            title = (entry.findtext("a:title", default="", namespaces=ns) or "").strip()
            updated = entry.findtext("a:updated", default="", namespaces=ns) or ""
            link_el = entry.find("a:link", ns)
            link = link_el.get("href") if link_el is not None else ""

            # Title like "13F-HR - BLACKROCK INSTITUTIONAL TRUST COMPANY (...)"
            m = re.match(r"13F[^-]*-\s*(.*?)\s*\(", title)
            firm = m.group(1).strip() if m else title[:60]

            yield {
                "type": "event",
                "ts": _parse_ts(updated),
                "source": self.name,
                "category": "institutional",
                "headline": f"13F FILING: {firm[:80]}",
                "body": f"Quarterly institutional holdings filing",
                "entities": [firm],
                "sentiment": 0.0,
                "impact": 0.6,
                "raw": {"link": link, "title": title},
            }


class WhalesCollector(Collector):
    """Umbrella collector: insider + institutional in one call."""

    name = "whales"
    category = "institutional"

    def fetch(self, since: datetime | None = None) -> Iterable[dict]:
        yield from SECInsiderCollector().fetch(since)
        yield from SEC13FCollector().fetch(since)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s  %(levelname)-5s  %(message)s")
    from macro_brain.persistence.store import init_db, recent_events
    init_db()

    r = WhalesCollector().run()
    print(f"\nWhales result: {r}")

    print("\nLast 5 insider events:")
    for e in recent_events(category="insider", limit=5):
        print(f"  {e['ts'][:16]}  {e['source'][:15]:<15}  {e['headline'][:80]}")
    print("\nLast 5 institutional events:")
    for e in recent_events(category="institutional", limit=5):
        print(f"  {e['ts'][:16]}  {e['source'][:15]:<15}  {e['headline'][:80]}")
