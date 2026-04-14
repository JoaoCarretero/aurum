"""Collector ABC + common utilities.

All data source collectors implement this protocol. Returns canonical
dicts ready for insert_event() / insert_macro().
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
import logging
from typing import Iterable

log = logging.getLogger("macro_brain.ingest")


class Collector(ABC):
    """Base interface. Concrete collectors override fetch()."""

    name: str = ""
    category: str = ""  # news|monetary|macro|commodities|sentiment

    @abstractmethod
    def fetch(self, since: datetime | None = None) -> Iterable[dict]:
        """Pull new records since `since` (None = full refresh window).

        Yields normalized dicts ready for persistence. Each dict must include:
          - type: "event" or "macro_data"
          - ts: ISO timestamp
          - remaining fields per type-specific schema
        """
        ...

    def run(self, since: datetime | None = None) -> dict:
        """Fetch + persist. Returns {inserted, skipped, errors}."""
        from macro_brain.persistence.store import insert_event, insert_macro

        inserted = skipped = errors = 0
        for rec in self.fetch(since):
            try:
                kind = rec.pop("type", "event")
                if kind == "macro_data":
                    result = insert_macro(**rec)
                    if result is None:
                        skipped += 1
                    else:
                        inserted += 1
                elif kind == "event":
                    insert_event(**rec)
                    inserted += 1
                else:
                    log.warning(f"{self.name}: unknown record type {kind!r}")
                    skipped += 1
            except Exception as e:
                log.warning(f"{self.name}: insert failed: {e}")
                errors += 1

        log.info(f"{self.name}: ingested={inserted} skipped={skipped} errors={errors}")
        return {"inserted": inserted, "skipped": skipped, "errors": errors}
