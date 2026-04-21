"""Regression tests for DataCenterScreen.

Focus: ``_get_counts`` TTL cache that keeps reentry cheap on a screen whose
``on_enter`` would otherwise ``rglob`` several engine dirs plus ``stat`` the
cache lake — ~130ms per visit on OneDrive.
"""
from __future__ import annotations

import tkinter as tk
from unittest.mock import MagicMock

import pytest

from launcher_support.screens.data_center import DataCenterScreen


@pytest.fixture(scope="module")
def gui_root():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("tk unavailable")
    root.withdraw()
    yield root
    try:
        root.destroy()
    except Exception:
        pass


@pytest.fixture
def fake_app():
    app = MagicMock()
    app._data_count_backtests.return_value = 10
    app._data_count_procs.return_value = (1, 3)
    app._data_count_reports.return_value = 28
    return app


@pytest.mark.gui
def test_get_counts_first_call_hits_disk(gui_root, fake_app, monkeypatch):
    s = DataCenterScreen(parent=gui_root, app=fake_app)
    monkeypatch.setattr(s, "_cache_tag", lambda: "216 files | 192 MB")
    monkeypatch.setattr(s, "_count_live_runs", lambda: 7)
    counts = s._get_counts()
    assert counts["bt_count"] == 10
    assert counts["eng_running"] == 1
    assert counts["eng_total"] == 3
    assert counts["rep_count"] == 28
    assert counts["cache_tag"] == "216 files | 192 MB"
    assert counts["live_count"] == 7
    assert fake_app._data_count_backtests.call_count == 1
    assert fake_app._data_count_procs.call_count == 1
    assert fake_app._data_count_reports.call_count == 1


@pytest.mark.gui
def test_get_counts_cached_within_ttl(gui_root, fake_app, monkeypatch):
    s = DataCenterScreen(parent=gui_root, app=fake_app)
    cache_tag_calls = {"n": 0}

    def fake_cache_tag():
        cache_tag_calls["n"] += 1
        return "216 files | 192 MB"

    monkeypatch.setattr(s, "_cache_tag", fake_cache_tag)
    s._get_counts()
    s._get_counts()
    s._get_counts()
    assert fake_app._data_count_backtests.call_count == 1
    assert fake_app._data_count_procs.call_count == 1
    assert fake_app._data_count_reports.call_count == 1
    assert cache_tag_calls["n"] == 1


@pytest.mark.gui
def test_get_counts_refetches_after_ttl(gui_root, fake_app, monkeypatch):
    s = DataCenterScreen(parent=gui_root, app=fake_app)
    monkeypatch.setattr(s, "_cache_tag", lambda: "216 files | 192 MB")
    s._get_counts()
    # Force cache stale.
    ts, data = s._counts_cache
    s._counts_cache = (ts - (s._COUNTS_TTL_SEC + 1.0), data)
    s._get_counts()
    assert fake_app._data_count_backtests.call_count == 2
    assert fake_app._data_count_reports.call_count == 2
