"""AgentDetailModal — view expandido de um operativo.

Toplevel window com:
  - Sigil grande (size=128) no topo
  - Nome em tipografia distintiva do agente
  - Titulo (role) + archetype + pedra
  - Tagline
  - Statblock (tickets done/active, artifacts, cost, birthday)
  - Recent work grid (ate 5 artefatos recentes clicaveis)

Click em artefato abre markdown_viewer Toplevel. ESC fecha.
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
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
    PANEL,
    WHITE,
)
from launcher_support.research_desk.agent_stats import (
    StatsView,
    ensure_path,
    filter_artifacts_for,
    filter_issues_for,
    agent_dict_for,
    shape_stats,
)
from launcher_support.research_desk.agents import AgentIdentity
from launcher_support.research_desk.artifact_scanner import (
    ArtifactEntry,
    relative_age,
    scan_artifacts,
)
from launcher_support.research_desk.artifacts_panel import open_markdown_viewer
from launcher_support.research_desk.palette import AGENT_COLORS
from launcher_support.research_desk.sigils import SigilCanvas
from launcher_support.research_desk.typography import agent_font


def open_agent_detail(
    parent: tk.Misc,
    *,
    agent: AgentIdentity,
    root_path: Path | str,
    agents_raw: list[dict],
    issues_raw: list[dict],
    on_assign: Callable[[AgentIdentity], None] | None = None,
) -> None:
    """Abre o modal de detalhe. Scaneia artefatos localmente pro agent.

    agents_raw + issues_raw sao snapshots do poll atual do Screen (nao
    refaz HTTP aqui pra evitar lag). Artefatos sao resultado de um scan
    fresh — e rapido o suficiente pra rodar no open.
    """
    root_path = ensure_path(root_path)
    artifacts_all = scan_artifacts(root_path, limit=200)
    artifacts_agent = filter_artifacts_for(agent, artifacts_all)
    issues_agent = filter_issues_for(agent, issues_raw)
    agent_dict = agent_dict_for(agent, agents_raw)

    stats = shape_stats(
        agent=agent,
        agent_dict=agent_dict,
        issues=issues_raw,  # passa todos — shape filtra por uuid
        artifacts=artifacts_agent,
    )

    AgentDetailModal(
        parent,
        agent=agent,
        stats=stats,
        artifacts=artifacts_agent[:5],
        root_path=root_path,
        on_assign=on_assign,
    )


class AgentDetailModal:
    def __init__(
        self,
        parent: tk.Misc,
        *,
        agent: AgentIdentity,
        stats: StatsView,
        artifacts: list[ArtifactEntry],
        root_path: Path,
        on_assign: Callable[[AgentIdentity], None] | None,
    ):
        self.agent = agent
        self.palette = AGENT_COLORS[agent.key]
        self.root_path = root_path
        self._on_assign = on_assign

        self.top = tk.Toplevel(parent)
        self.top.title(f"{agent.key} — {agent.role}")
        self.top.configure(bg=BG)
        self.top.geometry("640x620")
        self.top.transient(parent)

        self._build(stats, artifacts)
        self.top.bind("<Escape>", lambda _e: self.top.destroy())
        self.top.focus_set()

    def _build(self, stats: StatsView, artifacts: list[ArtifactEntry]) -> None:
        wrap = tk.Frame(self.top, bg=BG, padx=20, pady=16)
        wrap.pack(fill="both", expand=True)

        self._build_hero(wrap)
        tk.Frame(wrap, bg=DIM, height=1).pack(fill="x", pady=(10, 0))
        self._build_statblock(wrap, stats)
        tk.Frame(wrap, bg=DIM, height=1).pack(fill="x", pady=(10, 0))
        self._build_recent_work(wrap, artifacts)
        self._build_actions(wrap)

    # ── Hero (sigil + nome + tagline) ─────────────────────────────

    def _build_hero(self, parent: tk.Frame) -> None:
        hero = tk.Frame(parent, bg=BG)
        hero.pack(fill="x", pady=(0, 6))

        sigil = SigilCanvas(hero, self.agent.key, size=96, bg=BG)
        sigil.pack(side="left", padx=(0, 16))

        meta = tk.Frame(hero, bg=BG)
        meta.pack(side="left", fill="both", expand=True)

        tk.Label(
            meta, text=self.agent.key,
            font=agent_font(self.agent.key, size=22, weight="bold"),
            fg=self.palette.primary, bg=BG, anchor="w",
        ).pack(anchor="w")
        tk.Label(
            meta, text=self.agent.role,
            font=agent_font(self.agent.key, size=11),
            fg=WHITE, bg=BG, anchor="w",
        ).pack(anchor="w", pady=(2, 0))
        tk.Label(
            meta, text=f"{self.agent.archetype}  ·  {self.agent.stone}",
            font=(FONT, 8), fg=DIM, bg=BG, anchor="w",
        ).pack(anchor="w", pady=(4, 0))
        tk.Label(
            meta, text=self.agent.tagline,
            font=(FONT, 8, "italic"), fg=DIM2, bg=BG, anchor="w",
        ).pack(anchor="w", pady=(8, 0))

    # ── Statblock ────────────────────────────────────────────────

    def _build_statblock(self, parent: tk.Frame, stats: StatsView) -> None:
        section = tk.Frame(parent, bg=BG)
        section.pack(fill="x", pady=(10, 0))

        tk.Label(
            section, text="STATS",
            font=(FONT, 8, "bold"), fg=AMBER_D, bg=BG, anchor="w",
        ).pack(anchor="w")

        grid = tk.Frame(section, bg=BG)
        grid.pack(fill="x", pady=(6, 0))
        for col in range(2):
            grid.grid_columnconfigure(col, weight=1, uniform="stats_col")

        self._stat_row(grid, 0, 0, "tickets done", str(stats.tickets_done))
        self._stat_row(grid, 0, 1, "tickets active", str(stats.tickets_active))
        self._stat_row(grid, 1, 0,
                       stats.artifact_kind_label, str(stats.artifacts_total))
        self._stat_row(grid, 1, 1, "days active", stats.days_active)
        self._stat_row(grid, 2, 0, "birthday", stats.birthday)
        self._stat_row(
            grid, 2, 1, "monthly",
            f"{stats.monthly_spent} / {stats.monthly_cap}",
        )

        # Budget bar
        bar_wrap = tk.Frame(section, bg=BG)
        bar_wrap.pack(fill="x", pady=(10, 0))
        tk.Label(
            bar_wrap, text="budget usage",
            font=(FONT, 7), fg=DIM, bg=BG, anchor="w", width=14,
        ).pack(side="left")
        track = tk.Frame(
            bar_wrap, bg=BG2, height=8, width=200,
            highlightbackground=BORDER, highlightthickness=1,
        )
        track.pack(side="left", fill="x", expand=True, padx=(0, 6))
        track.pack_propagate(False)
        fill_color = (
            GREEN if stats.monthly_pct < 0.6
            else self.palette.primary if stats.monthly_pct < 0.8
            else AMBER
        )
        if stats.monthly_pct > 0:
            fill = tk.Frame(track, bg=fill_color, height=6)
            fill.place(relwidth=stats.monthly_pct, relheight=1.0)
        tk.Label(
            bar_wrap, text=f"{int(stats.monthly_pct * 100)}%",
            font=(FONT, 7), fg=DIM, bg=BG, anchor="e", width=5,
        ).pack(side="left")

    def _stat_row(
        self, parent: tk.Frame, row: int, col: int,
        key: str, value: str,
    ) -> None:
        cell = tk.Frame(parent, bg=BG)
        cell.grid(row=row, column=col, sticky="ew", pady=1, padx=(0, 10))
        tk.Label(
            cell, text=key,
            font=(FONT, 7), fg=DIM, bg=BG, anchor="w", width=16,
        ).pack(side="left")
        tk.Label(
            cell, text=value,
            font=agent_font(self.agent.key, size=9, weight="bold"),
            fg=WHITE, bg=BG, anchor="w",
        ).pack(side="left")

    # ── Recent work ──────────────────────────────────────────────

    def _build_recent_work(
        self, parent: tk.Frame, artifacts: list[ArtifactEntry],
    ) -> None:
        section = tk.Frame(parent, bg=BG)
        section.pack(fill="both", expand=True, pady=(10, 0))

        tk.Label(
            section, text="RECENT WORK",
            font=(FONT, 8, "bold"), fg=AMBER_D, bg=BG, anchor="w",
        ).pack(anchor="w")

        body = tk.Frame(section, bg=BG)
        body.pack(fill="both", expand=True, pady=(6, 0))

        if not artifacts:
            tk.Label(
                body, text="sem artefatos registrados ainda.",
                font=(FONT, 8, "italic"), fg=DIM, bg=BG, anchor="w",
            ).pack(anchor="w")
            return

        for entry in artifacts:
            self._render_artifact_row(body, entry)

    def _render_artifact_row(
        self, parent: tk.Frame, entry: ArtifactEntry,
    ) -> None:
        row = tk.Frame(parent, bg=BG, cursor="hand2")
        row.pack(fill="x", pady=2)
        tk.Frame(row, bg=self.palette.primary, width=2).pack(side="left", fill="y")
        content = tk.Frame(row, bg=BG)
        content.pack(side="left", fill="x", expand=True, padx=(6, 0))

        title_row = tk.Frame(content, bg=BG)
        title_row.pack(fill="x")
        tk.Label(
            title_row, text=entry.kind.upper(),
            font=(FONT, 7, "bold"), fg=self.palette.primary, bg=BG, width=8,
            anchor="w",
        ).pack(side="left")
        tk.Label(
            title_row, text=entry.title[:80],
            font=(FONT, 8), fg=WHITE, bg=BG, anchor="w",
        ).pack(side="left", fill="x", expand=True)
        tk.Label(
            title_row, text=relative_age(entry),
            font=(FONT, 7), fg=DIM, bg=BG, anchor="e",
        ).pack(side="right")

        def _on_click(_e: tk.Event, e: ArtifactEntry = entry) -> None:
            open_markdown_viewer(
                self.top, root_path=self.root_path, entry=e,
            )

        row.bind("<Button-1>", _on_click)
        for child in (content, title_row):
            child.bind("<Button-1>", _on_click)
        for leaf in title_row.winfo_children():
            if isinstance(leaf, tk.Label):
                leaf.bind("<Button-1>", _on_click)

    # ── Actions ───────────────────────────────────────────────────

    def _build_actions(self, parent: tk.Frame) -> None:
        actions = tk.Frame(parent, bg=BG)
        actions.pack(fill="x", pady=(12, 0))

        assign_btn = tk.Label(
            actions, text=f"  ATRIBUIR TICKET A {self.agent.key}  ",
            font=(FONT, 8, "bold"),
            fg=BG, bg=self.palette.primary, cursor="hand2",
            padx=8, pady=4,
        )
        assign_btn.pack(side="left")
        assign_btn.bind("<Button-1>", lambda _e: self._invoke_assign())

        close_btn = tk.Label(
            actions, text="  FECHAR  ",
            font=(FONT, 8),
            fg=DIM, bg=BG3, cursor="hand2",
            padx=8, pady=4,
        )
        close_btn.pack(side="right")
        close_btn.bind("<Button-1>", lambda _e: self.top.destroy())

    def _invoke_assign(self) -> None:
        if self._on_assign is not None:
            self.top.destroy()
            self._on_assign(self.agent)
