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
from pathlib import Path
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
    GREEN,
    HAZARD,
    PANEL,
    RED,
    WHITE,
)
from launcher_support.research_desk import strings as s
from launcher_support.research_desk.agent_card import AgentCard
from launcher_support.research_desk.agent_view import (
    offline_view,
    shape_agents_by_uuid,
)
from launcher_support.research_desk.agents import AGENTS, COMPANY_ID, AgentIdentity
from launcher_support.research_desk.artifact_scanner import (
    ArtifactEntry,
    scan_artifacts,
)
from launcher_support.research_desk.artifacts_panel import (
    ArtifactsPanel,
    open_markdown_viewer,
)
from launcher_support.research_desk.issue_view import IssueView
from launcher_support.research_desk.palette import AGENT_COLORS
from launcher_support.research_desk.paperclip_client import (
    PaperclipClient,
    PaperclipConfig,
    format_usd_from_cents,
    total_budget_cents,
)
from launcher_support.research_desk.paperclip_process import (
    PaperclipProcess,
    ServerStatus,
    default_paperclip_cmd,
)
from launcher_support.research_desk.pipeline_panel import PipelinePanel
from launcher_support.screens.base import Screen

# Polling rhythm — spec says 5s. Health check separately uses shorter
# timeout pra nao bloquear UI quando server ta offline.
_POLL_INTERVAL_MS = 5000
_HEALTH_TIMEOUT_SEC = 1.5


