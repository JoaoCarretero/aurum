"""Contract tests for core.versioned_state — schema-versioned payloads.

Thin module: adds/reads a ``schema_version`` field on dict payloads.
Tests lock down that the original payload is NOT mutated, that the
read path is tolerant (missing/malformed/non-dict → default), and
that schema_version_of pulls the tag back from any payload shape.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.versioned_state import (
    read_versioned_json,
    schema_version_of,
    with_schema_version,
    write_versioned_json,
)


class TestWithSchemaVersion:
    def test_tags_payload(self):
        out = with_schema_version({"a": 1}, "v2")
        assert out == {"a": 1, "schema_version": "v2"}

    def test_does_not_mutate_input(self):
        src = {"a": 1}
        with_schema_version(src, "v1")
        assert src == {"a": 1}  # no schema_version leaked back in

    def test_overwrites_existing_schema_version(self):
        out = with_schema_version({"schema_version": "old", "x": 1}, "new")
        assert out["schema_version"] == "new"
        assert out["x"] == 1


class TestWriteVersionedJson:
    def test_file_contains_payload_and_version(self, tmp_path):
        dest = tmp_path / "s.json"
        write_versioned_json(dest, {"counter": 42}, "v1")
        data = json.loads(dest.read_text(encoding="utf-8"))
        assert data == {"counter": 42, "schema_version": "v1"}

    def test_returns_path(self, tmp_path):
        out = write_versioned_json(tmp_path / "p.json", {}, "v1")
        assert isinstance(out, Path)


class TestReadVersionedJson:
    def test_missing_returns_default(self, tmp_path):
        assert read_versioned_json(tmp_path / "nope.json") is None
        sentinel = {"bootstrap": True}
        assert read_versioned_json(tmp_path / "nope.json", default=sentinel) is sentinel

    def test_malformed_returns_default(self, tmp_path):
        dest = tmp_path / "bad.json"
        dest.write_text("{ not json", encoding="utf-8")
        assert read_versioned_json(dest, default={}) == {}

    def test_non_dict_returns_default(self, tmp_path):
        dest = tmp_path / "list.json"
        dest.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        # A list isn't a dict — versioned payloads must be dict-shaped.
        assert read_versioned_json(dest, default={}) == {}

    def test_valid_dict_returned(self, tmp_path):
        dest = tmp_path / "ok.json"
        write_versioned_json(dest, {"x": 1}, "v1")
        out = read_versioned_json(dest)
        assert out == {"x": 1, "schema_version": "v1"}


class TestSchemaVersionOf:
    def test_returns_version_when_present(self):
        assert schema_version_of({"schema_version": "v1"}) == "v1"

    def test_none_when_absent(self):
        assert schema_version_of({"x": 1}) is None

    def test_none_when_not_a_dict(self):
        assert schema_version_of([1, 2, 3]) is None
        assert schema_version_of("string") is None
        assert schema_version_of(None) is None

    def test_coerces_version_to_string(self):
        # Int version → returned as str
        assert schema_version_of({"schema_version": 2}) == "2"
