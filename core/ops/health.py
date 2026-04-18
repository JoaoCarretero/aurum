"""Runtime health ledger for degraded infrastructure subsystems."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


@dataclass
class HealthLedger:
    counters: Counter = field(default_factory=Counter)

    def record(self, key: str, n: int = 1) -> None:
        self.counters[key] += n

    def snapshot(self) -> dict[str, int]:
        return dict(self.counters)

    def diagnostic_payload(self) -> dict[str, object]:
        return {
            "schema_version": "runtime_health.v1",
            "counters": self.snapshot(),
        }


runtime_health = HealthLedger()
