"""Tests da typography module — resolver de fontes com fallback."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from launcher_support.research_desk.typography import (
    _AGENT_FONT_PREFS,
    agent_font,
    reset_cache,
)


@pytest.fixture(autouse=True)
def _clear_font_cache():
    """Cache lru_cache isola state cross-test."""
    reset_cache()
    yield
    reset_cache()


def test_agent_font_returns_tuple_shape() -> None:
    with patch(
        "tkinter.font.families",
        return_value={"Georgia", "Consolas", "Tahoma", "Segoe UI", "Arial"},
    ):
        result = agent_font("SCRYER", size=12, weight="bold")
    assert isinstance(result, tuple)
    assert len(result) == 3
    family, size, style = result
    assert isinstance(family, str)
    assert size == 12
    assert style == "bold"


def test_scryer_prefers_serif() -> None:
    with patch(
        "tkinter.font.families",
        return_value={"Georgia", "Consolas"},
    ):
        family, _, _ = agent_font("SCRYER")
    assert family == "Georgia"


def test_arbiter_prefers_sans_rigorous() -> None:
    with patch(
        "tkinter.font.families",
        return_value={"Segoe UI", "Consolas"},
    ):
        family, _, _ = agent_font("ARBITER")
    assert family == "Segoe UI"


def test_artifex_prefers_mono() -> None:
    with patch(
        "tkinter.font.families",
        return_value={"Consolas", "Tahoma"},
    ):
        family, _, _ = agent_font("ARTIFEX")
    assert family == "Consolas"


def test_curator_prefers_sans_neutral() -> None:
    with patch(
        "tkinter.font.families",
        return_value={"Tahoma", "Consolas"},
    ):
        family, _, _ = agent_font("CURATOR")
    assert family == "Tahoma"


def test_fallback_when_preferred_missing() -> None:
    # So Consolas ta disponivel — SCRYER precisa cair pro default
    with patch(
        "tkinter.font.families",
        return_value={"Consolas"},
    ):
        family, _, _ = agent_font("SCRYER")
    assert family == "Consolas"  # DEFAULT_FONT


def test_unknown_agent_uses_default() -> None:
    with patch(
        "tkinter.font.families",
        return_value={"Consolas", "Georgia"},
    ):
        family, _, _ = agent_font("UNKNOWN")
    assert family == "Consolas"


def test_tk_unavailable_falls_back() -> None:
    with patch(
        "tkinter.font.families",
        side_effect=RuntimeError("Tk not initialized"),
    ):
        family, _, _ = agent_font("SCRYER")
    assert family == "Consolas"


def test_weight_styles() -> None:
    with patch("tkinter.font.families", return_value={"Consolas"}):
        assert agent_font("ARBITER", weight="bold")[2] == "bold"
        assert agent_font("ARBITER", weight="normal")[2] == "normal"
        assert agent_font("ARBITER", slant="italic")[2] == "italic"
        assert agent_font("ARBITER", weight="bold", slant="italic")[2] == "bold italic"


def test_each_agent_has_prefs() -> None:
    for key in ("SCRYER", "ARBITER", "ARTIFEX", "CURATOR"):
        assert key in _AGENT_FONT_PREFS
        assert len(_AGENT_FONT_PREFS[key]) >= 2
