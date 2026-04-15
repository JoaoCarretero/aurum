"""BotWatcher ABC — on-chain/surgical watchers for macro brain.

Contract:
  - Bots OBSERVE. They emit events into macro_brain.persistence.store.
  - They never place orders. They are scouts, not executors.
  - Each bot publishes a BotDescriptor the cockpit can render.

Status lifecycle:
  planned     → stub exists, no collector wired
  scaffolded  → structure + describe() live, fetch() returns nothing
  live        → emitting real events
  degraded    → partial failure, last error captured
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
import logging
from typing import Iterable, Literal

log = logging.getLogger("macro_brain.bots")

BotStatus = Literal["planned", "scaffolded", "live", "degraded"]


@dataclass
class BotDescriptor:
    """Cockpit-facing metadata. Pure data, safe to render."""
    slug: str
    label: str
    network: str              # e.g. "SOL", "HYPE", "ETH"
    status: BotStatus
    tagline: str              # one-line description for slot render
    color: str                # hex accent for the cockpit slot
    # runtime snapshot (populated by describe() subclasses when live)
    last_run_ts: str | None = None
    last_signal_ts: str | None = None
    signals_24h: int = 0
    notes: str = ""
    extra: dict = field(default_factory=dict)


class BotWatcher(ABC):
    """Base watcher. Subclasses override fetch() and metadata fields."""

    slug: str = ""
    label: str = ""
    network: str = ""
    tagline: str = ""
    color: str = "#9945FF"
    status: BotStatus = "planned"

    @abstractmethod
    def fetch(self, since: datetime | None = None) -> Iterable[dict]:
        """Yield normalized event dicts (same contract as Collector.fetch)."""
        ...

    def describe(self) -> BotDescriptor:
        return BotDescriptor(
            slug=self.slug, label=self.label, network=self.network,
            status=self.status, tagline=self.tagline, color=self.color,
        )

    def run(self, since: datetime | None = None) -> dict:
        """Emit yielded events into the macro store. Mirrors Collector.run()."""
        from macro_brain.persistence.store import insert_event

        inserted = errors = 0
        for rec in self.fetch(since):
            try:
                rec.pop("type", None)
                insert_event(**rec)
                inserted += 1
            except Exception as e:
                log.warning(f"{self.slug}: insert failed: {e}")
                errors += 1
        log.info(f"{self.slug}: emitted={inserted} errors={errors}")
        return {"inserted": inserted, "errors": errors}
