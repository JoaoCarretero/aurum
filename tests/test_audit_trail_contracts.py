"""Contract tests for core.audit_trail — immutable order log.

Groups:
- OrderEvent defaults & shape
- write() schema + event validation
- Append-only file semantics (JSONL)
- iter_rows reader tolerance (empty/malformed lines)
- Hash chain: disabled, enabled (genesis + link), verify_chain detects
  tampering, _scan_last_hash resumes across re-opens
- Canonical JSON determinism (key order independence)
"""
from __future__ import annotations

import json

import pytest

from core.audit_trail import (
    AuditTrail,
    OrderEvent,
    _canonical_json,
    _hash,
    _REQUIRED_EVENTS,
)


def _make_event(**overrides) -> OrderEvent:
    base = dict(
        event="intent",
        client_oid="oid-1",
        venue="binance_futures",
        symbol="BTCUSDT",
        side="BUY",
        qty=0.01,
        price=60_000.0,
        status="pending",
        payload={"score": 0.5},
    )
    base.update(overrides)
    return OrderEvent(**base)


# ────────────────────────────────────────────────────────────
# OrderEvent
# ────────────────────────────────────────────────────────────

class TestOrderEvent:
    def test_defaults(self):
        e = OrderEvent(event="intent", client_oid="x", venue="v",
                       symbol="BTC", side="BUY", qty=1.0)
        assert e.price is None
        assert e.status == ""
        assert e.payload == {}

    def test_payload_is_per_instance(self):
        a = OrderEvent(event="intent", client_oid="a", venue="v",
                       symbol="BTC", side="BUY", qty=1.0)
        b = OrderEvent(event="intent", client_oid="b", venue="v",
                       symbol="BTC", side="SELL", qty=1.0)
        a.payload["x"] = 1
        assert b.payload == {}  # no shared mutable default


# ────────────────────────────────────────────────────────────
# write() — schema and validation
# ────────────────────────────────────────────────────────────

class TestWriteSchema:
    def test_returns_row_with_required_fields(self, tmp_path):
        trail = AuditTrail(engine="newton", strategy_ver="v1",
                           audit_dir=tmp_path)
        row = trail.write(_make_event())
        required = {"ts", "event", "engine", "strategy_ver", "client_oid",
                    "venue", "symbol", "side", "qty", "price", "status",
                    "payload"}
        assert required <= set(row.keys())
        assert row["engine"] == "newton"
        assert row["strategy_ver"] == "v1"

    def test_engine_and_strategy_come_from_constructor(self, tmp_path):
        trail = AuditTrail(engine="citadel", strategy_ver="v3.6",
                           audit_dir=tmp_path)
        row = trail.write(_make_event())
        # Caller doesn't get to override these per-event — identity is
        # pinned to the trail instance.
        assert row["engine"] == "citadel"
        assert row["strategy_ver"] == "v3.6"

    def test_rejects_unknown_event_type(self, tmp_path):
        trail = AuditTrail(engine="e", strategy_ver="v1", audit_dir=tmp_path)
        with pytest.raises(ValueError, match="must be one of"):
            trail.write(_make_event(event="partial_fill"))

    def test_all_documented_events_accepted(self, tmp_path):
        trail = AuditTrail(engine="e", strategy_ver="v1", audit_dir=tmp_path)
        for evt in _REQUIRED_EVENTS:
            trail.write(_make_event(event=evt))

    def test_monthly_filename_format(self, tmp_path):
        trail = AuditTrail(engine="e", strategy_ver="v1", audit_dir=tmp_path)
        trail.write(_make_event())
        files = list(tmp_path.glob("orders-*.jsonl"))
        assert len(files) == 1
        # orders-YYYY-MM.jsonl
        name = files[0].name
        assert name.startswith("orders-") and name.endswith(".jsonl")
        parts = name[len("orders-"):-len(".jsonl")].split("-")
        assert len(parts) == 2
        assert len(parts[0]) == 4 and parts[0].isdigit()
        assert len(parts[1]) == 2 and parts[1].isdigit()


# ────────────────────────────────────────────────────────────
# Append-only file semantics
# ────────────────────────────────────────────────────────────

class TestAppend:
    def test_multiple_writes_are_jsonl(self, tmp_path):
        trail = AuditTrail(engine="e", strategy_ver="v1", audit_dir=tmp_path)
        trail.write(_make_event(client_oid="a"))
        trail.write(_make_event(client_oid="b"))
        trail.write(_make_event(client_oid="c"))
        lines = trail.current_path().read_text(encoding="utf-8").splitlines()
        assert len(lines) == 3
        for line in lines:
            assert json.loads(line)["client_oid"] in {"a", "b", "c"}

    def test_prior_rows_survive_new_writes(self, tmp_path):
        trail = AuditTrail(engine="e", strategy_ver="v1", audit_dir=tmp_path)
        first = trail.write(_make_event(client_oid="first"))
        trail.write(_make_event(client_oid="second"))
        rows = list(trail.iter_rows())
        assert rows[0]["ts"] == first["ts"]
        assert rows[0]["client_oid"] == "first"


