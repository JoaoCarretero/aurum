"""Contract tests for core.health — runtime health ledger.

Tiny module: Counter-backed ledger with record/snapshot/diagnostic_payload
+ one module-level singleton. Tests lock down the wire format
(schema_version) and snapshot isolation so a caller can't corrupt the
live counters via the returned dict.
"""
from __future__ import annotations

from collections import Counter

from core.health import HealthLedger, runtime_health


class TestRecord:
    def test_fresh_ledger_is_empty(self):
        led = HealthLedger()
        assert led.snapshot() == {}

    def test_default_increment_by_one(self):
        led = HealthLedger()
        led.record("fetch.timeout")
        assert led.counters["fetch.timeout"] == 1

    def test_explicit_n(self):
        led = HealthLedger()
        led.record("db.retry", n=5)
        assert led.counters["db.retry"] == 5

    def test_multiple_records_accumulate(self):
        led = HealthLedger()
        led.record("x"); led.record("x"); led.record("x", n=3)
        assert led.counters["x"] == 5


class TestSnapshot:
    def test_snapshot_returns_dict(self):
        led = HealthLedger()
        led.record("a")
        snap = led.snapshot()
        assert isinstance(snap, dict) and not isinstance(snap, Counter)

    def test_snapshot_is_decoupled_copy(self):
        # Mutating the returned dict must NOT change the live ledger —
        # that protects callers from accidentally clobbering counters
        # when they transform the snapshot for reporting.
        led = HealthLedger()
        led.record("a", n=3)
        snap = led.snapshot()
        snap["a"] = 999
        snap["new_key"] = 1
        assert led.counters["a"] == 3
        assert "new_key" not in led.counters


class TestDiagnosticPayload:
    def test_payload_has_schema_version(self):
        led = HealthLedger()
        p = led.diagnostic_payload()
        assert p["schema_version"] == "runtime_health.v1"

    def test_payload_counters_match_snapshot(self):
        led = HealthLedger()
        led.record("a"); led.record("b", n=2)
        p = led.diagnostic_payload()
        assert p["counters"] == {"a": 1, "b": 2}


class TestModuleSingleton:
    def test_runtime_health_is_ledger_instance(self):
        assert isinstance(runtime_health, HealthLedger)

    def test_runtime_health_is_singleton_across_imports(self):
        from core.health import runtime_health as rh2
        assert rh2 is runtime_health
