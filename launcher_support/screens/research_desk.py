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

import logging
import tkinter as tk
from pathlib import Path
from typing import Any


def _research_desk_logger() -> logging.Logger:
    log = logging.getLogger("aurum.research_desk")
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    log_dir = Path("data/.paperclip_cache")
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    try:
        h = logging.FileHandler(log_dir / "research_desk.log", mode="a", encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(h)
    except OSError:
        pass
    return log


_LOG = _research_desk_logger()

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
from launcher_support.research_desk.activity_events import (
    ActivityEvent,
    merge_events,
)
from launcher_support.research_desk.activity_feed import ActivityFeed
from launcher_support.research_desk.agent_card import AgentCard
from launcher_support.research_desk.agent_detail import open_agent_detail
from launcher_support.research_desk.cost_dashboard import open_cost_dashboard
from launcher_support.research_desk.cost_summary import shape_cost_summary
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
from launcher_support.research_desk.markdown_editor import (
    open_markdown_editor,
    persona_path,
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
from launcher_support.research_desk.issue_detail import open_issue_detail
from launcher_support.research_desk.pipeline_panel import PipelinePanel
from launcher_support.research_desk import stats_db
from launcher_support.research_desk.ticket_form import (
    NewTicketModal,
    TicketDraft,
    draft_to_api_payload,
)
from launcher_support.screens.base import Screen

# Polling rhythm — spec says 5s. Health check separately uses shorter
# timeout pra nao bloquear UI quando server ta offline.
_POLL_INTERVAL_MS = 5000
_HEALTH_TIMEOUT_SEC = 1.5


def _count_tickets_for(agent_uuid: str, issues_raw: list[dict]) -> tuple[int, int]:
    """Retorna (tickets_done, tickets_active) atribuidos a um agente."""
    done = active = 0
    for issue in issues_raw:
        assignee = (issue.get("assigned_agent_id")
                    or issue.get("assignee_id")
                    or issue.get("agent_id") or "")
        if assignee != agent_uuid:
            continue
        status = (issue.get("status") or "").lower()
        if status in ("done", "closed", "completed"):
            done += 1
        elif status in ("todo", "in_progress", "review"):
            active += 1
    return done, active


def _on_configure_click_pure(parent, agent, root_path) -> None:
    """Resolve persona + abre editor. Fn pura pra testar sem Tk real."""
    target = persona_path(agent.key, root_path)
    open_markdown_editor(
        parent, path=target,
        title_hint=f"{agent.key} persona · {target.name}",
    )


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
        self._activity_feed: ActivityFeed | None = None

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
        # Snapshot do ultimo poll — consumido pelo detail view sem
        # refazer HTTP na hora do click.
        self._last_agents_raw: list[dict] = []
        self._last_issues_raw: list[dict] = []
        # Stats DB — abre lazy (so quando primeiro snapshot for gravado)
        # pra nao custar fs I/O em screens que so navegam sem mount.
        self._stats_db_conn = None
        self._last_snapshot_date = ""  # detecta rollover de dia
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

        new_ticket_btn = tk.Label(
            pill, text=f"  {s.BTN_NEW_TICKET}  ",
            font=(FONT, 7, "bold"),
            fg=BG, bg=AMBER, cursor="hand2", padx=4, pady=2,
        )
        new_ticket_btn.pack(side="left", padx=(8, 0))
        new_ticket_btn.bind("<Button-1>", lambda _e: self._open_new_ticket())

        alignment_btn = tk.Label(
            pill, text="  ALIGNMENT  ",
            font=(FONT, 7, "bold"),
            fg=BG, bg=GREEN, cursor="hand2", padx=4, pady=2,
        )
        alignment_btn.pack(side="left", padx=(8, 0))
        alignment_btn.bind("<Button-1>", lambda _e: self._open_alignment())

        tk.Frame(parent, bg=BG2, height=6).pack(fill="x")
        tk.Frame(parent, bg=DIM, height=1).pack(fill="x", pady=(0, 12))

    def _build_content(self, parent: tk.Frame) -> None:
        content = tk.Frame(parent, bg=BG)
        content.pack(fill="both", expand=True)

        # Grid: row 0 = cards, row 1 = pipeline | artifacts, row 2 = activity feed
        content.grid_columnconfigure(0, weight=1, uniform="rd_col")
        content.grid_columnconfigure(1, weight=1, uniform="rd_col")
        content.grid_rowconfigure(0, weight=0)  # cards fixos
        content.grid_rowconfigure(1, weight=2)  # pipeline/artifacts grande
        content.grid_rowconfigure(2, weight=1)  # activity feed menor

        self._build_agents_strip(content)
        self._build_pipeline_panel(content)
        self._build_artifacts_panel(content)
        self._build_activity_feed(content)

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
                on_configure=lambda a=agent: self._on_configure_click(a),
                on_history=self._stub_action("history"),
                on_inspect=self._open_agent_detail,
            )
            card.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 6, 0))
            self._agent_cards[agent.key] = card

    def _stub_action(self, action: str) -> Any:
        """Retorna handler generico que mostra msg no h_stat.

        Tasks 3.2 e 3.4 substituem configure/history por handlers reais
        (AGENTS.md editor + history view). Assign ja foi ligado ao
        NewTicketModal abaixo.
        """
        if action == "assign":
            return self._open_new_ticket_for_agent

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

    # ── Ticket flow ───────────────────────────────────────────────

    def _open_new_ticket(self) -> None:
        NewTicketModal(
            self.container,
            submit_callback=self._submit_ticket,
            default_assignee=AGENTS[0],
        )

    def _open_new_ticket_for_agent(self, agent: AgentIdentity) -> None:
        NewTicketModal(
            self.container,
            submit_callback=self._submit_ticket,
            default_assignee=agent,
        )

    def _on_configure_click(self, agent: AgentIdentity) -> None:
        _on_configure_click_pure(self, agent, self.root_path)

    def _open_agent_detail(self, agent: AgentIdentity) -> None:
        """Click no hero area de um card abre o detail modal."""
        open_agent_detail(
            self.container,
            agent=agent,
            root_path=self.root_path,
            agents_raw=self._last_agents_raw,
            issues_raw=self._last_issues_raw,
            on_assign=self._open_new_ticket_for_agent,
            on_toggle_pause=self._toggle_agent_pause,
            fetch_runs=self._fetch_runs_for,
            fetch_ratios=self._fetch_ratios_for,
        )

    def _ensure_stats_db(self):
        """Abre lazy a connection do stats DB. Retorna None se falhar.

        Consolida o padrao de abrir em 3 callers (ratios/cost/snapshots) —
        todos compartilham a mesma conn (main thread) e todos tratam
        ImportError (config.paths ausente) + OSError + sqlite.Error igual.
        """
        if self._stats_db_conn is not None:
            return self._stats_db_conn
        try:
            from config.paths import AURUM_DB_PATH
            self._stats_db_conn = stats_db.connect(AURUM_DB_PATH)
            self._stats_db_error_flashed = False
        except Exception as e:
            self._stats_db_conn = None
            if not getattr(self, "_stats_db_error_flashed", False):
                _LOG.warning("stats_db indisponível: %s", e)
                self._flash_feedback(
                    ok=False, msg=f"stats_db: {e.__class__.__name__}",
                )
                self._stats_db_error_flashed = True
        return self._stats_db_conn

    def _fetch_ratios_for(self, agent: AgentIdentity):
        """Query SQLite pra ratios ship/iterate/kill em 30d. None se DB vazio."""
        conn = self._ensure_stats_db()
        if conn is None:
            return None
        try:
            rows = stats_db.list_days(conn, agent.key, days=30)
            return stats_db.compute_ratios(rows)
        except Exception:
            return None

    def _fetch_cost_summary(self):
        """Constroi CostSummary a partir do snapshot atual + historico SQLite."""
        history: dict[str, list] = {}
        conn = self._ensure_stats_db()
        if conn is not None:
            for agent in AGENTS:
                try:
                    history[agent.key] = stats_db.list_days(
                        conn, agent.key, days=30,
                    )
                except Exception:
                    history[agent.key] = []
        return shape_cost_summary(self._last_agents_raw, history)

    def _open_cost_dashboard(self) -> None:
        open_cost_dashboard(
            self.container,
            fetch_summary=self._fetch_cost_summary,
        )

    def _open_alignment(self) -> None:
        """Open the alignment drift modal. Scan is fast (<100ms), runs
        synchronously in the modal constructor."""
        from launcher_support.research_desk.alignment_panel import (
            open_alignment_modal,
        )
        open_alignment_modal(self.container, root_path=self.root_path)

    def _fetch_runs_for(self, agent: AgentIdentity) -> list[dict]:
        """Fetch heartbeat runs pra um agente. Chamado em thread daemon
        pelo modal — nao bloqueia main loop do launcher."""
        try:
            return self._client.list_heartbeat_runs_cached(agent.uuid, limit=20)
        except Exception:
            return []

    def _toggle_agent_pause(
        self, agent: AgentIdentity, was_paused: bool,
    ) -> None:
        """Chama POST /api/agents/:id/pause ou /resume. Re-poll imediato.

        HTTP roda em thread daemon — nao bloqueia Tk. Resultado
        aparece no proximo tick (alem do re-poll imediato).
        """
        import threading

        def _run() -> None:
            try:
                if was_paused:
                    self._client.resume_agent(agent.uuid)
                else:
                    self._client.pause_agent(agent.uuid)
            except Exception as e:  # noqa: BLE001
                from launcher_support.research_desk.paperclip_client import CircuitOpen
                if isinstance(e, CircuitOpen):
                    try:
                        self.container.after(0, lambda: self._flash_feedback(
                            ok=False, msg="paperclip offline",
                        ))
                    except Exception:
                        pass
                else:
                    _LOG.warning("pause/resume falhou (%s): %s", agent.key, e)
                    _ename = e.__class__.__name__
                    _akey = agent.key
                    try:
                        self.container.after(0, lambda: self._flash_feedback(
                            ok=False, msg=f"pause {_akey}: {_ename}",
                        ))
                    except Exception:
                        pass

        threading.Thread(target=_run, daemon=True).start()
        # Feedback visual imediato + re-poll em 200ms (thread deve completar)
        try:
            verb = "retomando" if was_paused else "pausando"
            self.app.h_stat.configure(
                text=f"{verb} {agent.key}...", fg=AMBER_D,
            )
            self._after(200, self._poll_state)
            self._after(2500, lambda: self.app.h_stat.configure(
                text=s.STATUS_LABEL, fg=AMBER_D,
            ))
        except Exception:
            pass

    def _submit_ticket(self, draft: TicketDraft) -> tuple[bool, str]:
        """POST /api/companies/:id/issues. Retorna (ok, msg) pro modal."""
        if not self._client.is_online():
            return False, "paperclip offline"
        payload = draft_to_api_payload(draft)
        try:
            result = self._client.create_issue(COMPANY_ID, payload)
        except Exception as exc:  # noqa: BLE001
            return False, f"api: {exc}"
        issue_id = result.get("id") if isinstance(result, dict) else None
        # Refresca pipeline imediatamente pra mostrar o novo ticket
        self._after(50, self._poll_state)
        return True, f"id={issue_id or '?'}"

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
        if not view.id:
            return
        open_issue_detail(
            self,
            client=self._client,
            issue_id=view.id,
            on_close=self._refresh_pipeline,
        )

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

    def _build_activity_feed(self, parent: tk.Frame) -> None:
        frame = tk.Frame(
            parent, bg=PANEL,
            highlightbackground=BORDER, highlightthickness=1,
        )
        frame.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(10, 0))
        tk.Label(
            frame, text="ACTIVITY FEED",
            font=(FONT, 8, "bold"), fg=AMBER_D, bg=PANEL, anchor="w",
        ).pack(anchor="nw", padx=10, pady=(10, 4))
        tk.Frame(frame, bg=DIM2, height=1).pack(fill="x", padx=10, pady=(0, 6))

        body = tk.Frame(frame, bg=PANEL)
        body.pack(fill="both", expand=True, padx=10, pady=(2, 10))
        self._activity_feed = ActivityFeed(
            body, on_event_click=self._on_activity_click,
        )
        self._activity_feed.pack(fill="both", expand=True)

    def _on_activity_click(self, event: ActivityEvent) -> None:
        """Navega pro source do evento: artifact -> markdown viewer,
        issue -> IssueDetailModal com polling."""
        payload = event.payload
        if isinstance(payload, ArtifactEntry):
            open_markdown_viewer(
                self.container, root_path=self.root_path, entry=payload,
            )
            return
        # Issue payload — abre modal de detalhe
        if isinstance(payload, dict):
            iid = str(payload.get("id") or "")
            if not iid:
                return
            open_issue_detail(
                self,
                client=self._client,
                issue_id=iid,
                on_close=self._refresh_pipeline,
            )
            return

    def _refresh_pipeline(self) -> None:
        """Re-poll forçado pro pipeline panel após ação de ticket."""
        try:
            self._poll_state()
        except Exception:
            pass

    # ── Lifecycle ─────────────────────────────────────────────────

    def on_enter(self, **kwargs: Any) -> None:
        del kwargs
        app = self.app
        app.h_path.configure(text=s.PATH_LABEL)
        app.h_stat.configure(text=s.STATUS_LABEL, fg=AMBER_D)
        app.f_lbl.configure(text=s.FOOTER_KEYS)

        app._kb("<Escape>", self._back)
        app._kb("<Key-0>", self._back)
        app._kb("<Key-n>", self._open_new_ticket)
        app._kb("<Key-N>", self._open_new_ticket)
        app._kb("<Key-r>", self._poll_state)
        app._kb("<Key-R>", self._poll_state)
        app._kb("<Key-s>", self._toggle_paperclip)
        app._kb("<Key-S>", self._toggle_paperclip)
        app._kb("<Key-c>", self._open_cost_dashboard)
        app._kb("<Key-C>", self._open_cost_dashboard)
        app._kb("<Key-a>", self._open_alignment)
        app._kb("<Key-A>", self._open_alignment)
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
        """Bate no /api/health em thread, aplica UI na main loop, reagenda.

        HTTP roda em background pra nao bloquear Tk durante o timeout
        de 1.5s (ou ate 5s com cache miss + breaker). Callbacks de UI
        voltam via container.after(0, ...).
        """
        import threading

        def _work() -> None:
            from launcher_support.research_desk.paperclip_client import CircuitOpen
            import urllib.error
            try:
                online = self._client.is_online()
                agents_raw: list[dict] = []
                issues_raw: list[dict] = []
                used_cents, cap_cents = 0, 0
                if online:
                    agents_raw = self._client.list_agents_cached(COMPANY_ID)
                    issues_raw = self._client.list_issues_cached(COMPANY_ID)
                    used_cents, cap_cents = total_budget_cents(agents_raw)
            except (CircuitOpen, urllib.error.URLError, TimeoutError):
                online = False
                agents_raw = []
                issues_raw = []
                used_cents = cap_cents = 0
            except Exception as e:  # noqa: BLE001
                online = False
                agents_raw = []
                issues_raw = []
                used_cents = cap_cents = 0
                _LOG.exception("poll_state exception: %s", e)
                _ename = e.__class__.__name__
                try:
                    self.container.after(0, lambda: self._flash_feedback(
                        ok=False, msg=f"poll erro: {_ename}",
                    ))
                except Exception:
                    pass

            # Post resultado pra main thread
            try:
                self.container.after(0, lambda: self._apply_poll_result(
                    online=online, agents_raw=agents_raw,
                    issues_raw=issues_raw,
                    used_cents=used_cents, cap_cents=cap_cents,
                ))
            except Exception:  # container destruido — screen saiu
                pass

        threading.Thread(target=_work, daemon=True).start()
        # Reagenda proximo tick independente do resultado da thread
        self._after(_POLL_INTERVAL_MS, self._poll_state)

    def _apply_poll_result(
        self, *, online: bool, agents_raw: list[dict],
        issues_raw: list[dict], used_cents: int, cap_cents: int,
    ) -> None:
        """Roda na main thread — aplica resultado do poll_state async."""
        if online:
            self._process.mark_online()
        else:
            self._process.mark_offline()

        self._last_agents_raw = agents_raw
        self._last_issues_raw = issues_raw

        self._apply_state(online=online, used=used_cents, cap=cap_cents)
        self._apply_agent_cards(agents_raw, online=online)
        self._apply_pipeline(issues_raw, online=online)
        full_scan = self._apply_artifacts()
        # Snapshot diario — 1x por dia por agente, so quando online (dados reais)
        if online and agents_raw:
            try:
                self._maybe_record_snapshots(
                    agents_raw=agents_raw,
                    issues_raw=issues_raw,
                    artifacts=full_scan,
                )
            except Exception:
                pass  # DB opcional — nao bloqueia UI

    def _apply_artifacts(self) -> list[ArtifactEntry]:
        """Atualiza panels + retorna o scan pra reuso (snapshots)."""
        if self._artifacts_panel is None:
            return []
        # Scan unico por tick. Panel usa os 30 mais recentes; activity
        # feed recebe ate 200 (pagina internamente via LOAD MORE).
        try:
            full_scan = scan_artifacts(self.root_path, limit=200)
        except Exception as e:
            full_scan = getattr(self, "_last_full_scan", [])
            _LOG.warning("scan_artifacts falhou: %s", e)
            if not getattr(self, "_scan_error_flashed", False):
                self._flash_feedback(ok=False, msg="scan artifacts falhou")
                self._scan_error_flashed = True
        else:
            self._last_full_scan = full_scan
            self._scan_error_flashed = False

        try:
            self._artifacts_panel.update(full_scan[:30])
        except Exception as e:
            _LOG.warning("artifacts_panel.update falhou: %s", e)

        if self._activity_feed is not None:
            try:
                events = merge_events(
                    issues=self._last_issues_raw,
                    artifacts=full_scan,
                    limit=200,
                )
                self._activity_feed.update(events)
                self._merge_error_flashed = False
            except Exception as e:
                _LOG.warning("merge_events falhou: %s", e)
                if not getattr(self, "_merge_error_flashed", False):
                    self._flash_feedback(ok=False, msg="activity feed falhou")
                    self._merge_error_flashed = True
        return full_scan

    def _maybe_record_snapshots(
        self, *, agents_raw: list[dict], issues_raw: list[dict],
        artifacts: list[ArtifactEntry],
    ) -> None:
        """Grava snapshot diario por agente no SQLite. Idempotente via
        upsert por (agent_key, date). Skipa se ja gravou hoje neste processo.
        """
        today = stats_db.today_utc()
        if today == self._last_snapshot_date:
            return  # ja gravou hoje neste processo
        conn = self._ensure_stats_db()
        if conn is None:
            return  # DB indisponivel — snapshot nao grava, nao trava UI

        # Indexa por UUID pra resolver agent_dict.paused/spent
        by_uuid = {a.get("id"): a for a in agents_raw if a.get("id")}

        for agent in AGENTS:
            a_dict = by_uuid.get(agent.uuid) or {}
            spent = int(a_dict.get("monthly_spent_cents") or
                        a_dict.get("spent_cents") or 0)
            done, active = _count_tickets_for(agent.uuid, issues_raw)
            arts = sum(1 for a in artifacts if a.agent_key == agent.key)
            stats_db.record_snapshot(
                conn,
                agent_key=agent.key,
                date=today,
                tickets_done=done,
                tickets_active=active,
                artifacts_total=arts,
                spent_cents=spent,
            )
        self._last_snapshot_date = today

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
        """Clique no action btn: decide start/stop pelo status atual.

        start/stop roda em thread daemon — stop() faz proc.wait(5s)
        + possivel kill+wait(2s), total ate 7s bloqueante se fosse
        na main loop.
        """
        import threading

        status = self._process.status
        if status == ServerStatus.EXTERNAL or status in (
            ServerStatus.STARTING, ServerStatus.STOPPING,
        ):
            return  # botao desabilitado nesses estados

        is_stop = self._process.is_owned()

        # Feedback imediato antes da thread disparar
        self._flash_feedback(
            ok=True,
            msg="parando..." if is_stop else "iniciando...",
        )

        def _work() -> None:
            try:
                if is_stop:
                    ok, msg = self._process.stop(wait_sec=5.0)
                else:
                    ok, msg = self._process.start()
            except Exception as exc:  # noqa: BLE001
                ok, msg = False, f"err: {exc}"
            try:
                self.container.after(0, lambda: self._post_toggle(ok, msg))
            except Exception:
                pass

        threading.Thread(target=_work, daemon=True).start()

    def _post_toggle(self, ok: bool, msg: str) -> None:
        """Roda na main thread apos start/stop completar."""
        self._flash_feedback(ok=ok, msg=msg)
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