class ResearchDeskScreen(Screen):
    def __init__(self, parent: tk.Misc, app: Any, root_path: Path):
        super().__init__(parent)
        self.app = app
        self.root_path = root_path
        # Referencias de widgets preenchidas em build()
        self._subtitle_label: tk.Label | None = None
        self._state_label: tk.Label | None = None
        self._agent_cards: dict[str, AgentCard] = {}
        self._pipeline_panel: PipelinePanel | None = None
        self._artifacts_panel: ArtifactsPanel | None = None

        # HTTP client do Paperclip — reused across mount/unmount para
        # preservar circuit breaker state + cache em disco.
        self._client = PaperclipClient(
            cfg=PaperclipConfig(timeout_sec=_HEALTH_TIMEOUT_SEC),
        )
        # Process manager — reused across mount/unmount para preservar
        # ownership do subprocess (se o user navega pra outro screen e
        # volta, o paperclip continua rodando).
        self._process = PaperclipProcess(cmd=default_paperclip_cmd())
        # Ultimo estado conhecido, pra o label piscar somente em mudanca
        # real (evita redraw desnecessario a cada tick).
        self._last_online: bool | None = None
        self._last_budget: tuple[int, int] = (0, 0)
        # Widgets do toggle paperclip
        self._action_btn: tk.Label | None = None

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

        # Paperclip state pill + action button (start/stop)
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

        self._action_btn = tk.Label(
            pill, text=f"  {s.BTN_START_PAPERCLIP}  ",
            font=(FONT, 7, "bold"),
            fg=BG, bg=GREEN, cursor="hand2", padx=4, pady=2,
        )
        self._action_btn.pack(side="left", padx=(8, 0))
        self._action_btn.bind("<Button-1>", lambda _e: self._toggle_paperclip())

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
            card = AgentCard(
                strip,
                agent=agent,
                palette=AGENT_COLORS[agent.key],
                on_assign=self._stub_action("assign"),
                on_configure=self._stub_action("configure"),
                on_history=self._stub_action("history"),
            )
            card.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 6, 0))
            self._agent_cards[agent.key] = card

    def _stub_action(self, action: str) -> Any:
        """Retorna handler generico que mostra msg no h_stat.

        Tasks 1.6, 3.2, 3.4 substituem por handlers reais (ticket form,
        AGENTS.md editor, history view).
        """
        def handler(agent: AgentIdentity) -> None:
            try:
                self.app.h_stat.configure(
                    text=f"{agent.key} {action}: em breve",
                    fg=AMBER_D,
                )
                self._after(2000, lambda: self.app.h_stat.configure(
                    text=s.STATUS_LABEL, fg=AMBER_D,
                ))
            except Exception:
                pass
        return handler

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
        self._pipeline_panel = PipelinePanel(
            body,
            on_row_click=self._on_issue_click,
            empty_text=s.EMPTY_PIPELINE,
        )
        self._pipeline_panel.pack(fill="both", expand=True)

    def _on_issue_click(self, view: IssueView) -> None:
        """Stub — Sprint 3.1 vai abrir painel de detalhe com stream."""
        try:
            self.app.h_stat.configure(
                text=f"issue {view.id[:8]}: em breve",
                fg=AMBER_D,
            )
            self._after(2500, lambda: self.app.h_stat.configure(
                text=s.STATUS_LABEL, fg=AMBER_D,
            ))
        except Exception:
            pass

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
        self._artifacts_panel = ArtifactsPanel(
            body,
            on_row_click=self._on_artifact_click,
            empty_text=s.EMPTY_ARTIFACTS,
        )
        self._artifacts_panel.pack(fill="both", expand=True)

    def _on_artifact_click(self, entry: ArtifactEntry) -> None:
        open_markdown_viewer(
            self.container, root_path=self.root_path, entry=entry,
        )

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

        # Primeiro tick imediato pra evitar mostrar OFFLINE por 5s
        # quando o server na verdade esta online.
        self._poll_state()

    def _back(self) -> None:
        """Volta pro main menu Bloomberg (desk router)."""
        try:
            self.app._menu_main_bloomberg()
        except Exception:
            pass

    # ── Paperclip polling ─────────────────────────────────────────

    def _poll_state(self) -> None:
        """Bate no /api/health, agrega budgets se online, e reagenda."""
        online = self._client.is_online()
        # Sync process status machine com health observado
        if online:
            self._process.mark_online()
        else:
            self._process.mark_offline()

        used_cents, cap_cents = 0, 0
        agents_raw: list[dict] = []
        issues_raw: list[dict] = []
        if online:
            agents_raw = self._client.list_agents_cached(COMPANY_ID)
            issues_raw = self._client.list_issues_cached(COMPANY_ID)
            used_cents, cap_cents = total_budget_cents(agents_raw)

        self._apply_state(online=online, used=used_cents, cap=cap_cents)
        self._apply_agent_cards(agents_raw, online=online)
        self._apply_pipeline(issues_raw, online=online)
        self._apply_artifacts()
        # Reagenda via helper da base — cancelado automaticamente em on_exit
        self._after(_POLL_INTERVAL_MS, self._poll_state)

    def _apply_artifacts(self) -> None:
        if self._artifacts_panel is None:
            return
        try:
            entries = scan_artifacts(self.root_path, limit=30)
        except Exception:
            entries = []
        self._artifacts_panel.update(entries)

    def _apply_pipeline(self, issues_raw: list[dict], *, online: bool) -> None:
        if self._pipeline_panel is None:
            return
        if not online:
            self._pipeline_panel.show_offline(s.OFFLINE_BANNER)
            return
        self._pipeline_panel.update(issues_raw)

    def _apply_agent_cards(self, agents_raw: list[dict], *, online: bool) -> None:
        """Distribui dados de /api/companies/:id/agents nos cards por UUID.

        Se offline, todos os cards mostram offline_view. Se online e UUID
        nao retornou do Paperclip, aquele card tambem cai pra offline_view
        (agente registrado mas nao existe mais no server).
        """
        if not online:
            for card in self._agent_cards.values():
                card.update(offline_view())
            return

        by_uuid = shape_agents_by_uuid(agents_raw)
        for key, card in self._agent_cards.items():
            view = by_uuid.get(card.agent.uuid)
            card.update(view if view is not None else offline_view())

    def _apply_state(self, *, online: bool, used: int, cap: int) -> None:
        """Atualiza pill + subtitle + action btn. No-op se widgets destroyed."""
        status = self._process.status

        # Pill reflete health real + ownership
        if self._state_label is not None:
            pill_text, pill_fg, pill_bg = _pill_style_for(status, online)
            self._state_label.configure(text=pill_text, fg=pill_fg, bg=pill_bg)

        # Action button (start/stop/external)
        if self._action_btn is not None:
            self._update_action_button(status)

        # Subtitle com counts + budget agregado
        if self._subtitle_label is not None:
            self._subtitle_label.configure(
                text=s.SUBTITLE_FMT.format(
                    n=len(AGENTS),
                    state=status.value,
                    used=format_usd_from_cents(used),
                    cap=format_usd_from_cents(cap),
                )
            )

        self._last_online = online
        self._last_budget = (used, cap)

    def _update_action_button(self, status: ServerStatus) -> None:
        assert self._action_btn is not None
        if status == ServerStatus.EXTERNAL:
            self._action_btn.configure(
                text="  EXTERNO  ",
                fg=DIM, bg=BG3, cursor="arrow",
            )
        elif status == ServerStatus.STARTING:
            self._action_btn.configure(
                text="  INICIANDO...  ",
                fg=BG, bg=HAZARD, cursor="arrow",
            )
        elif status == ServerStatus.STOPPING:
            self._action_btn.configure(
                text="  PARANDO...  ",
                fg=BG, bg=HAZARD, cursor="arrow",
            )
        elif self._process.is_owned():
            self._action_btn.configure(
                text=f"  {s.BTN_STOP_PAPERCLIP}  ",
                fg=WHITE, bg=RED, cursor="hand2",
            )
        else:
            self._action_btn.configure(
                text=f"  {s.BTN_START_PAPERCLIP}  ",
                fg=BG, bg=GREEN, cursor="hand2",
            )

    def _toggle_paperclip(self) -> None:
        """Clique no action btn: decide start/stop pelo status atual."""
        status = self._process.status
        if status == ServerStatus.EXTERNAL or status in (
            ServerStatus.STARTING, ServerStatus.STOPPING,
        ):
            return  # botao desabilitado nesses estados
        if self._process.is_owned():
            ok, msg = self._process.stop(wait_sec=5.0)
        else:
            ok, msg = self._process.start()
        self._flash_feedback(ok=ok, msg=msg)
        # Repoll agora pra refletir transicao imediatamente
        self._after(100, self._poll_state)

    def _flash_feedback(self, *, ok: bool, msg: str) -> None:
        """Mostra feedback breve no status do launcher."""
        app = self.app
        try:
            app.h_stat.configure(
                text=f"paperclip: {msg}",
                fg=AMBER if ok else RED,
            )
            # Restaura DESK label depois de 2.5s
            self._after(2500, lambda: app.h_stat.configure(
                text=s.STATUS_LABEL, fg=AMBER_D,
            ))
        except Exception:
            pass


def _pill_style_for(status: ServerStatus, online: bool) -> tuple[str, str, str]:
    """(text, fg, bg) pra pill dado status do processo + health observado."""
    if status == ServerStatus.STARTING:
        return f" {s.STATE_STARTING} ", BG, HAZARD
    if status == ServerStatus.EXTERNAL:
        # online confirmado mas spawned fora — marca distinto do owned.
        return f" {s.STATE_ONLINE} ", BG, AMBER
    if online:
        return f" {s.STATE_ONLINE} ", BG, GREEN
    return f" {s.STATE_OFFLINE} ", WHITE, RED
