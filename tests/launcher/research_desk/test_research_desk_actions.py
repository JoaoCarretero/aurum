"""Tests de actions da Research Desk screen — resolve path + delegate."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from launcher_support.research_desk.agents import RESEARCH


def test_configure_action_resolves_persona_path_and_calls_editor(tmp_path, monkeypatch):
    """_on_configure_click_pure(parent, agent, root) → persona_path() → open_markdown_editor()."""
    calls = {}

    def fake_persona_path(agent_key, root):
        calls["key"] = agent_key
        calls["root"] = root
        return tmp_path / "fake_AGENTS.md"

    def fake_editor(parent, *, path, title_hint):
        calls["parent"] = parent
        calls["path"] = path
        calls["title"] = title_hint
        return MagicMock()

    monkeypatch.setattr(
        "launcher_support.screens.research_desk.persona_path", fake_persona_path,
    )
    monkeypatch.setattr(
        "launcher_support.screens.research_desk.open_markdown_editor",
        fake_editor,
    )

    from launcher_support.screens.research_desk import _on_configure_click_pure

    parent = MagicMock()
    _on_configure_click_pure(parent, RESEARCH, tmp_path)

    assert calls["key"] == "RESEARCH"
    assert calls["root"] == tmp_path
    assert calls["path"] == tmp_path / "fake_AGENTS.md"
    assert "RESEARCH persona" in calls["title"]
