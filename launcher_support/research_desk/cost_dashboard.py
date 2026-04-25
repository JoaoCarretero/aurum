"""Cost Dashboard Toplevel — visao consolidada do orçamento.

Layout:
  - Header com total spent / cap / pct + pill de alerta
  - Barras horizontais por agente (spent/cap) com trend sparkline 30d
  - Alert row: agentes em alert/crit list

Zero deps — Canvas drawn sparklines via create_line. Nao bloqueia
loop principal: dados vem via callback injetado pelo Screen.
"""
from __future__ import annotations

import tkinter as tk
from typing import Callable

from core.ui.ui_palette import (
    AMBER,
    AMBER_D,
    BG,
    BG2,
    BG3,
    BORDER,
    DIM,
    DIM2,
    FONT,
    GREEN,
    HAZARD,
    PANEL,
    RED,
    WHITE,
)
from launcher_support.research_desk.cost_summary import (
    LEVEL_ALERT,
    LEVEL_CRIT,
    LEVEL_GREEN,
    LEVEL_WARN,
    AgentCostView,
    CostSummary,
    format_cap_text,
    normalize_trend,
)
from launcher_support.research_desk.palette import AGENT_COLORS


_REFRESH_MS = 5000
_TREND_WIDTH = 200
_TREND_HEIGHT = 28

# level -> cor (barra + pill)
_LEVEL_COLOR: dict[str, str] = {
    LEVEL_GREEN: GREEN,
    LEVEL_WARN: AMBER,
    LEVEL_ALERT: AMBER_D,
    LEVEL_CRIT: HAZARD,
}


def open_cost_dashboard(
    parent: tk.Misc,
    *,
    fetch_summary: Callable[[], CostSummary],
) -> "CostDashboard":
    return CostDashboard(parent, fetch_summary=fetch_summary)


