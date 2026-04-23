"""Research Desk screen — gerencia 4 operativos AI via Paperclip API.

Esta Screen e o hub Bloomberg-terminal da mesa de pesquisa. No Sprint 1
(scaffold base) ela renderiza:

  - header com titulo + indicador paperclip (stub OFFLINE por enquanto)
  - grid de 4 cards placeholder (sigil + nome + tagline)
  - painel ACTIVE PIPELINE (placeholder)
  - painel RECENT ARTIFACTS (placeholder)

Itens 1.2-1.7 do Sprint 1 populam cada panel com dados reais. Itens 2.x
(Sprint 2) substituem os placeholders de sigil por SVG generativo e
aplicam tipografia distinta por agente. Itens 3.x (Sprint 3) adicionam
live log streaming, editor AGENTS.md, stats SQLite.

Padrao: espelha DeployPipelineScreen (single screen + _refresh + split
panel via grid). Lifecycle automatico via base.Screen — _after/_bind
sao canceladas em on_exit.
"""
from __future__ import annotations

import tkinter as tk
from typing import Any

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
    PANEL,
    WHITE,
)
from launcher_support.research_desk import strings as s
from launcher_support.research_desk.agents import AGENTS, AgentIdentity
from launcher_support.research_desk.palette import AGENT_COLORS
from launcher_support.screens.base import Screen


