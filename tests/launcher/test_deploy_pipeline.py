from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import tkinter as tk

from launcher_support import deploy_pipeline
from launcher_support.screens.deploy_pipeline import DeployPipelineScreen


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
def fake_app(gui_root):
    app = MagicMock()
    app.h_stat = MagicMock()
    app.h_path = MagicMock()
    app.f_lbl = MagicMock()
    app._strategies_backtest = MagicMock()
    app._data_backtests = MagicMock()
    app._data_runs_history = MagicMock()
    app._data_engines = MagicMock()
    app._strategies_live = MagicMock()
    app._terminal = MagicMock()
    app._bind_global_nav = MagicMock()
    app._kb = MagicMock()

    def _ui_panel_frame(parent, title, note):
        frame = tk.Frame(parent)
        tk.Label(frame, text=title).pack()
        tk.Label(frame, text=note).pack()
        frame.pack(fill="both", expand=True)
        return frame

    def _ui_action_row(parent, key_label, name, desc, command=None, available=True, tag="", tag_fg=None, tag_bg=None, title_width=22):
        row = tk.Frame(parent)
        row.pack(fill="x")
        tk.Label(row, text=key_label).pack(side="left")
        tk.Label(row, text=name, width=title_width, anchor="w").pack(side="left")
        tk.Label(row, text=desc).pack(side="left")
        tag_lbl = tk.Label(row, text=tag, fg=tag_fg, bg=tag_bg)
        tag_lbl.pack(side="right")
        if command is not None:
            row.bind("<Button-1>", lambda _e: command())
        return row, None, None

    def _ui_back_row(parent, command):
        row = tk.Frame(parent)
        row.pack(fill="x")
        row.bind("<Button-1>", lambda _e: command())
        return row

    app._ui_panel_frame.side_effect = _ui_panel_frame
    app._ui_action_row.side_effect = _ui_action_row
    app._ui_back_row.side_effect = _ui_back_row
    return app


def test_list_deploy_candidates_keeps_best_row_per_engine():
    rows = [
        {"engine": "citadel", "run_id": "citadel_old", "timestamp": "2026-04-20T10:00:00", "roi": -2.0, "sharpe": -0.5},
        {"engine": "citadel", "run_id": "citadel_best", "timestamp": "2026-04-20T12:00:00", "roi": 3.0, "sharpe": 1.1},
        {"engine": "millennium", "run_id": "mill_boot", "timestamp": "2026-04-20T11:00:00", "roi": 8.0, "sharpe": 2.0},
    ]

    candidates = deploy_pipeline.list_deploy_candidates(rows)

    assert [c.slug for c in candidates] == ["citadel", "millennium"]
    assert candidates[0].run_id == "citadel_best"


def test_pick_paper_candidate_prefers_positive_live_ready():
    rows = [
        {"engine": "citadel", "run_id": "c1", "timestamp": "2026-04-20T10:00:00", "roi": -2.0, "sharpe": -0.5},
        {"engine": "janestreet", "run_id": "j1", "timestamp": "2026-04-20T11:00:00", "roi": 4.5, "sharpe": 1.2},
        {"engine": "millennium", "run_id": "m1", "timestamp": "2026-04-20T12:00:00", "roi": 9.0, "sharpe": 2.0},
    ]

    picked = deploy_pipeline.pick_paper_candidate(rows)

    assert picked is rows[1]


def test_pick_bootstrap_candidate_finds_bootstrap_engine():
    rows = [
        {"engine": "citadel", "run_id": "c1", "timestamp": "2026-04-20T10:00:00", "roi": 2.0, "sharpe": 1.1},
        {"engine": "millennium", "run_id": "m1", "timestamp": "2026-04-20T12:00:00", "roi": 7.0, "sharpe": 1.9},
    ]

    picked = deploy_pipeline.pick_bootstrap_candidate(rows)

    assert picked is rows[1]


def test_start_best_paper_candidate_dispatches_exec_live_inline(fake_app):
    deploy_pipeline.start_best_paper_candidate(
        fake_app,
        {
            "paper_candidate": {"engine": "citadel", "run_id": "c1", "timestamp": "2026-04-20T12:00:00", "roi": 3.0, "sharpe": 1.4},
            "bootstrap_candidate": None,
            "total_runs": 1,
            "rows": [],
            "candidates": [],
        },
    )

    fake_app._exec_live_inline.assert_called_once()
    args = fake_app._exec_live_inline.call_args.args
    assert args[0] == "CITADEL"
    assert args[3] == "paper"


def test_start_candidate_rejects_bootstrap_only(fake_app):
    candidate = deploy_pipeline.list_deploy_candidates(
        [{"engine": "millennium", "run_id": "m1", "timestamp": "2026-04-20T12:00:00", "roi": 9.0, "sharpe": 2.0}]
    )[0]

    deploy_pipeline.start_candidate(fake_app, candidate)

    fake_app._exec_live_inline.assert_not_called()


@pytest.mark.gui
def test_screen_builds(gui_root, fake_app):
    screen = DeployPipelineScreen(parent=gui_root, app=fake_app)
    screen.mount()
    assert screen._list_frame is not None
    assert screen._detail_frame is not None


@pytest.mark.gui
def test_screen_on_enter_renders_candidates(gui_root, fake_app, monkeypatch):
    snap = {
        "rows": [],
        "total_runs": 3,
        "paper_candidate": None,
        "bootstrap_candidate": None,
        "candidates": deploy_pipeline.list_deploy_candidates([
            {"engine": "citadel", "run_id": "citadel_best", "timestamp": "2026-04-20T12:00:00", "roi": 3.0, "sharpe": 1.1},
            {"engine": "millennium", "run_id": "mill_boot", "timestamp": "2026-04-20T11:00:00", "roi": 8.0, "sharpe": 2.0},
        ]),
    }
    monkeypatch.setattr("launcher_support.screens.deploy_pipeline.deploy_pipeline.pipeline_snapshot", lambda: snap)
    screen = DeployPipelineScreen(parent=gui_root, app=fake_app)
    screen.mount()

    screen.on_enter()

    assert screen._selected_slug == "citadel"
    assert len(screen._current_candidates) == 2


@pytest.mark.gui
def test_screen_start_selected_candidate_dispatches_paper(gui_root, fake_app, monkeypatch):
    snap = {
        "rows": [],
        "total_runs": 1,
        "paper_candidate": None,
        "bootstrap_candidate": None,
        "candidates": deploy_pipeline.list_deploy_candidates([
            {"engine": "citadel", "run_id": "citadel_best", "timestamp": "2026-04-20T12:00:00", "roi": 3.0, "sharpe": 1.1},
        ]),
    }
    monkeypatch.setattr("launcher_support.screens.deploy_pipeline.deploy_pipeline.pipeline_snapshot", lambda: snap)
    screen = DeployPipelineScreen(parent=gui_root, app=fake_app)
    screen.mount()
    screen.on_enter()

    screen._start_selected_candidate()

    fake_app._exec_live_inline.assert_called_once()
