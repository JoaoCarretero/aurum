"""Smoke tests do SigilCanvas — verifica que desenha itens na Canvas
sem explodir. Rendering visual nao testado (nao ha display).
"""
from __future__ import annotations

import tkinter as tk

import pytest


@pytest.fixture(scope="module")
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk nao disponivel")
    root.withdraw()
    yield root
    try:
        root.destroy()
    except Exception:
        pass


@pytest.mark.gui
def test_sigil_creates_canvas_with_items(tk_root) -> None:
    from launcher_support.research_desk.sigils import SigilCanvas

    sigil = SigilCanvas(tk_root, "RESEARCH", size=96)
    # Canvas deve ter itens drawn (frame + glyph)
    items = sigil.canvas.find_all()
    assert len(items) > 0, "sigil RESEARCH nao desenhou nada"


@pytest.mark.gui
@pytest.mark.parametrize("key", ["RESEARCH", "REVIEW", "BUILD", "CURATE", "AUDIT"])
def test_all_agent_sigils_draw(tk_root, key: str) -> None:
    from launcher_support.research_desk.sigils import SigilCanvas

    sigil = SigilCanvas(tk_root, key, size=64)
    items = sigil.canvas.find_all()
    assert len(items) >= 4, f"{key} deveria desenhar ao menos frame + glyph"


@pytest.mark.gui
def test_unknown_agent_still_renders_frame(tk_root) -> None:
    """Agente desconhecido nao quebra — so desenha o circle frame."""
    from launcher_support.research_desk.sigils import SigilCanvas

    sigil = SigilCanvas(tk_root, "NEBULAR", size=48)
    items = sigil.canvas.find_all()
    # So o frame (circle + 4 marks compasso) = ~5 items
    assert len(items) >= 1


@pytest.mark.gui
def test_size_param_respected(tk_root) -> None:
    from launcher_support.research_desk.sigils import SigilCanvas

    sigil = SigilCanvas(tk_root, "RESEARCH", size=32)
    assert sigil.canvas["width"] == "32"
    assert sigil.canvas["height"] == "32"


@pytest.mark.gui
def test_canvas_supports_layout_passthrough(tk_root) -> None:
    from launcher_support.research_desk.sigils import SigilCanvas

    frame = tk.Frame(tk_root)
    sigil = SigilCanvas(frame, "REVIEW", size=40)
    # Sem explosao nos passthroughs
    sigil.pack(side="left")
    assert sigil.canvas.winfo_manager() == "pack"
