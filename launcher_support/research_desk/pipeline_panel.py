"""PipelinePanel — lista de tickets ativos no Research Desk.

Renderiza os itens retornados por filter_active(issues) como linhas com:
  [indicador cor do assignee] STATUS  TITULO...  idade

Click numa linha abre modal de detalhe (stub no Sprint 1.4; Sprint 3
liga stream de comentarios). No Sprint 1, so lista + auto-refresh.

Padrao: espelha a list-widget de DeployPipelineScreen (canvas scrollable).
"""
from __future__ import annotations

import tkinter as tk
from typing import Any, Callable

from core.ui.scroll import bind_mousewheel
from core.ui.ui_palette import (
    BG,
    BG3,
    DIM,
    DIM2,
    FONT,
    HAZARD,
    PANEL,
    RED,
    WHITE,
)
from launcher_support.research_desk.agents import BY_UUID
from launcher_support.research_desk.issue_view import IssueView, filter_active
from launcher_support.research_desk.palette import AGENT_COLORS


# Cor do label de status
_STATUS_COLORS: dict[str, str] = {
    "in_progress": HAZARD,
    "todo": DIM,
}

# Cor da prioridade (small pill ao lado)
_PRIORITY_COLORS: dict[str, str] = {
    "high": RED,
    "medium": DIM,
    "low": DIM2,
}


class PipelinePanel:
    """Widget standalone do painel ACTIVE PIPELINE."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        on_row_click: Callable[[IssueView], None] | None = None,
        empty_text: str = "sem tickets ativos no momento.",
    ):
        self._on_row_click = on_row_click
        self._empty_text = empty_text

        self.frame: tk.Frame = tk.Frame(parent, bg=PANEL)
        self._list_frame: tk.Frame | None = None
        self._list_canvas: tk.Canvas | None = None
        self._current_views: list[IssueView] = []
        self._build()

    def _build(self) -> None:
        # Scrollable area
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
        self._list_canvas = canvas

    # ── Layout passthrough ────────────────────────────────────────

    def grid(self, **opts: Any) -> None:
        self.frame.grid(**opts)

    def pack(self, **opts: Any) -> None:
        self.frame.pack(**opts)

    # ── Update (idempotente) ──────────────────────────────────────

    def update(self, issues_raw: list[dict]) -> None:
        """Refresca a lista. Chama filter_active + repinta."""
        views = filter_active(issues_raw)
        self._current_views = views
        self._repaint()

    def show_offline(self, message: str = "paperclip offline") -> None:
        self._current_views = []
        self._repaint_with_message(message)

    # ── Internals ─────────────────────────────────────────────────

    def _repaint(self) -> None:
        if self._list_frame is None:
            return
        for child in self._list_frame.winfo_children():
            child.destroy()

        if not self._current_views:
            self._repaint_with_message(self._empty_text)
            return

        for view in self._current_views:
            self._render_row(view)

    def _repaint_with_message(self, message: str) -> None:
        if self._list_frame is None:
            return
        for child in self._list_frame.winfo_children():
            child.destroy()
        tk.Label(
            self._list_frame, text=f"  {message}",
            font=(FONT, 8), fg=DIM, bg=PANEL, anchor="w",
        ).pack(fill="x", pady=6)

    def _render_row(self, view: IssueView) -> None:
        if self._list_frame is None:
            return
        row = tk.Frame(self._list_frame, bg=PANEL, cursor="hand2")
        row.pack(fill="x", padx=2, pady=1)
        row.bind("<Button-1>", lambda _e, v=view: self._on_click(v))

        # Assignee accent stripe (cor do agente na esquerda)
        agent_color = _agent_accent(view.assignee_uuid)
        tk.Frame(row, bg=agent_color, width=3).pack(side="left", fill="y")

        content = tk.Frame(row, bg=PANEL)
        content.pack(side="left", fill="x", expand=True, padx=6, pady=2)

        # Linha 1: [STATUS] [PRIO] titulo
        line1 = tk.Frame(content, bg=PANEL)
        line1.pack(fill="x")
        status_col = _STATUS_COLORS.get(view.status, DIM)
        tk.Label(
            line1, text=view.status.upper().replace("_", " "),
            font=(FONT, 7, "bold"), fg=status_col, bg=PANEL, width=12, anchor="w",
        ).pack(side="left")
        prio_col = _PRIORITY_COLORS.get(view.priority, DIM)
        tk.Label(
            line1, text=f"[{view.priority.upper()}]",
            font=(FONT, 7, "bold"), fg=prio_col, bg=PANEL, width=8, anchor="w",
        ).pack(side="left")
        tk.Label(
            line1, text=view.title,
            font=(FONT, 8), fg=WHITE, bg=PANEL, anchor="w",
        ).pack(side="left", fill="x", expand=True)

        # Linha 2: assignee + age
        line2 = tk.Frame(content, bg=PANEL)
        line2.pack(fill="x")
        assignee_text = _assignee_label(view.assignee_uuid)
        tk.Label(
            line2, text=f"  {assignee_text}",
            font=(FONT, 7), fg=DIM, bg=PANEL, anchor="w",
        ).pack(side="left")
        tk.Label(
            line2, text=view.age,
            font=(FONT, 7), fg=DIM, bg=PANEL, anchor="e",
        ).pack(side="right")

        # Hover effect subtil
        def _enter(_e: tk.Event) -> None:
            row.configure(bg=BG3)
            for child in content.winfo_children():
                for leaf in child.winfo_children():
                    if isinstance(leaf, tk.Label):
                        leaf.configure(bg=BG3)
                if isinstance(child, tk.Frame):
                    child.configure(bg=BG3)

        def _leave(_e: tk.Event) -> None:
            row.configure(bg=PANEL)
            for child in content.winfo_children():
                for leaf in child.winfo_children():
                    if isinstance(leaf, tk.Label):
                        leaf.configure(bg=PANEL)
                if isinstance(child, tk.Frame):
                    child.configure(bg=PANEL)

        row.bind("<Enter>", _enter)
        row.bind("<Leave>", _leave)

    def _on_click(self, view: IssueView) -> None:
        if self._on_row_click is not None:
            self._on_row_click(view)


def _agent_accent(uuid: str) -> str:
    """Retorna cor primaria do agente associado, ou BG se nao atribuido."""
    identity = BY_UUID.get(uuid)
    if identity is None:
        return BG
    return AGENT_COLORS[identity.key].primary


def _assignee_label(uuid: str) -> str:
    """Retorna 'RESEARCH' etc, ou '—' se nao atribuido."""
    identity = BY_UUID.get(uuid)
    return identity.key if identity is not None else "—"
