"""Tests pro markdown_editor — pure functions testaveis sem Tk."""
from __future__ import annotations

from pathlib import Path

from launcher_support.research_desk.markdown_editor import (
    is_dirty_label,
    persona_path,
)


def test_dirty_label_prefixes_bullet_when_dirty() -> None:
    assert is_dirty_label(path_name="SCRYER.md", dirty=True) == "● SCRYER.md"


def test_dirty_label_plain_when_clean() -> None:
    assert is_dirty_label(path_name="SCRYER.md", dirty=False) == "SCRYER.md"


def test_persona_path_prefers_agent_specific(tmp_path: Path) -> None:
    specific = tmp_path / "docs" / "agents" / "scryer.md"
    specific.parent.mkdir(parents=True)
    specific.write_text("# scryer", encoding="utf-8")

    (tmp_path / "AGENTS.md").write_text("# shared", encoding="utf-8")

    result = persona_path("SCRYER", tmp_path)
    assert result == specific


def test_persona_path_falls_back_to_root_agents(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("# shared", encoding="utf-8")
    # docs/agents/ nao existe
    result = persona_path("SCRYER", tmp_path)
    assert result == tmp_path / "AGENTS.md"


def test_persona_path_returns_candidate_if_nothing_exists(tmp_path: Path) -> None:
    # Nada existe — caller cria
    result = persona_path("ARBITER", tmp_path)
    expected = tmp_path / "docs" / "agents" / "arbiter.md"
    assert result == expected
    assert not result.exists()


def test_persona_path_lowercases_key(tmp_path: Path) -> None:
    specific = tmp_path / "docs" / "agents" / "curator.md"
    specific.parent.mkdir(parents=True)
    specific.write_text("x", encoding="utf-8")
    result = persona_path("CURATOR", tmp_path)
    assert result.name == "curator.md"


def test_persona_path_accepts_str_root(tmp_path: Path) -> None:
    result = persona_path("SCRYER", str(tmp_path))
    assert isinstance(result, Path)
