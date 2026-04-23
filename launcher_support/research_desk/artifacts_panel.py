"""ArtifactsPanel — lista RECENT ARTIFACTS no Research Desk.

Renderiza os items de artifact_scanner.scan_artifacts() como linhas
[cor agente] TIPO  titulo  idade. Click abre viewer inline (markdown)
em Toplevel — Sprint 3 upgrade pra detail pane embutido no mesmo frame.

Nao faz scan aqui; recebe via update(entries). Screen tem root_path
e chama scanner.
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Any, Callable

from core.ui.scroll import bind_mousewheel
from core.ui.ui_palette import (
    AMBER,
    BG,
    BG3,
    DIM,
    DIM2,
    FONT,
    PANEL,
    WHITE,
)
from launcher_support.research_desk.agents import BY_KEY
from launcher_support.research_desk.artifact_scanner import (
    ArtifactEntry,
    relative_age,
)
from launcher_support.research_desk.palette import AGENT_COLORS


_KIND_LABELS: dict[str, str] = {
    "spec": "SPEC",
    "review": "REVIEW",
    "branch": "BRANCH",
    "audit": "AUDIT",
}


class ArtifactsPanel:
    def __init__(
        self,
        parent: tk.Misc,
        *,
        on_row_click: Callable[[ArtifactEntry], None] | None = None,
        empty_text: str = "nenhum artefato indexado ainda.",
    ):
        self._on_row_click = on_row_click
        self._empty_text = empty_text

        self.frame: tk.Frame = tk.Frame(parent, bg=PANEL)
        self._list_frame: tk.Frame | None = None
        self._current: list[ArtifactEntry] = []
        self._build()

    def _build(self) -> None:
        canvas = tk.Canvas(self.frame, bg=PANEL, highlightthickness=0)
        sb = tk.Scrollbar(self.frame, orient="vertical", command=canvas.yview)
        self._list_frame = tk.Frame(canvas, bg=PANEL)
        self._list_frame.bind(
            "<Configure>",
            lambda _e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=self._list_frame, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        bind_mousewheel(canvas)

    def grid(self, **opts: Any) -> None:
        self.frame.grid(**opts)

    def pack(self, **opts: Any) -> None:
        self.frame.pack(**opts)

    def update(self, entries: list[ArtifactEntry]) -> None:
        self._current = entries
        self._repaint()

    def _repaint(self) -> None:
        if self._list_frame is None:
            return
        for child in self._list_frame.winfo_children():
            child.destroy()
        if not self._current:
            tk.Label(
                self._list_frame, text=f"  {self._empty_text}",
                font=(FONT, 8), fg=DIM, bg=PANEL, anchor="w",
            ).pack(fill="x", pady=6)
            return
        for entry in self._current:
            self._render_row(entry)

    def _render_row(self, entry: ArtifactEntry) -> None:
        if self._list_frame is None:
            return
        row = tk.Frame(self._list_frame, bg=PANEL, cursor="hand2")
        row.pack(fill="x", padx=2, pady=1)
        row.bind("<Button-1>", lambda _e, e=entry: self._on_click(e))

        palette = _agent_palette(entry.agent_key)
        tk.Frame(row, bg=palette or DIM2, width=3).pack(side="left", fill="y")

        content = tk.Frame(row, bg=PANEL)
        content.pack(side="left", fill="x", expand=True, padx=6, pady=2)

        line1 = tk.Frame(content, bg=PANEL)
        line1.pack(fill="x")
        tk.Label(
            line1, text=_KIND_LABELS.get(entry.kind, entry.kind.upper()),
            font=(FONT, 7, "bold"), fg=palette or AMBER, bg=PANEL,
            width=8, anchor="w",
        ).pack(side="left")
        tk.Label(
            line1, text=entry.title[:80],
            font=(FONT, 8), fg=WHITE, bg=PANEL, anchor="w",
        ).pack(side="left", fill="x", expand=True)

        line2 = tk.Frame(content, bg=PANEL)
        line2.pack(fill="x")
        tk.Label(
            line2, text=f"  {entry.agent_key}",
            font=(FONT, 7), fg=DIM, bg=PANEL, anchor="w",
        ).pack(side="left")
        tk.Label(
            line2, text=relative_age(entry),
            font=(FONT, 7), fg=DIM, bg=PANEL, anchor="e",
        ).pack(side="right")

        def _enter(_e: tk.Event) -> None:
            for w in (row, content, line1, line2):
                try:
                    w.configure(bg=BG3)
                except tk.TclError:
                    pass
            for frm in (line1, line2):
                for ch in frm.winfo_children():
                    if isinstance(ch, tk.Label):
                        ch.configure(bg=BG3)

        def _leave(_e: tk.Event) -> None:
            for w in (row, content, line1, line2):
                try:
                    w.configure(bg=PANEL)
                except tk.TclError:
                    pass
            for frm in (line1, line2):
                for ch in frm.winfo_children():
                    if isinstance(ch, tk.Label):
                        ch.configure(bg=PANEL)

        row.bind("<Enter>", _enter)
        row.bind("<Leave>", _leave)

    def _on_click(self, entry: ArtifactEntry) -> None:
        if self._on_row_click is not None:
            self._on_row_click(entry)


def _agent_palette(key: str) -> str | None:
    identity = BY_KEY.get(key)
    if identity is None:
        return None
    return AGENT_COLORS[identity.key].primary


# ── Viewer (Toplevel modal) ───────────────────────────────────────


def open_markdown_viewer(
    parent: tk.Misc, *,
    root_path: Path,
    entry: ArtifactEntry,
) -> None:
    """Abre Toplevel com texto renderizado via markdown_viewer.

    Para branches (kind='branch'), mostra metadata apenas. Para .md,
    renderiza conteudo.
    """
    # Import lazy — evita custo de setup em paths que nunca abrem viewer
    from launcher_support.research_desk.markdown_viewer import (
        configure_text_widget, render_markdown,
    )

    top = tk.Toplevel(parent)
    top.title(f"{entry.kind.upper()} — {entry.title}")
    top.configure(bg=BG)
    top.geometry("820x620")

    # Header
    head = tk.Frame(top, bg=BG, padx=16, pady=10)
    head.pack(fill="x")
    palette = _agent_palette(entry.agent_key)
    tk.Label(
        head, text=entry.agent_key,
        font=(FONT, 9, "bold"),
        fg=palette or AMBER, bg=BG, anchor="w",
    ).pack(side="left")
    tk.Label(
        head, text=f"  ·  {entry.path}",
        font=(FONT, 8), fg=DIM, bg=BG, anchor="w",
    ).pack(side="left")
    tk.Label(
        head, text=relative_age(entry),
        font=(FONT, 8), fg=DIM, bg=BG, anchor="e",
    ).pack(side="right")

    body = tk.Frame(top, bg=BG)
    body.pack(fill="both", expand=True)

    if entry.is_markdown:
        content = _read_markdown(root_path / entry.path)
    else:
        content = f"# Branch\n\n`{entry.path}`\n\n> Use git log/diff pra ver os commits."

    txt = tk.Text(body, bg=BG, fg=WHITE)
    scroll = tk.Scrollbar(body, orient="vertical", command=txt.yview)
    txt.configure(yscrollcommand=scroll.set)
    configure_text_widget(txt)
    render_markdown(txt, content)
    txt.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")

    # ESC fecha
    top.bind("<Escape>", lambda _e: top.destroy())
    top.focus_set()


def _read_markdown(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"# Erro ao abrir arquivo\n\n`{path}`\n\n> {exc}"
