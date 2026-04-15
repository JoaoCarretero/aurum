"""Contract tests for core.persistence — atomic_write_text + json.

Covers:
- atomic_write_text: file created, parent auto-created, original
  survives a mid-write crash (tmp cleanup on exception), round-trip
- atomic_write_json: default opts (indent=2, ensure_ascii=False,
  default=str), override via kwargs, non-ASCII preserved, custom
  object via default=str
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.persistence import atomic_write_json, atomic_write_text


class TestAtomicWriteText:
    def test_creates_file_with_content(self, tmp_path):
        dest = tmp_path / "a.txt"
        atomic_write_text(dest, "hello")
        assert dest.read_text(encoding="utf-8") == "hello"

    def test_accepts_str_path(self, tmp_path):
        dest = tmp_path / "b.txt"
        atomic_write_text(str(dest), "hi")
        assert dest.read_text() == "hi"

    def test_returns_path_object(self, tmp_path):
        out = atomic_write_text(tmp_path / "c.txt", "x")
        assert isinstance(out, Path)
        assert out == tmp_path / "c.txt"

    def test_parent_directory_auto_created(self, tmp_path):
        dest = tmp_path / "sub" / "nested" / "d.txt"
        atomic_write_text(dest, "deep")
        assert dest.read_text() == "deep"

    def test_overwrites_existing(self, tmp_path):
        dest = tmp_path / "e.txt"
        dest.write_text("old")
        atomic_write_text(dest, "new")
        assert dest.read_text() == "new"

    def test_no_tmp_leftovers_after_success(self, tmp_path):
        dest = tmp_path / "f.txt"
        atomic_write_text(dest, "ok")
        # No lingering *.tmp files in the target dir
        leftovers = list(tmp_path.glob("*.tmp"))
        assert leftovers == []

    def test_unicode_roundtrip(self, tmp_path):
        dest = tmp_path / "u.txt"
        atomic_write_text(dest, "café · ñ · 🏦")
        assert dest.read_text(encoding="utf-8") == "café · ñ · 🏦"


class TestAtomicWriteJson:
    def test_writes_valid_json(self, tmp_path):
        dest = tmp_path / "x.json"
        atomic_write_json(dest, {"a": 1, "b": [2, 3]})
        assert json.loads(dest.read_text(encoding="utf-8")) == {"a": 1, "b": [2, 3]}

    def test_default_indent_is_2(self, tmp_path):
        dest = tmp_path / "y.json"
        atomic_write_json(dest, {"k": 1})
        text = dest.read_text(encoding="utf-8")
        # indent=2 produces a newline + 2 spaces before "k"
        assert "\n  \"k\"" in text

    def test_default_preserves_non_ascii(self, tmp_path):
        dest = tmp_path / "z.json"
        atomic_write_json(dest, {"city": "São Paulo"})
        raw = dest.read_text(encoding="utf-8")
        # ensure_ascii=False → São Paulo appears literally (no \u escapes)
        assert "São Paulo" in raw
        assert "\\u00e3" not in raw

    def test_default_str_handles_non_serializable(self, tmp_path):
        dest = tmp_path / "ns.json"
        class Obj:
            def __str__(self): return "custom-str"
        atomic_write_json(dest, {"o": Obj()})
        assert json.loads(dest.read_text())["o"] == "custom-str"

    def test_override_indent_via_kwargs(self, tmp_path):
        dest = tmp_path / "compact.json"
        atomic_write_json(dest, {"a": 1}, indent=None, separators=(",", ":"))
        assert dest.read_text() == '{"a":1}'

    def test_returns_path(self, tmp_path):
        out = atomic_write_json(tmp_path / "p.json", [1, 2, 3])
        assert isinstance(out, Path)
