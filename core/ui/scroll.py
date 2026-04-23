"""Shared mouse-wheel scroll helper for scrollable Tk canvases.

Padrao unico pra todos os scroll regions do launcher — elimina bug
classico de `bind_all` + `unbind_all` global que nukava scroll em
outras telas quando o mouse saia de uma area scrollavel.

Como funciona:
- `bind_all("<MouseWheel>")` uma vez com ancestry check por
  `winfo_containing` — se widget sob cursor nao pertence ao canvas,
  no-op. Zero interferencia entre scroll regions.
- `add="+"` pra coexistir com outros handlers.
- Rebind no `<Enter>` caso outra tela (padrao antigo) tenha chamado
  `unbind_all`.
- Linux Button-4/Button-5 suportado alem de MouseWheel Windows/Mac.

Uso:
    from core.ui.scroll import bind_mousewheel
    canvas = tk.Canvas(...)
    bind_mousewheel(canvas)

Substitui o padrao antigo:
    canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _wheel))
    canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
"""
from __future__ import annotations

import tkinter as tk


def bind_mousewheel(canvas: tk.Canvas) -> None:
    """Attach mouse-wheel scrolling to ``canvas`` safely.

    Safe em duplo sentido:
    1. Nao interfere com scroll de outras telas (ancestry check).
    2. Nao quebra se outra tela fizer unbind_all (rebind defensivo).
    """

    def _scroll(delta: int) -> None:
        if delta:
            try:
                canvas.yview_scroll(delta, "units")
            except Exception:
                pass

    def _on_wheel(event: tk.Event) -> None:
        # Ancestry check — so age se widget sob cursor pertence ao canvas.
        try:
            w = canvas.winfo_containing(event.x_root, event.y_root)
        except Exception:
            return
        while w is not None:
            if w is canvas:
                break
            try:
                w = w.master
            except Exception:
                return
        else:
            return
        if getattr(event, "delta", 0):
            _scroll(-1 * (event.delta // 120))
        elif getattr(event, "num", 0) == 4:
            _scroll(-1)
        elif getattr(event, "num", 0) == 5:
            _scroll(1)

    def _rebind(_event: tk.Event | None = None) -> None:
        # Re-registra se outra tela (padrao antigo) tiver chamado
        # unbind_all. Check evita stacking (add="+" acumula).
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            try:
                if not canvas.bind_all(seq):
                    canvas.bind_all(seq, _on_wheel, add="+")
            except Exception:
                pass

    _rebind()
    try:
        canvas.bind("<Enter>", _rebind)
    except Exception:
        pass
