from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def macro_store(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "macro_brain.db"
    monkeypatch.setattr("config.macro_params.MACRO_DB_PATH", db_path)
    monkeypatch.setattr("macro_brain.persistence.store.MACRO_DB_PATH", db_path)
    from macro_brain.persistence import store

    store.init_db()
    return store


def test_macro_series_many_groups_rows_per_metric(macro_store):
    macro_store.insert_macro("2026-04-21T10:00:00", "SP500", 5100.0, "test")
    macro_store.insert_macro("2026-04-21T10:05:00", "SP500", 5110.0, "test")
    macro_store.insert_macro("2026-04-21T10:00:00", "DXY", 104.1, "test")

    grouped = macro_store.macro_series_many(["SP500", "DXY", "VIX"])

    assert [row["value"] for row in grouped["SP500"]] == [5100.0, 5110.0]
    assert [row["value"] for row in grouped["DXY"]] == [104.1]
    assert grouped["VIX"] == []


def test_latest_macro_many_caps_rows_per_metric(macro_store):
    macro_store.insert_macro("2026-04-21T10:00:00", "SP500", 5100.0, "test")
    macro_store.insert_macro("2026-04-21T10:05:00", "SP500", 5110.0, "test")
    macro_store.insert_macro("2026-04-21T10:10:00", "SP500", 5120.0, "test")
    macro_store.insert_macro("2026-04-21T10:00:00", "DXY", 104.1, "test")
    macro_store.insert_macro("2026-04-21T10:05:00", "DXY", 104.3, "test")

    grouped = macro_store.latest_macro_many(["SP500", "DXY"], n=2)

    assert [row["value"] for row in grouped["SP500"]] == [5120.0, 5110.0]
    assert [row["value"] for row in grouped["DXY"]] == [104.3, 104.1]


def test_macro_map_uses_batch_fetch(monkeypatch):
    from macro_brain import dashboard_view

    def fail_single_fetch(*args, **kwargs):
        raise AssertionError("single-series path should not run")

    def fake_batch(metrics, since=None):
        assert since is None
        assert metrics == ["SP500", "DXY"]
        return {
            "SP500": [
                {"ts": "2026-04-21T10:00:00", "value": 5100.0},
                {"ts": "2026-04-21T10:05:00", "value": 5110.0},
            ],
            "DXY": [
                {"ts": "2026-04-21T10:00:00", "value": 104.1},
            ],
        }

    monkeypatch.setattr("macro_brain.persistence.store.macro_series", fail_single_fetch)
    monkeypatch.setattr("macro_brain.persistence.store.macro_series_many", fake_batch)

    data = dashboard_view._macro_map(["SP500", "DXY"])

    assert data["SP500"]["value"] == 5110.0
    assert data["SP500"]["prev"] == 5100.0
    assert data["SP500"]["series"] == [5100.0, 5110.0]
    assert data["DXY"]["prev"] is None


def test_cot_matrix_uses_batch_latest_fetch(monkeypatch):
    from macro_brain import dashboard_view

    calls = {"batch": 0, "single": 0}

    def fake_batch(metrics, n=1):
        calls["batch"] += 1
        assert n == 1
        assert metrics == ["DXY_NET", "BTC_NET", "BTC_SWAP"]
        return {
            "DXY_NET": [{"value": 10}],
            "BTC_NET": [{"value": -5}],
            "BTC_SWAP": [{"value": 0}],
        }

    def fake_single(*args, **kwargs):
        calls["single"] += 1
        return []

    monkeypatch.setattr("macro_brain.persistence.store.latest_macro_many", fake_batch)
    monkeypatch.setattr("macro_brain.persistence.store.latest_macro", fake_single)

    class Dummy:
        def __init__(self, *args, **kwargs):
            self._bg = kwargs.get("bg", "")

        def pack(self, *args, **kwargs):
            return None

        def cget(self, key):
            if key == "bg":
                return self._bg
            return ""

        def bind(self, *args, **kwargs):
            return None

        def configure(self, *args, **kwargs):
            return None

    monkeypatch.setattr(dashboard_view.tk, "Frame", Dummy)
    monkeypatch.setattr(dashboard_view.tk, "Label", Dummy)

    dashboard_view._cot_matrix(
        Dummy(bg="x"),
        [("DXY", "DXY_NET", None, None), ("BTC", "BTC_NET", "BTC_SWAP", None)],
    )

    assert calls["batch"] == 1
    assert calls["single"] == 0
