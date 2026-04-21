"""Integration: Terminal app shows LIVE RUNS screen via ScreenManager."""
from __future__ import annotations

import sqlite3
import tkinter as tk
from pathlib import Path

import pytest

from core.ops import db_live_runs
from tools.maintenance.migrations import migration_001_live_runs as mig


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
def fake_live_db(tmp_path, monkeypatch):
    db = tmp_path / "a.db"
    conn = sqlite3.connect(db)
    mig.apply(conn)
    conn.close()
    monkeypatch.setattr(db_live_runs, "DB_PATH", db)
    db_live_runs.upsert(
        run_id="test_paper_2026-04-20_1200",
        engine="millennium", mode="paper",
        started_at="2026-04-20T12:00:00+00:00",
        run_dir="data/millennium_paper/2026-04-20_1200",
        host="localhost", status="running",
        tick_count=20, novel_count=3, equity=10123.45,
        last_tick_at="2026-04-20T12:05:00+00:00",
    )
    return db


@pytest.mark.gui
def test_live_runs_screen_shows_via_screen_manager(fake_live_db, gui_root):
    parent = None
    try:
        from launcher_support.screens.manager import ScreenManager
        from launcher_support.screens.live_runs import LiveRunsScreen
        from unittest.mock import MagicMock

        app = MagicMock()
        parent = tk.Frame(gui_root)
        mgr = ScreenManager(parent=parent)
        mgr.register(
            "live_runs",
            lambda p, a=app: LiveRunsScreen(parent=p, app=a),
        )
        s = mgr.show("live_runs")
        assert s is not None
        assert mgr.current_name() == "live_runs"
    finally:
        if parent is not None:
            parent.destroy()