class ResearchDeskScreen(Screen):
    def __init__(self, parent: tk.Misc, app: Any):
        super().__init__(parent)
        self.app = app
        # Referencias de widgets preenchidas em build()
        self._subtitle_label: tk.Label | None = None
        self._state_label: tk.Label | None = None
        self._agent_card_frames: dict[str, tk.Frame] = {}
        self._pipeline_body: tk.Frame | None = None
        self._artifacts_body: tk.Frame | None = None

    # ── Build ─────────────────────────────────────────────────────

    def build(self) -> None:
        outer = tk.Frame(self.container, bg=BG)
        outer.pack(fill="both", expand=True, padx=20, pady=14)

        self._build_header(outer)
        self._build_content(outer)

    def _build_header(self, parent: tk.Frame) -> None:
        head = tk.Frame(parent, bg=BG)
        head.pack(fill="x", pady=(0, 12))

        strip = tk.Frame(head, bg=BG)
        strip.pack(fill="x")
        tk.Frame(strip, bg=AMBER, width=4, height=28).pack(side="left", padx=(0, 8))

        title_wrap = tk.Frame(strip, bg=BG)
        title_wrap.pack(side="left", fill="x", expand=True)
        tk.Label(
            title_wrap, text=s.TITLE, font=(FONT, 14, "bold"),
            fg=AMBER, bg=BG, anchor="w",
        ).pack(anchor="w")
        self._subtitle_label = tk.Label(
            title_wrap, text="", font=(FONT, 8),
            fg=DIM, bg=BG, anchor="w",
        )
        self._subtitle_label.pack(anchor="w", pady=(3, 0))

        # Paperclip state pill (OFFLINE default — Task 1.2 polling real state)
        pill = tk.Frame(strip, bg=BG)
        pill.pack(side="right", padx=(12, 0))
        tk.Label(
            pill, text="paperclip", font=(FONT, 7),
            fg=DIM, bg=BG, anchor="e",
        ).pack(side="left", padx=(0, 6))
        self._state_label = tk.Label(
            pill, text=f" {s.STATE_OFFLINE} ",
            font=(FONT, 7, "bold"),
            fg=BG, bg=DIM, padx=6, pady=2,
        )
        self._state_label.pack(side="left")

        tk.Frame(parent, bg=BG2, height=6).pack(fill="x")
        tk.Frame(parent, bg=DIM, height=1).pack(fill="x", pady=(0, 12))

    def _build_content(self, parent: tk.Frame) -> None:
        content = tk.Frame(parent, bg=BG)
        content.pack(fill="both", expand=True)

        # Grid: top row = 4 agent cards, bottom row = pipeline | artifacts
        content.grid_columnconfigure(0, weight=1, uniform="rd_col")
        content.grid_columnconfigure(1, weight=1, uniform="rd_col")
        content.grid_rowconfigure(0, weight=0)  # cards fixos
        content.grid_rowconfigure(1, weight=1)  # painéis crescem

        self._build_agents_strip(content)
        self._build_pipeline_panel(content)
        self._build_artifacts_panel(content)

    def _build_agents_strip(self, parent: tk.Frame) -> None:
        strip = tk.Frame(parent, bg=BG)
        strip.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        for i in range(len(AGENTS)):
            strip.grid_columnconfigure(i, weight=1, uniform="rd_agent")

        for i, agent in enumerate(AGENTS):
            card = self._build_agent_card(strip, agent)
            card.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 6, 0))
            self._agent_card_frames[agent.key] = card

    def _build_agent_card(self, parent: tk.Frame, agent: AgentIdentity) -> tk.Frame:
        palette = AGENT_COLORS[agent.key]
        card = tk.Frame(
            parent, bg=PANEL,
            highlightbackground=BORDER, highlightthickness=1,
        )

        # Left accent stripe (per-agent color)
        accent = tk.Frame(card, bg=palette.primary, width=3)
        accent.pack(side="left", fill="y")

        body = tk.Frame(card, bg=PANEL)
        body.pack(side="left", fill="both", expand=True, padx=10, pady=8)

        # Sigil placeholder (Sprint 2 substitui por SVG). Usa primeira
        # letra do key stylizada na cor do agente.
        sigil_frame = tk.Frame(body, bg=PANEL)
        sigil_frame.pack(anchor="w")
        tk.Label(
            sigil_frame, text=agent.key[0],
            font=(FONT, 18, "bold"),
            fg=palette.primary, bg=PANEL,
        ).pack(side="left")
        tk.Label(
            sigil_frame, text=f"  {agent.key}",
            font=(FONT, 10, "bold"),
            fg=palette.primary, bg=PANEL, anchor="w",
        ).pack(side="left")

        tk.Label(
            body, text=agent.role,
            font=(FONT, 8), fg=WHITE, bg=PANEL, anchor="w",
        ).pack(anchor="w", pady=(2, 0))
        tk.Label(
            body, text=f"{agent.archetype} · {agent.stone}",
            font=(FONT, 7), fg=DIM, bg=PANEL, anchor="w",
        ).pack(anchor="w")

        tk.Frame(body, bg=DIM2, height=1).pack(fill="x", pady=(6, 4))

        # Placeholders de stats (Task 1.3 popula com dados reais)
        stat_row = tk.Frame(body, bg=PANEL)
        stat_row.pack(fill="x")
        tk.Label(
            stat_row, text="status",
            font=(FONT, 7), fg=DIM, bg=PANEL, width=10, anchor="w",
        ).pack(side="left")
        tk.Label(
            stat_row, text="-",
            font=(FONT, 7), fg=WHITE, bg=PANEL, anchor="w",
        ).pack(side="left")

        cost_row = tk.Frame(body, bg=PANEL)
        cost_row.pack(fill="x")
        tk.Label(
            cost_row, text="budget",
            font=(FONT, 7), fg=DIM, bg=PANEL, width=10, anchor="w",
        ).pack(side="left")
        tk.Label(
            cost_row, text="-",
            font=(FONT, 7), fg=WHITE, bg=PANEL, anchor="w",
        ).pack(side="left")

        return card

    def _build_pipeline_panel(self, parent: tk.Frame) -> None:
        frame = tk.Frame(
            parent, bg=PANEL,
            highlightbackground=BORDER, highlightthickness=1,
        )
        frame.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        tk.Label(
            frame, text=s.PANEL_PIPELINE,
            font=(FONT, 8, "bold"), fg=AMBER_D, bg=PANEL, anchor="w",
        ).pack(anchor="nw", padx=10, pady=(10, 4))
        tk.Frame(frame, bg=DIM2, height=1).pack(fill="x", padx=10, pady=(0, 6))

        body = tk.Frame(frame, bg=PANEL)
        body.pack(fill="both", expand=True, padx=10, pady=(2, 10))
        self._pipeline_body = body
        tk.Label(
            body, text=s.EMPTY_PIPELINE,
            font=(FONT, 8), fg=DIM, bg=PANEL, anchor="w",
        ).pack(anchor="w")

    def _build_artifacts_panel(self, parent: tk.Frame) -> None:
        frame = tk.Frame(
            parent, bg=PANEL,
            highlightbackground=BORDER, highlightthickness=1,
        )
        frame.grid(row=1, column=1, sticky="nsew")
        tk.Label(
            frame, text=s.PANEL_ARTIFACTS,
            font=(FONT, 8, "bold"), fg=AMBER_D, bg=PANEL, anchor="w",
        ).pack(anchor="nw", padx=10, pady=(10, 4))
        tk.Frame(frame, bg=DIM2, height=1).pack(fill="x", padx=10, pady=(0, 6))

        body = tk.Frame(frame, bg=PANEL)
        body.pack(fill="both", expand=True, padx=10, pady=(2, 10))
        self._artifacts_body = body
        tk.Label(
            body, text=s.EMPTY_ARTIFACTS,
            font=(FONT, 8), fg=DIM, bg=PANEL, anchor="w",
        ).pack(anchor="w")

    # ── Lifecycle ─────────────────────────────────────────────────

    def on_enter(self, **kwargs: Any) -> None:
        del kwargs
        app = self.app
        app.h_path.configure(text=s.PATH_LABEL)
        app.h_stat.configure(text=s.STATUS_LABEL, fg=AMBER_D)
        app.f_lbl.configure(text=s.FOOTER_KEYS)

        app._kb("<Escape>", self._back)
        app._kb("<Key-0>", self._back)
        app._bind_global_nav()

        self._refresh_subtitle()

    def _back(self) -> None:
        """Volta pro main menu Bloomberg (desk router)."""
        try:
            self.app._menu_main_bloomberg()
        except Exception:
            pass

    def _refresh_subtitle(self) -> None:
        """Task 1.2 vai plugar state real do paperclip; aqui mantem stub."""
        if self._subtitle_label is None:
            return
        self._subtitle_label.configure(
            text=s.SUBTITLE_FMT.format(
                n=len(AGENTS),
                state=s.STATE_OFFLINE.lower(),
                used="$0.00",
                cap="$0.00",
            )
        )
