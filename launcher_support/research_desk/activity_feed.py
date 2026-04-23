"""ActivityFeed — timeline unica agregando issues + artifacts + branches.

Widget standalone, scrollavel. Pagination via "LOAD MORE" button: exibe
N eventos inicialmente, click duplica ate acabar.

Visual: cada row tem [icone da acao] [tipo] titulo [agente] [age].
Cor do accent = cor do agente. Pipeline/Artifacts panels ficam
complementares ao feed (feed e visao plana; os painels especificos
sao focados).
"""
from __future__ import annotations

import time
import tkinter as tk
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
from launcher_support.research_desk.activity_events import (
    ActivityEvent,
    action_icon,
    action_label,
    merge_events,
)
from launcher_support.research_desk.agents import BY_KEY
from launcher_support.research_desk.palette import AGENT_COLORS


_INITIAL_PAGE = 20
_PAGE_INCREMENT = 20


class ActivityFeed:
    def __init__(
        self,
        parent: tk.Misc,
        *,
        on_event_click: Callable[[ActivityEvent], None] | None = None,
        empty_text: str = "timeline vazia — sem eventos registrados.",
    ):
        self._on_event_click = on_event_click
        self._empty_text = empty_text

        self._visible_count = _INITIAL_PAGE
        self._current: list[ActivityEvent] = []

        self.frame: tk.Frame = tk.Frame(parent, bg=PANEL)
        self._list_frame: tk.Frame | None = None
        self._load_more_btn: tk.Label | None = None
        self._counter_label: tk.Label | None = None
        self._build()

    def _build(self) -> None:
        # Scrollable list
        list_wrap = tk.Frame(self.frame, bg=PANEL)
        list_wrap.pack(fill="both", expand=True)

        canvas = tk.Canvas(list_wrap, bg=PANEL, highlightthickness=0)
        sb = tk.Scrollbar(list_wrap, orient="vertical", command=canvas.yview)
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

        # Footer com counter + load more
        footer = tk.Frame(self.frame, bg=PANEL)
        footer.pack(fill="x", pady=(4, 0))
        self._counter_label = tk.Label(
            footer, text="",
            font=(FONT, 7), fg=DIM, bg=PANEL, anchor="w",
        )
        self._counter_label.pack(side="left", padx=(6, 0))
        self._load_more_btn = tk.Label(
            footer, text="  LOAD MORE  ",
            font=(FONT, 7, "bold"), fg=BG, bg=AMBER,
            cursor="hand2", padx=6, pady=2,
        )
        self._load_more_btn.pack(side="right")
        self._load_more_btn.bind("<Button-1>", lambda _e: self._load_more())

    # ── Layout passthrough ────────────────────────────────────────

    def grid(self, **opts: Any) -> None:
        self.frame.grid(**opts)

    def pack(self, **opts: Any) -> None:
        self.frame.pack(**opts)

    # ── Public API ────────────────────────────────────────────────

    def update(self, events: list[ActivityEvent]) -> None:
        """Recebe lista ordenada DESC. Reseta paginacao se a cabeca mudou."""
        prev_head = (
            self._current[0].when_epoch if self._current else 0.0
        )
        new_head = events[0].when_epoch if events else 0.0
        if new_head != prev_head:
            # Evento novo na cabeca — volta pra primeira pagina
            self._visible_count = _INITIAL_PAGE
        self._current = events
        self._repaint()

    def from_raw(
        self, *, issues_raw: list[dict], artifacts_raw: list,
    ) -> None:
        """Conveniencia: merge_events + update."""
        self.update(merge_events(issues=issues_raw, artifacts=artifacts_raw))

    def clear(self, message: str | None = None) -> None:
        self._current = []
        if self._list_frame is None:
            return
        for child in self._list_frame.winfo_children():
            child.destroy()
        if message:
            tk.Label(
                self._list_frame, text=f"  {message}",
                font=(FONT, 8), fg=DIM, bg=PANEL, anchor="w",
            ).pack(fill="x", pady=6)
        self._update_footer()

    # ── Repaint ───────────────────────────────────────────────────

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
            self._update_footer()
            return

        visible = self._current[: self._visible_count]
        for ev in visible:
            self._render_row(ev)

        self._update_footer()

    def _update_footer(self) -> None:
        if self._counter_label is None or self._load_more_btn is None:
            return
        total = len(self._current)
        shown = min(total, self._visible_count)
        self._counter_label.configure(
            text=f"{shown} / {total} eventos",
        )
        if shown >= total:
            # Hide or disable load more
            self._load_more_btn.configure(
                fg=DIM, bg=BG3, cursor="arrow",
            )
        else:
            self._load_more_btn.configure(
                fg=BG, bg=AMBER, cursor="hand2",
            )

    def _load_more(self) -> None:
        total = len(self._current)
        if self._visible_count >= total:
            return
        self._visible_count = min(total, self._visible_count + _PAGE_INCREMENT)
        self._repaint()

    def _render_row(self, event: ActivityEvent) -> None:
        if self._list_frame is None:
            return
        row = tk.Frame(self._list_frame, bg=PANEL, cursor="hand2")
        row.pack(fill="x", padx=2, pady=1)
        row.bind("<Button-1>", lambda _e, e=event: self._on_click(e))

        # Accent stripe (cor do agente)
        accent_color = _agent_accent(event.agent_key)
        tk.Frame(row, bg=accent_color, width=3).pack(side="left", fill="y")

        content = tk.Frame(row, bg=PANEL)
        content.pack(side="left", fill="x", expand=True, padx=6, pady=2)

        # Linha 1: [icon] [TYPE] title
        line1 = tk.Frame(content, bg=PANEL)
        line1.pack(fill="x")
        tk.Label(
            line1, text=action_icon(event.action),
            font=(FONT, 10), fg=accent_color, bg=PANEL, width=2, anchor="w",
        ).pack(side="left")
        tk.Label(
            line1, text=action_label(event.action),
            font=(FONT, 7, "bold"), fg=accent_color, bg=PANEL, width=10,
            anchor="w",
        ).pack(side="left")
        tk.Label(
            line1, text=event.title,
            font=(FONT, 8), fg=WHITE, bg=PANEL, anchor="w",
        ).pack(side="left", fill="x", expand=True)

        # Linha 2: agente + detail + age
        line2 = tk.Frame(content, bg=PANEL)
        line2.pack(fill="x")
        left2 = tk.Label(
            line2,
            text=f"  {event.agent_key or '—'}  ·  {event.detail}",
            font=(FONT, 7), fg=DIM, bg=PANEL, anchor="w",
        )
        left2.pack(side="left")
        right2 = tk.Label(
            line2, text=_relative_age(event.when_epoch),
            font=(FONT, 7), fg=DIM, bg=PANEL, anchor="e",
        )
        right2.pack(side="right")

    def _on_click(self, event: ActivityEvent) -> None:
        if self._on_event_click is not None:
            self._on_event_click(event)


def _agent_accent(key: str) -> str:
    if not key:
        return DIM2
    identity = BY_KEY.get(key)
    if identity is None:
        return DIM2
    return AGENT_COLORS[identity.key].primary


def _relative_age(epoch: float) -> str:
    if epoch <= 0:
        return "—"
    delta = int(time.time() - epoch)
    if delta < 0:
        return "agora"
    if delta < 60:
        return f"{delta}s atras"
    if delta < 3600:
        return f"{delta // 60}min atras"
    if delta < 86400:
        return f"{delta // 3600}h atras"
    return f"{delta // 86400}d atras"
