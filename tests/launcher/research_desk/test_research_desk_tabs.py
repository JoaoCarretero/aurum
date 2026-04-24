"""Integration smoke — screen monta + troca tabs sem crash.

Gated via AURUM_TEST_GUI=1 porque exige Tk display; CI headless pula.
"""
from __future__ import annotations
import os
import tkinter as tk
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.mark.skipif(
    not os.environ.get("AURUM_TEST_GUI", ""),
    reason="Tk integration — so roda com AURUM_TEST_GUI=1",
)
def test_screen_builds_and_switches_all_tabs():
    """Com Paperclip mockado, screen monta e _switch_tab pra cada agent
    key nao crasha."""
    root = tk.Tk()
    try:
        app = MagicMock()
        app.h_stat = tk.Label(root)
        app._menu_main_bloomberg = MagicMock()

        mock_client = MagicMock()
        mock_client.is_online.return_value = False
        mock_client.list_agents_cached.return_value = []
        mock_client.list_issues_cached.return_value = []
        mock_client.list_heartbeat_runs_cached.return_value = []

        from launcher_support.screens.research_desk import ResearchDeskScreen
        from launcher_support.research_desk.agents import AGENTS

        screen = ResearchDeskScreen(parent=root, app=app, root_path=Path.cwd())
        screen._client = mock_client
        screen.build()

        assert screen._active_tab == "overview"

        for agent in AGENTS:
            screen._switch_tab(agent.key)
            assert screen._active_tab == agent.key
            assert agent.key in screen._tab_frames

        screen._switch_tab("overview")
        assert screen._active_tab == "overview"
    finally:
        root.destroy()
