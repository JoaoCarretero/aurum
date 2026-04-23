"""Tipografia distintiva por operativo AI.

Sprint 2.5: cada agente ganha voz tipografica propria nos titulos dos
cards/headers do detail view. Fonts sao checadas contra o sistema;
fallback gracioso pra FONT default (Consolas) se a preferida nao
existir — launcher nao deve quebrar em Linux/macOS/Windows sem Georgia.

Mapa:
  SCRYER   — serif ornamentado (Georgia / Cambria / serif)
             → sugere manuscrito, visao, contemplacao
  ARBITER  — sans-serif rigoroso (Segoe UI / Arial / sans-serif)
             → judicial, limpo, sem decoracao
  ARTIFEX  — monospace (Consolas / Courier New / monospace)
             → engenheiro, codigo, grid
  CURATOR  — sans-serif neutro (Tahoma / Verdana / sans-serif)
             → calmo, eficiente, minimal

API:
    from launcher_support.research_desk.typography import agent_font
    tk.Label(..., font=agent_font("SCRYER", size=14, weight="bold"))
"""
from __future__ import annotations

import tkinter.font as tkfont
from functools import lru_cache

from core.ui.ui_palette import FONT as DEFAULT_FONT


_AGENT_FONT_PREFS: dict[str, tuple[str, ...]] = {
    "SCRYER":  ("Georgia", "Cambria", "Times New Roman", DEFAULT_FONT),
    "ARBITER": ("Segoe UI", "Inter", "Arial", DEFAULT_FONT),
    "ARTIFEX": ("Consolas", "JetBrains Mono", "Courier New", DEFAULT_FONT),
    "CURATOR": ("Tahoma", "Verdana", "Segoe UI", DEFAULT_FONT),
}


@lru_cache(maxsize=8)
def _resolve_family(agent_key: str) -> str:
    """Retorna a primeira familia de fonte disponivel pro agente.

    Cached via lru_cache: a enumeracao de fontes do Tk e custosa e
    so roda 1x por agent_key ao longo da sessao.
    """
    prefs = _AGENT_FONT_PREFS.get(agent_key, (DEFAULT_FONT,))
    try:
        available = set(tkfont.families())
    except RuntimeError:
        # Tk ainda nao inicializou (ambiente test sem Tk root)
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
    """Constroi um font tuple (family, size, style) tipado pra Tk widget.

    Example:
        tk.Label(..., font=agent_font("SCRYER", size=14, weight="bold"))
    """
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
    """Usado por tests pra recomputar apos instalacao mock de fontes."""
    _resolve_family.cache_clear()
