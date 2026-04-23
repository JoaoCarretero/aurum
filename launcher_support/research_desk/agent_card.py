"""AgentCard widget — renderiza um operativo AI no strip do Research Desk.

Cada card e self-contained: possui seu frame, seu agente canonico, sua
paleta, e expoe `update(view)` pra atualizar dados dinamicos sem rebuild.

Arquitetura:
  - build() roda 1x; cria widgets e armazena refs
  - update(view) configura labels existentes — idempotente, thread-safe
    desde que chamado da main loop Tk
  - action callbacks (assign/configure/history) sao injetados via
    construtor; card nao conhece Screen — so dispatcha eventos

Sprint 1 aplica paleta ametista/onix/cobre/prata como accent stripe e
titulo. Sprint 2 substitui o sigil placeholder (1a letra) por SVG real.
"""
from __future__ import annotations

import tkinter as tk
from typing import Callable

from core.ui.ui_palette import (
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
from launcher_support.research_desk.agent_view import AgentView, offline_view
from launcher_support.research_desk.agents import AgentIdentity
from launcher_support.research_desk.palette import AgentPalette
from launcher_support.research_desk.sigils import SigilCanvas
from launcher_support.research_desk.typography import agent_font


# Mapa status -> cor do badge de status
_STATUS_COLORS: dict[str, str] = {
    "running": GREEN,
    "idle": DIM,
    "paused": HAZARD,
    "error": RED,
    "offline": DIM2,
}


class AgentCard:
    """Widget de card de agente. Nao herda — composicao sobre tk.Frame."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        agent: AgentIdentity,
        palette: AgentPalette,
        on_assign: Callable[[AgentIdentity], None] | None = None,
        on_configure: Callable[[AgentIdentity], None] | None = None,
        on_history: Callable[[AgentIdentity], None] | None = None,
    ):
        self.agent = agent
        self.palette = palette
        self._on_assign = on_assign
        self._on_configure = on_configure
        self._on_history = on_history

        # Widget refs (populados em build())
        self.frame: tk.Frame = tk.Frame(
            parent, bg=PANEL,
            highlightbackground=BORDER, highlightthickness=1,
        )
        self._status_label: tk.Label | None = None
        self._budget_label: tk.Label | None = None
        self._ticket_label: tk.Label | None = None
        self._age_label: tk.Label | None = None

        self.build()
        # Inicializa com view offline — o Screen sobrepoe apos primeiro fetch
        self.update(offline_view())

    # ── Build ─────────────────────────────────────────────────────

    def build(self) -> None:
        # Left accent stripe (cor do agente)
        accent = tk.Frame(self.frame, bg=self.palette.primary, width=3)
        accent.pack(side="left", fill="y")

        body = tk.Frame(self.frame, bg=PANEL)
        body.pack(side="left", fill="both", expand=True, padx=10, pady=8)

        # Sigil alquimico desenhado em Canvas + key name com tipografia
        # distintiva do agente (Sprint 2).
        header = tk.Frame(body, bg=PANEL)
        header.pack(fill="x")
        sigil = SigilCanvas(header, self.agent.key, size=40, bg=PANEL)
        sigil.pack(side="left", padx=(0, 6))
        tk.Label(
            header, text=self.agent.key,
            font=agent_font(self.agent.key, size=11, weight="bold"),
            fg=self.palette.primary, bg=PANEL, anchor="w",
        ).pack(side="left", pady=(4, 0))

        # Status pill no canto direito do header
        self._status_label = tk.Label(
            header, text=" idle ",
            font=(FONT, 7, "bold"),
            fg=PANEL, bg=DIM, padx=5, pady=1,
        )
        self._status_label.pack(side="right")

        tk.Label(
            body, text=self.agent.role,
            font=(FONT, 8), fg=WHITE, bg=PANEL, anchor="w",
        ).pack(anchor="w", pady=(2, 0))
        tk.Label(
            body, text=f"{self.agent.archetype} · {self.agent.stone}",
            font=(FONT, 7), fg=DIM, bg=PANEL, anchor="w",
        ).pack(anchor="w")

        tk.Frame(body, bg=DIM2, height=1).pack(fill="x", pady=(6, 4))

        # Budget row
        budget_row = tk.Frame(body, bg=PANEL)
        budget_row.pack(fill="x")
        tk.Label(
            budget_row, text="budget",
            font=(FONT, 7), fg=DIM, bg=PANEL, width=10, anchor="w",
        ).pack(side="left")
        self._budget_label = tk.Label(
            budget_row, text="—",
            font=(FONT, 7), fg=WHITE, bg=PANEL, anchor="w",
        )
        self._budget_label.pack(side="left")

        # Last ticket
        ticket_row = tk.Frame(body, bg=PANEL)
        ticket_row.pack(fill="x")
        tk.Label(
            ticket_row, text="ticket",
            font=(FONT, 7), fg=DIM, bg=PANEL, width=10, anchor="w",
        ).pack(side="left")
        self._ticket_label = tk.Label(
            ticket_row, text="—",
            font=(FONT, 7), fg=WHITE, bg=PANEL, anchor="w",
            wraplength=180, justify="left",
        )
        self._ticket_label.pack(side="left", fill="x", expand=True)

        age_row = tk.Frame(body, bg=PANEL)
        age_row.pack(fill="x")
        tk.Label(
            age_row, text="idade",
            font=(FONT, 7), fg=DIM, bg=PANEL, width=10, anchor="w",
        ).pack(side="left")
        self._age_label = tk.Label(
            age_row, text="—",
            font=(FONT, 7), fg=DIM, bg=PANEL, anchor="w",
        )
        self._age_label.pack(side="left")

        # Action buttons footer
        tk.Frame(body, bg=DIM2, height=1).pack(fill="x", pady=(6, 4))
        actions = tk.Frame(body, bg=PANEL)
        actions.pack(fill="x")
        for label, handler in (
            ("ATRIBUIR", self._invoke_assign),
            ("CONFIG", self._invoke_configure),
            ("HIST", self._invoke_history),
        ):
            btn = tk.Label(
                actions, text=label,
                font=(FONT, 7, "bold"),
                fg=self.palette.primary, bg=PANEL,
                cursor="hand2", padx=4, pady=1,
            )
            btn.pack(side="left", padx=(0, 8))
            btn.bind("<Button-1>", lambda _e, h=handler: h())
            btn.bind("<Enter>", lambda _e, b=btn: b.configure(fg=WHITE))
            btn.bind("<Leave>", lambda _e, b=btn, p=self.palette: b.configure(fg=p.primary))

    # ── Update (idempotente) ──────────────────────────────────────

    def update(self, view: AgentView) -> None:
        """Refresca labels com o view-model. No-op se widgets destroyed."""
        if self._status_label is not None:
            color = _STATUS_COLORS.get(view.status_color_key, DIM)
            self._status_label.configure(
                text=f" {view.status_text} ",
                bg=color,
                fg=PANEL,
            )
        if self._budget_label is not None:
            self._budget_label.configure(text=view.budget_text)
        if self._ticket_label is not None:
            self._ticket_label.configure(text=view.last_ticket)
        if self._age_label is not None:
            self._age_label.configure(text=view.last_ticket_age)

    # ── Layout passthrough ────────────────────────────────────────

    def grid(self, **opts: object) -> None:
        self.frame.grid(**opts)

    def pack(self, **opts: object) -> None:
        self.frame.pack(**opts)

    # ── Action dispatch ───────────────────────────────────────────

    def _invoke_assign(self) -> None:
        if self._on_assign is not None:
            self._on_assign(self.agent)

    def _invoke_configure(self) -> None:
        if self._on_configure is not None:
            self._on_configure(self.agent)

    def _invoke_history(self) -> None:
        if self._on_history is not None:
            self._on_history(self.agent)
