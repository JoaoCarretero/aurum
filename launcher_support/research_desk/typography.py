"""Research Desk typography.

All agent surfaces use the launcher terminal font. The role is expressed by
content, status and restrained accent color, not by per-agent typefaces.
"""
from __future__ import annotations

import tkinter.font as tkfont
from functools import lru_cache

from core.ui.ui_palette import FONT as DEFAULT_FONT


_AGENT_FONT_PREFS: dict[str, tuple[str, ...]] = {
    "RESEARCH": (DEFAULT_FONT,),
    "REVIEW": (DEFAULT_FONT,),
    "BUILD": (DEFAULT_FONT,),
    "CURATE": (DEFAULT_FONT,),
    "AUDIT": (DEFAULT_FONT,),
}


@lru_cache(maxsize=8)
def _resolve_family(agent_key: str) -> str:
    """Return the configured terminal font when available."""
    prefs = _AGENT_FONT_PREFS.get(agent_key, (DEFAULT_FONT,))
    try:
        available = set(tkfont.families())
    except RuntimeError:
        return DEFAULT_FONT
    for family in prefs:
        if family in available:
            return family
    return DEFAULT_FONT


def agent_font(
    agent_key: str,
    *,
    size: int = 10,
    weight: str = "normal",
    slant: str = "roman",
) -> tuple[str, int, str]:
    """Build a Tk font tuple for agent widgets."""
    family = _resolve_family(agent_key)
    if weight == "bold" and slant == "italic":
        style = "bold italic"
    elif weight == "bold":
        style = "bold"
    elif slant == "italic":
        style = "italic"
    else:
        style = "normal"
    return (family, size, style)


def reset_cache() -> None:
    """Clear cached font family resolution for tests."""
    _resolve_family.cache_clear()