class CostDashboard:
    def __init__(
        self, parent: tk.Misc,
        *, fetch_summary: Callable[[], CostSummary],
    ):
        self._fetch_summary = fetch_summary
        self._closed = False
        self._refresh_after_id: str | None = None

        self.top = tk.Toplevel(parent)
        self.top.title("COST DASHBOARD  ·  aurum research")
        self.top.configure(bg=BG)
        self.top.geometry("780x560")
        self.top.transient(parent)

        # Refs pra repaint
        self._header_pct: tk.Label | None = None
        self._header_pill: tk.Label | None = None
        self._header_total: tk.Label | None = None
        self._body: tk.Frame | None = None
        self._alert_row: tk.Frame | None = None

        self._build()
        self.top.bind("<Escape>", lambda _e: self._close())
        self.top.protocol("WM_DELETE_WINDOW", self._close)
        self._refresh(initial=True)
        self.top.focus_set()

    def _build(self) -> None:
        wrap = tk.Frame(self.top, bg=BG, padx=18, pady=14)
        wrap.pack(fill="both", expand=True)

        # Header
        header = tk.Frame(wrap, bg=BG)
        header.pack(fill="x")
        tk.Label(
            header, text="COST DASHBOARD",
            font=(FONT, 12, "bold"), fg=AMBER, bg=BG, anchor="w",
        ).pack(side="left")
        self._header_pill = tk.Label(
            header, text="  OK  ",
            font=(FONT, 8, "bold"), fg=BG, bg=GREEN, padx=6,
        )
        self._header_pill.pack(side="right")
        self._header_pct = tk.Label(
            header, text="—",
            font=(FONT, 11, "bold"), fg=WHITE, bg=BG,
        )
        self._header_pct.pack(side="right", padx=(0, 10))
        self._header_total = tk.Label(
            header, text="", font=(FONT, 8), fg=DIM, bg=BG,
        )
        self._header_total.pack(side="right", padx=(0, 12))

        tk.Frame(wrap, bg=BG3, height=1).pack(fill="x", pady=(10, 8))

        # Alert row (so aparece se agentes_over_alert > 0)
        self._alert_row = tk.Frame(wrap, bg=BG)
        self._alert_row.pack(fill="x", pady=(0, 8))

        tk.Label(
            wrap, text="BY AGENT",
            font=(FONT, 8, "bold"), fg=AMBER_D, bg=BG, anchor="w",
        ).pack(anchor="w", pady=(4, 4))

        # Body com rows por agente
        self._body = tk.Frame(wrap, bg=BG)
        self._body.pack(fill="both", expand=True)

        # Footer hint
        tk.Frame(wrap, bg=BG3, height=1).pack(fill="x", pady=(10, 4))
        tk.Label(
            wrap, text="Esc fecha  ·  refresh 5s",
            font=(FONT, 7), fg=DIM, bg=BG, anchor="e",
        ).pack(fill="x")

    def _close(self) -> None:
        self._closed = True
        if self._refresh_after_id is not None:
            try:
                self.top.after_cancel(self._refresh_after_id)
            except Exception:
                pass
            self._refresh_after_id = None
        try:
            self.top.destroy()
        except Exception:
            pass

    def _refresh(self, *, initial: bool = False) -> None:
        if self._closed:
            return
        try:
            summary = self._fetch_summary()
        except Exception:
            summary = None

        if summary is not None:
            self._apply(summary)

        # Re-arm
        delay = 50 if initial else _REFRESH_MS
        try:
            self._refresh_after_id = self.top.after(
                delay, lambda: self._refresh(initial=False),
            )
        except Exception:
            pass

    def _apply(self, summary: CostSummary) -> None:
        if self._closed:
            return
        # Header
        if self._header_pct is not None:
            self._header_pct.configure(text=format_cap_text(summary.total_pct))
        if self._header_total is not None:
            self._header_total.configure(
                text=f"{summary.total_spent_text} / {summary.total_cap_text}",
            )
        if self._header_pill is not None:
            color = _LEVEL_COLOR.get(summary.total_level, DIM)
            self._header_pill.configure(
                text=f"  {summary.total_level.upper()}  ",
                bg=color,
            )

        # Alert row
        if self._alert_row is not None:
            for child in self._alert_row.winfo_children():
                child.destroy()
            if summary.agents_over_alert:
                tk.Label(
                    self._alert_row, text="ATENCAO:  ",
                    font=(FONT, 8, "bold"), fg=HAZARD, bg=BG,
                ).pack(side="left")
                tk.Label(
                    self._alert_row,
                    text=", ".join(summary.agents_over_alert) + "  acima de 80% do budget",
                    font=(FONT, 8), fg=AMBER, bg=BG,
                ).pack(side="left")

        # Body — repaint limpo
        if self._body is not None:
            for child in self._body.winfo_children():
                child.destroy()
            for view in summary.by_agent:
                self._render_agent_row(self._body, view)

    def _render_agent_row(self, parent: tk.Frame, view: AgentCostView) -> None:
        row = tk.Frame(parent, bg=PANEL)
        row.pack(fill="x", pady=3, padx=0)

        # Accent stripe cor do agente
        palette = AGENT_COLORS.get(view.agent_key)
        accent = palette.primary if palette else AMBER
        tk.Frame(row, bg=accent, width=3).pack(side="left", fill="y")

        inner = tk.Frame(row, bg=PANEL)
        inner.pack(side="left", fill="both", expand=True, padx=8, pady=6)

        # Linha 1: name + spent/cap + pct pill
        line1 = tk.Frame(inner, bg=PANEL)
        line1.pack(fill="x")
        tk.Label(
            line1, text=view.agent_key,
            font=(FONT, 10, "bold"), fg=accent, bg=PANEL, width=10, anchor="w",
        ).pack(side="left")
        tk.Label(
            line1, text=f"{view.spent_text} / {view.cap_text}",
            font=(FONT, 8), fg=WHITE, bg=PANEL, anchor="w",
        ).pack(side="left", padx=(8, 0))
        pill_color = _LEVEL_COLOR.get(view.level, DIM)
        tk.Label(
            line1, text=f" {format_cap_text(view.pct)} ",
            font=(FONT, 8, "bold"), fg=BG, bg=pill_color, padx=4,
        ).pack(side="right")

        # Linha 2: progress bar full-width + sparkline
        line2 = tk.Frame(inner, bg=PANEL)
        line2.pack(fill="x", pady=(5, 0))

        track = tk.Frame(
            line2, bg=BG2, height=8,
            highlightbackground=BORDER, highlightthickness=1,
        )
        track.pack(side="left", fill="x", expand=True)
        track.pack_propagate(False)
        fill_pct = min(1.0, view.pct)
        if fill_pct > 0:
            fill = tk.Frame(track, bg=pill_color, height=6)
            fill.place(relwidth=fill_pct, relheight=1.0)

        # Sparkline 30d (so se tiver dados)
        if view.trend_cents:
            self._draw_sparkline(line2, view.trend_cents, accent)

    def _draw_sparkline(
        self, parent: tk.Frame, values: list[int], color: str,
    ) -> None:
        canvas = tk.Canvas(
            parent, bg=PANEL, width=_TREND_WIDTH, height=_TREND_HEIGHT,
            highlightthickness=0, borderwidth=0,
        )
        canvas.pack(side="right", padx=(10, 0))
        points = normalize_trend(values, n_points=30)
        n = len(points)
        if n < 2:
            return
        x_step = _TREND_WIDTH / (n - 1)
        pad = 3
        y_range = _TREND_HEIGHT - (pad * 2)
        coords: list[float] = []
        for i, p in enumerate(points):
            x = i * x_step
            y = _TREND_HEIGHT - pad - (p * y_range)
            coords.extend([x, y])
        canvas.create_line(*coords, fill=color, width=1.5, smooth=True)
        # Dot no ponto final
        last_x = coords[-2]
        last_y = coords[-1]
        canvas.create_oval(
            last_x - 2, last_y - 2, last_x + 2, last_y + 2,
            fill=color, outline=color,
        )