# ────────────────────────────────────────────────────────────
# iter_rows reader tolerance
# ────────────────────────────────────────────────────────────

class TestIterRows:
    def test_empty_file_yields_nothing(self, tmp_path):
        trail = AuditTrail(engine="e", strategy_ver="v1", audit_dir=tmp_path)
        assert list(trail.iter_rows()) == []

    def test_skips_blank_and_malformed_lines(self, tmp_path):
        trail = AuditTrail(engine="e", strategy_ver="v1", audit_dir=tmp_path)
        trail.write(_make_event(client_oid="ok1"))
        # Manually corrupt: add a blank line and garbage
        with trail.current_path().open("a", encoding="utf-8") as fh:
            fh.write("\n")
            fh.write("{ not json\n")
            fh.write("\n")
        trail.write(_make_event(client_oid="ok2"))
        oids = [r["client_oid"] for r in trail.iter_rows()]
        assert oids == ["ok1", "ok2"]


# ────────────────────────────────────────────────────────────
# Hash chain
# ────────────────────────────────────────────────────────────

class TestHashChain:
    def test_disabled_means_no_prev_hash_field(self, tmp_path):
        trail = AuditTrail(engine="e", strategy_ver="v1",
                           audit_dir=tmp_path, hash_chain=False)
        row = trail.write(_make_event())
        assert "prev_hash" not in row

    def test_genesis_row_has_prev_hash_none(self, tmp_path):
        trail = AuditTrail(engine="e", strategy_ver="v1",
                           audit_dir=tmp_path, hash_chain=True)
        row = trail.write(_make_event(client_oid="g"))
        assert row["prev_hash"] is None

    def test_second_row_links_to_first(self, tmp_path):
        trail = AuditTrail(engine="e", strategy_ver="v1",
                           audit_dir=tmp_path, hash_chain=True)
        first  = trail.write(_make_event(client_oid="a"))
        second = trail.write(_make_event(client_oid="b"))
        assert second["prev_hash"] == _hash(first)

    def test_verify_chain_ok_on_clean_file(self, tmp_path):
        trail = AuditTrail(engine="e", strategy_ver="v1",
                           audit_dir=tmp_path, hash_chain=True)
        for oid in ("a", "b", "c", "d"):
            trail.write(_make_event(client_oid=oid))
        ok, n = trail.verify_chain()
        assert ok is True
        assert n == 4

    def test_verify_detects_tampering(self, tmp_path):
        trail = AuditTrail(engine="e", strategy_ver="v1",
                           audit_dir=tmp_path, hash_chain=True)
        for oid in ("a", "b", "c"):
            trail.write(_make_event(client_oid=oid))

        # Tamper with row 1 (middle): flip its qty
        path = trail.current_path()
        lines = path.read_text(encoding="utf-8").splitlines()
        bad = json.loads(lines[1])
        bad["qty"] = bad["qty"] + 999.0
        lines[1] = json.dumps(bad, sort_keys=True, separators=(",", ":"),
                              ensure_ascii=False)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        ok, _ = trail.verify_chain()
        assert ok is False

    def test_scan_last_hash_resumes_across_reopen(self, tmp_path):
        t1 = AuditTrail(engine="e", strategy_ver="v1",
                        audit_dir=tmp_path, hash_chain=True)
        first  = t1.write(_make_event(client_oid="a"))
        second = t1.write(_make_event(client_oid="b"))

        # New writer on the same dir: should pick up where t1 left off
        t2 = AuditTrail(engine="e", strategy_ver="v1",
                        audit_dir=tmp_path, hash_chain=True)
        third = t2.write(_make_event(client_oid="c"))
        assert third["prev_hash"] == _hash(second)

        # End-to-end chain is still valid
        ok, n = t2.verify_chain()
        assert ok is True and n == 3
        # (first is referenced via second's prev_hash)
        assert second["prev_hash"] == _hash(first)


# ────────────────────────────────────────────────────────────
# Canonical JSON determinism
# ────────────────────────────────────────────────────────────

class TestCanonicalJson:
    def test_key_order_irrelevant(self):
        a = {"b": 2, "a": 1, "c": 3}
        b = {"a": 1, "b": 2, "c": 3}
        assert _canonical_json(a) == _canonical_json(b)
        assert _hash(a) == _hash(b)

    def test_nested_dicts_also_sorted(self):
        a = {"x": {"z": 1, "y": 2}}
        b = {"x": {"y": 2, "z": 1}}
        assert _hash(a) == _hash(b)

    def test_different_values_different_hash(self):
        assert _hash({"a": 1}) != _hash({"a": 2})
