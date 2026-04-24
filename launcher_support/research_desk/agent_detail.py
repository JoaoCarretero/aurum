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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

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
from launcher_support.research_desk.live_runs import (
    STATUS_ERROR,
    STATUS_RUNNING,
    STATUS_STALE,
    STATUS_SUCCESS,
    RunView,
    shape_runs,
)
from launcher_support.research_desk.artifact_linking import (
    LinkedChain,
    backtest_command_for,
    chains_for_agent,
    link_artifacts,
)
from launcher_support.research_desk.markdown_editor import (
    open_markdown_editor,
    persona_path,
)
from launcher_support.research_desk.palette import AGENT_COLORS
from launcher_support.research_desk.stats_db import RatiosView
from launcher_support.research_desk.sigils import SigilCanvas
from launcher_support.research_desk.typography import agent_font

# Status -> cor do dot/label no painel LIVE RUNS
_RUN_STATUS_COLOR = {
    STATUS_RUNNING: AMBER,
    STATUS_SUCCESS: GREEN,
    STATUS_ERROR: HAZARD,
    STATUS_STALE: HAZARD,
}

_RUNS_REFRESH_MS = 3000


# ── Builder handles dataclass ─────────────────────────────────────────────────

@dataclass
class BuilderHandles:
    """Handles retornados pelos 4 builders. `widgets` dict de refs
    ao conteúdo renderizado (pro caller atualizar sem rebuild);
    `stop` callable opcional (só build_live_runs usa — cancela o
    polling interno)."""
    widgets: dict = field(default_factory=dict)
    stop: Callable[[], None] | None = None


# ── Module-level builder functions ────────────────────────────────────────────

def build_agent_header(
    parent: tk.Frame,
    *,
    agent: AgentIdentity,
    agent_dict: dict,
    stats: StatsView,
    on_toggle_pause: Callable[[AgentIdentity, bool], None],
) -> BuilderHandles:
    """Monta hero (sigil+nome) + statblock (budget/tokens/custo) +
    actions (pause/resume). Retorna handles pra refresh posterior."""
    handles = BuilderHandles()
    palette = AGENT_COLORS[agent.key]

    # ── Hero (sigil + nome + tagline) ─────────────────────────────
    hero = tk.Frame(parent, bg=BG)
    hero.pack(fill="x", pady=(0, 6))

    sigil = SigilCanvas(hero, agent.key, size=96, bg=BG)
    sigil.pack(side="left", padx=(0, 16))

    meta = tk.Frame(hero, bg=BG)
    meta.pack(side="left", fill="both", expand=True)

    tk.Label(
        meta, text=agent.key,
        font=agent_font(agent.key, size=22, weight="bold"),
        fg=palette.primary, bg=BG, anchor="w",
    ).pack(anchor="w")
    tk.Label(
        meta, text=agent.role,
        font=agent_font(agent.key, size=11),
        fg=WHITE, bg=BG, anchor="w",
    ).pack(anchor="w", pady=(2, 0))
    tk.Label(
        meta, text=f"{agent.archetype}  ·  {agent.stone}",
        font=(FONT, 8), fg=DIM, bg=BG, anchor="w",
    ).pack(anchor="w", pady=(4, 0))
    tk.Label(
        meta, text=agent.tagline,
        font=(FONT, 8, "italic"), fg=DIM2, bg=BG, anchor="w",
    ).pack(anchor="w", pady=(8, 0))

    # ── Statblock ─────────────────────────────────────────────────
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

    def _stat_row(
        grid_frame: tk.Frame, row: int, col: int, key: str, value: str,
    ) -> None:
        cell = tk.Frame(grid_frame, bg=BG)
        cell.grid(row=row, column=col, sticky="ew", pady=1, padx=(0, 10))
        tk.Label(
            cell, text=key,
            font=(FONT, 7), fg=DIM, bg=BG, anchor="w", width=16,
        ).pack(side="left")
        tk.Label(
            cell, text=value,
            font=agent_font(agent.key, size=9, weight="bold"),
            fg=WHITE, bg=BG, anchor="w",
        ).pack(side="left")

    _stat_row(grid, 0, 0, "tickets done", str(stats.tickets_done))
    _stat_row(grid, 0, 1, "tickets active", str(stats.tickets_active))
    _stat_row(grid, 1, 0, stats.artifact_kind_label, str(stats.artifacts_total))
    _stat_row(grid, 1, 1, "days active", stats.days_active)
    _stat_row(grid, 2, 0, "birthday", stats.birthday)
    _stat_row(
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
        else palette.primary if stats.monthly_pct < 0.8
        else AMBER
    )
    if stats.monthly_pct > 0:
        fill = tk.Frame(track, bg=fill_color, height=6)
        fill.place(relwidth=stats.monthly_pct, relheight=1.0)
    budget_pct_label = tk.Label(
        bar_wrap, text=f"{int(stats.monthly_pct * 100)}%",
        font=(FONT, 7), fg=DIM, bg=BG, anchor="e", width=5,
    )
    budget_pct_label.pack(side="left")
    handles.widgets["budget_bar"] = track
    handles.widgets["budget_pct_label"] = budget_pct_label

    # ── Actions ───────────────────────────────────────────────────
    # NOTE: actions are wired by the caller (AgentDetailModal) since
    # assign/close callbacks are modal-level. build_agent_header only
    # renders the pause button here; full actions row is built by modal.
    # We store a sentinel so caller knows header is ready.
    handles.widgets["header_frame"] = hero
    handles.widgets["stats_section"] = section

    return handles


def build_linked_work(
    parent: tk.Frame,
    *,
    agent: AgentIdentity,
    chains: list[LinkedChain],
    root_path: Path,
) -> BuilderHandles:
    """Lista chains filtradas do agent. COPY CMD + OPEN buttons.
    Se chains vazia → label stub '(sem artifacts deste agent)'."""
    handles = BuilderHandles()
    palette = AGENT_COLORS[agent.key]

    section = tk.Frame(parent, bg=BG)
    section.pack(fill="x", pady=(10, 0))

    tk.Label(
        section, text="LINKED WORK",
        font=(FONT, 8, "bold"), fg=AMBER_D, bg=BG, anchor="w",
    ).pack(anchor="w")

    if not chains:
        tk.Label(
            section, text="(sem artifacts deste agent)",
            font=(FONT, 8, "italic"), fg=DIM, bg=BG, anchor="w",
        ).pack(anchor="w", pady=(4, 0))
        handles.widgets["section"] = section
        return handles

    for chain in chains[:8]:  # max 8 pra nao estourar modal
        _render_chain_row(section, chain, palette=palette, root_path=root_path)

    handles.widgets["section"] = section
    return handles


def _render_chain_row(
    parent: tk.Frame,
    chain: LinkedChain,
    *,
    palette: Any,
    root_path: Path,
) -> None:
    row = tk.Frame(parent, bg=BG)
    row.pack(fill="x", pady=2)

    # Dots pra 4 fases (spec, review, branch, audit)
    phases = [
        ("S", chain.spec is not None),
        ("R", chain.review is not None),
        ("B", chain.branch is not None),
        ("A", chain.audit is not None),
    ]
    for letter, present in phases:
        color = palette.primary if present else DIM2
        tk.Label(
            row, text=letter,
            font=(FONT, 8, "bold"), fg=color, bg=BG, width=2, anchor="center",
        ).pack(side="left")

    # Stem + engine tag
    engine_tag = f" [{chain.engine}]" if chain.engine else ""
    tk.Label(
        row, text=f" {chain.stem}{engine_tag}",
        font=(FONT, 8), fg=WHITE, bg=BG, anchor="w",
    ).pack(side="left", fill="x", expand=True, padx=(6, 0))

    # COPY CMD button — so se houver branch (candidato a backtest)
    if chain.branch is not None and chain.engine is not None:
        copy_btn = tk.Label(
            row, text=" COPY CMD ",
            font=(FONT, 7, "bold"), fg=BG, bg=palette.primary,
            cursor="hand2", padx=4, pady=1,
        )
        copy_btn.pack(side="right", padx=(4, 0))
        copy_btn.bind(
            "<Button-1>",
            lambda _e, c=chain, w=row: _copy_backtest_cmd(c, widget=w),
        )


def _copy_backtest_cmd(chain: LinkedChain, *, widget: tk.Widget) -> None:
    cmd = backtest_command_for(chain)
    try:
        widget.clipboard_clear()
        widget.clipboard_append(cmd)
    except Exception:
        pass
    # Feedback visual breve — tenta encontrar o Toplevel pai
    try:
        top = widget.winfo_toplevel()
        original = top.title()
        top.title(f"comando copiado  ·  {chain.stem}")
        top.after(1500, lambda: _restore_title_safe(top, original))
    except Exception:
        pass


def _restore_title_safe(top: tk.Toplevel, title: str) -> None:
    try:
        top.title(title)
    except Exception:
        pass


def build_live_runs(
    parent: tk.Frame,
    *,
    agent: AgentIdentity,
    client: Any,
    interval_ms: int = 3000,
) -> BuilderHandles:
    """LIVE RUNS panel + polling interno via parent.after().
    Retorna handles com stop() pra cancelar o polling quando tab some."""
    handles = BuilderHandles()
    palette = AGENT_COLORS[agent.key]
    after_id: list[str | None] = [None]

    section = tk.Frame(parent, bg=BG)
    section.pack(fill="both", expand=True, pady=(10, 0))

    header = tk.Frame(section, bg=BG)
    header.pack(fill="x")
    tk.Label(
        header, text="LIVE RUNS",
        font=(FONT, 8, "bold"), fg=AMBER_D, bg=BG, anchor="w",
    ).pack(side="left")
    runs_counter = tk.Label(
        header, text="...",
        font=(FONT, 7), fg=DIM, bg=BG, anchor="e",
    )
    runs_counter.pack(side="right")

    runs_body = tk.Frame(section, bg=BG)
    runs_body.pack(fill="both", expand=True, pady=(6, 0))

    # Estado inicial
    tk.Label(
        runs_body, text="carregando...",
        font=(FONT, 8, "italic"), fg=DIM, bg=BG, anchor="w",
    ).pack(anchor="w")

    handles.widgets["runs_frame"] = runs_body
    handles.widgets["runs_counter"] = runs_counter

    def _apply_runs(views: list[RunView]) -> None:
        if not runs_body.winfo_exists():
            return
        try:
            for child in runs_body.winfo_children():
                child.destroy()
        except Exception:
            return

        try:
            runs_counter.configure(text=f"{len(views)} runs")
        except Exception:
            pass

        if not views:
            tk.Label(
                runs_body, text="sem runs recentes.",
                font=(FONT, 8, "italic"), fg=DIM, bg=BG, anchor="w",
            ).pack(anchor="w")
        else:
            for view in views:
                _render_run_row(runs_body, view, palette=palette)

    def _tick() -> None:
        if not parent.winfo_exists():
            return
        import threading

        def _work() -> None:
            try:
                raw = client(agent)
            except Exception:
                raw = []
            if not parent.winfo_exists():
                return
            views = shape_runs(raw, limit=10)
            try:
                parent.after(0, lambda: _apply_runs(views))
            except Exception:
                pass

        try:
            threading.Thread(target=_work, daemon=True).start()
        except Exception:
            pass
        # Re-arm
        after_id[0] = parent.after(interval_ms, _tick)

    def _stop() -> None:
        if after_id[0] is not None:
            try:
                parent.after_cancel(after_id[0])
            except Exception:
                pass
            after_id[0] = None

    handles.stop = _stop

    # fetch inicial — pequeno delay pra modal pintar primeiro
    after_id[0] = parent.after(50, _tick)

    return handles


def _render_run_row(parent: tk.Frame, view: RunView, *, palette: Any) -> None:
    row = tk.Frame(parent, bg=BG)
    row.pack(fill="x", pady=1)

    color = _RUN_STATUS_COLOR.get(view.status, DIM)
    tk.Label(
        row, text=view.status_icon,
        font=(FONT, 10), fg=color, bg=BG, width=2, anchor="w",
    ).pack(side="left")
    tk.Label(
        row, text=view.issue_title,
        font=(FONT, 8), fg=WHITE, bg=BG, anchor="w",
    ).pack(side="left", fill="x", expand=True)
    tk.Label(
        row, text=view.duration_text,
        font=(FONT, 7), fg=DIM, bg=BG, anchor="e", width=8,
    ).pack(side="right")
    tk.Label(
        row, text=view.cost_text,
        font=(FONT, 7), fg=palette.primary, bg=BG, anchor="e", width=8,
    ).pack(side="right")
    tk.Label(
        row, text=view.tokens_text,
        font=(FONT, 7), fg=DIM2, bg=BG, anchor="e", width=18,
    ).pack(side="right")
    tk.Label(
        row, text=view.age_text,
        font=(FONT, 7), fg=DIM, bg=BG, anchor="e", width=12,
    ).pack(side="right")


def _render_artifact_row_fn(
    parent: tk.Frame,
    entry: ArtifactEntry,
    *,
    palette: Any,
    toplevel: tk.Misc,
    root_path: Path,
) -> None:
    """Module-level artifact row renderer (usado por build_persona_stats
    e pelo modal)."""
    row = tk.Frame(parent, bg=BG, cursor="hand2")
    row.pack(fill="x", pady=2)
    tk.Frame(row, bg=palette.primary, width=2).pack(side="left", fill="y")
    content = tk.Frame(row, bg=BG)
    content.pack(side="left", fill="x", expand=True, padx=(6, 0))

    title_row = tk.Frame(content, bg=BG)
    title_row.pack(fill="x")
    tk.Label(
        title_row, text=entry.kind.upper(),
        font=(FONT, 7, "bold"), fg=palette.primary, bg=BG, width=8,
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
        open_markdown_viewer(toplevel, root_path=root_path, entry=e)

    row.bind("<Button-1>", _on_click)
    for child in (content, title_row):
        child.bind("<Button-1>", _on_click)
    for leaf in title_row.winfo_children():
        if isinstance(leaf, tk.Label):
            leaf.bind("<Button-1>", _on_click)


def build_persona_stats(
    parent: tk.Frame,
    *,
    agent: AgentIdentity,
    ratios: "RatiosView | None",
    root_path: Path,
    toplevel: tk.Misc,
    artifacts: list[ArtifactEntry] | None = None,
) -> BuilderHandles:
    """30d ratios + recent work summary + EDIT PERSONA button.
    toplevel = widget pai pro markdown_editor Toplevel (self.top
    da modal ou screen root pra tab).
    artifacts: lista de ArtifactEntry pra exibir no RECENT WORK panel."""
    handles = BuilderHandles()
    palette = AGENT_COLORS[agent.key]

    if ratios is not None and ratios.total > 0:
        section = tk.Frame(parent, bg=BG)
        section.pack(fill="x", pady=(10, 0))

        tk.Label(
            section, text="SHIP · ITERATE · KILL  (30d)",
            font=(FONT, 8, "bold"), fg=AMBER_D, bg=BG, anchor="w",
        ).pack(anchor="w")

        # Barra horizontal composta
        bar_row = tk.Frame(section, bg=BG2, height=10)
        bar_row.pack(fill="x", pady=(6, 2))
        bar_row.pack_propagate(False)
        if ratios.ship_pct > 0:
            ship = tk.Frame(bar_row, bg=GREEN)
            ship.place(relx=0, rely=0, relwidth=ratios.ship_pct, relheight=1)
        if ratios.iterate_pct > 0:
            it = tk.Frame(bar_row, bg=AMBER)
            it.place(relx=ratios.ship_pct, rely=0,
                     relwidth=ratios.iterate_pct, relheight=1)
        if ratios.kill_pct > 0:
            kl = tk.Frame(bar_row, bg=HAZARD)
            kl.place(relx=ratios.ship_pct + ratios.iterate_pct, rely=0,
                     relwidth=ratios.kill_pct, relheight=1)

        # Legenda numeric row
        legend = tk.Frame(section, bg=BG)
        legend.pack(fill="x")
        for label, count, pct, color in (
            ("ship",    ratios.ship,    ratios.ship_pct,    GREEN),
            ("iterate", ratios.iterate, ratios.iterate_pct, AMBER),
            ("kill",    ratios.kill,    ratios.kill_pct,    HAZARD),
        ):
            cell = tk.Frame(legend, bg=BG)
            cell.pack(side="left", padx=(0, 14))
            tk.Label(
                cell, text="■", font=(FONT, 8), fg=color, bg=BG,
            ).pack(side="left")
            tk.Label(
                cell, text=f" {label} {count}  ({int(pct * 100)}%)",
                font=(FONT, 7), fg=DIM, bg=BG,
            ).pack(side="left")

        handles.widgets["ratios_section"] = section

    # ── EDIT PERSONA button ──────────────────────────────────────
    edit_btn = tk.Label(
        parent, text="  EDIT PERSONA  ",
        font=(FONT, 8, "bold"),
        fg=WHITE, bg=BG3, cursor="hand2",
        padx=8, pady=4,
    )
    edit_btn.pack(anchor="w", pady=(10, 0))
    edit_btn.bind(
        "<Button-1>",
        lambda _e: _open_persona_editor(toplevel, agent=agent, root_path=root_path),
    )
    handles.widgets["edit_persona_btn"] = edit_btn

    # ── Recent work panel ─────────────────────────────────────────
    if artifacts is not None:
        tk.Frame(parent, bg=DIM, height=1).pack(fill="x", pady=(10, 0))
        rw_section = tk.Frame(parent, bg=BG)
        rw_section.pack(fill="both", expand=True, pady=(10, 0))

        tk.Label(
            rw_section, text="RECENT WORK",
            font=(FONT, 8, "bold"), fg=AMBER_D, bg=BG, anchor="w",
        ).pack(anchor="w")

        body = tk.Frame(rw_section, bg=BG)
        body.pack(fill="both", expand=True, pady=(6, 0))

        if not artifacts:
            tk.Label(
                body, text="sem artefatos registrados ainda.",
                font=(FONT, 8, "italic"), fg=DIM, bg=BG, anchor="w",
            ).pack(anchor="w")
        else:
            for entry in artifacts:
                _render_artifact_row_fn(
                    body, entry,
                    palette=palette, toplevel=toplevel, root_path=root_path,
                )

        handles.widgets["recent_work_body"] = body

    return handles


def _open_persona_editor(
    toplevel: tk.Misc, *, agent: AgentIdentity, root_path: Path,
) -> None:
    """Abre markdown_editor sobre AGENTS.md do agent. Standalone helper
    (antes era método de AgentDetailModal com anti-double-click guard).

    Note: original class method tracked self._persona_editor attr, calling
    focus_set() on existing window instead of opening a duplicate. This
    module-level helper is stateless by design. open_markdown_editor()
    uses transient(parent) but has no internal instance tracking. If
    double-click becomes an issue, reintroduce guard via module-level dict
    keyed by (agent.key, root_path) tuple, or add grab_set() to editor."""
    target = persona_path(agent.key, root_path)
    open_markdown_editor(
        toplevel, path=target,
        title_hint=f"{agent.key} persona · {target.name}",
    )


# ── Public entry point ────────────────────────────────────────────────────────

def open_agent_detail(
    parent: tk.Misc,
    *,
    agent: AgentIdentity,
    root_path: Path | str,
    agents_raw: list[dict],
    issues_raw: list[dict],
    on_assign: Callable[[AgentIdentity], None] | None = None,
    on_toggle_pause: Callable[[AgentIdentity, bool], None] | None = None,
    fetch_runs: Callable[[AgentIdentity], list[dict]] | None = None,
    fetch_ratios: Callable[[AgentIdentity], RatiosView | None] | None = None,
) -> None:
    """Abre o modal de detalhe. Scaneia artefatos localmente pro agent.

    agents_raw + issues_raw sao snapshots do poll atual do Screen (nao
    refaz HTTP aqui pra evitar lag). Artefatos sao resultado de um scan
    fresh — e rapido o suficiente pra rodar no open.

    on_toggle_pause recebe (agent, currently_paused) — o Screen chama
    client.pause_agent ou resume_agent baseado no flag.

    fetch_runs e opcional — se fornecido, modal mostra painel LIVE RUNS
    com auto-refresh 3s. Callback roda em thread daemon no Screen e
    retorna a lista de dicts crus de /api/heartbeat-runs.
    """
    root_path = ensure_path(root_path)
    artifacts_all = scan_artifacts(root_path, limit=200)
    artifacts_agent = filter_artifacts_for(agent, artifacts_all)
    issues_agent = filter_issues_for(agent, issues_raw)
    agent_dict = agent_dict_for(agent, agents_raw)
    is_paused = bool(agent_dict and agent_dict.get("paused"))
    chains = chains_for_agent(link_artifacts(artifacts_all), agent.key)

    stats = shape_stats(
        agent=agent,
        agent_dict=agent_dict,
        issues=issues_raw,  # passa todos — shape filtra por uuid
        artifacts=artifacts_agent,
    )

    ratios = None
    if fetch_ratios is not None:
        try:
            ratios = fetch_ratios(agent)
        except Exception:
            ratios = None

    AgentDetailModal(
        parent,
        agent=agent,
        stats=stats,
        artifacts=artifacts_agent[:5],
        root_path=root_path,
        is_paused=is_paused,
        ratios=ratios,
        chains=chains,
        agent_dict=agent_dict,
        on_assign=on_assign,
        on_toggle_pause=on_toggle_pause,
        fetch_runs=fetch_runs,
    )


# ── Modal (thin wrapper) ──────────────────────────────────────────────────────

class AgentDetailModal:
    def __init__(
        self,
        parent: tk.Misc,
        *,
        agent: AgentIdentity,
        stats: StatsView,
        artifacts: list[ArtifactEntry],
        root_path: Path,
        is_paused: bool = False,
        ratios: RatiosView | None = None,
        chains: list[LinkedChain] | None = None,
        agent_dict: dict | None = None,
        on_assign: Callable[[AgentIdentity], None] | None,
        on_toggle_pause: Callable[[AgentIdentity, bool], None] | None = None,
        fetch_runs: Callable[[AgentIdentity], list[dict]] | None = None,
    ):
        self.agent = agent
        self.palette = AGENT_COLORS[agent.key]
        self.root_path = root_path
        self._stats = stats
        self._agent_dict = agent_dict or {}
        self._is_paused = is_paused
        self._ratios = ratios
        self._chains = chains or []
        self._on_assign = on_assign
        self._on_toggle_pause = on_toggle_pause
        self._fetch_runs = fetch_runs

        # Builder handles
        self._header_handles: BuilderHandles | None = None
        self._linked_handles: BuilderHandles | None = None
        self._live_runs_handles: BuilderHandles | None = None
        self._stats_handles: BuilderHandles | None = None

        self.top = tk.Toplevel(parent)
        self.top.title(f"{agent.key} — {agent.role}")
        self.top.configure(bg=BG)
        self.top.geometry("720x720" if fetch_runs else "640x620")
        self.top.transient(parent)

        self._build(artifacts)
        self.top.bind("<Escape>", lambda _e: self._close())
        self.top.protocol("WM_DELETE_WINDOW", self._close)
        self.top.focus_set()

    def _close(self) -> None:
        if self._live_runs_handles and self._live_runs_handles.stop:
            self._live_runs_handles.stop()
        try:
            self.top.destroy()
        except Exception:
            pass

    def _build(self, artifacts: list[ArtifactEntry]) -> None:
        wrap = tk.Frame(self.top, bg=BG, padx=20, pady=16)
        wrap.pack(fill="both", expand=True)

        # Header: hero + statblock
        header_frame = tk.Frame(wrap, bg=BG)
        header_frame.pack(fill="x")
        self._header_handles = build_agent_header(
            header_frame,
            agent=self.agent,
            agent_dict=self._agent_dict,
            stats=self._stats,
            on_toggle_pause=self._on_toggle_pause,
        )

        tk.Frame(wrap, bg=DIM, height=1).pack(fill="x", pady=(10, 0))

        # Persona stats (ratios) + recent work in one builder
        stats_frame = tk.Frame(wrap, bg=BG)
        stats_frame.pack(fill="both", expand=True)
        self._stats_handles = build_persona_stats(
            stats_frame,
            agent=self.agent,
            ratios=self._ratios,
            root_path=self.root_path,
            toplevel=self.top,
            artifacts=artifacts,
        )

        # Linked work
        if self._chains:
            tk.Frame(wrap, bg=DIM, height=1).pack(fill="x", pady=(10, 0))
            linked_frame = tk.Frame(wrap, bg=BG)
            linked_frame.pack(fill="x")
            self._linked_handles = build_linked_work(
                linked_frame,
                agent=self.agent,
                chains=self._chains,
                root_path=self.root_path,
            )

        # Live runs
        if self._fetch_runs is not None:
            tk.Frame(wrap, bg=DIM, height=1).pack(fill="x", pady=(10, 0))
            runs_frame = tk.Frame(wrap, bg=BG)
            runs_frame.pack(fill="both", expand=True)
            self._live_runs_handles = build_live_runs(
                runs_frame,
                agent=self.agent,
                client=self._fetch_runs,
                interval_ms=_RUNS_REFRESH_MS,
            )

        # Actions row (assign + pause/resume + close) — inlined
        actions = tk.Frame(wrap, bg=BG)
        actions.pack(fill="x", pady=(12, 0))

        assign_btn = tk.Label(
            actions, text=f"  ATRIBUIR TICKET A {self.agent.key}  ",
            font=(FONT, 8, "bold"),
            fg=BG, bg=self.palette.primary, cursor="hand2",
            padx=8, pady=4,
        )
        assign_btn.pack(side="left")
        assign_btn.bind("<Button-1>", lambda _e: self._invoke_assign())

        # Toggle pause/resume — so aparece se callback foi injetado
        if self._on_toggle_pause is not None:
            pause_label = "  RETOMAR  " if self._is_paused else "  PAUSAR  "
            pause_bg = GREEN if self._is_paused else HAZARD
            self._pause_btn = tk.Label(
                actions, text=pause_label,
                font=(FONT, 8, "bold"),
                fg=BG, bg=pause_bg, cursor="hand2",
                padx=8, pady=4,
            )
            self._pause_btn.pack(side="left", padx=(8, 0))
            self._pause_btn.bind("<Button-1>", lambda _e: self._invoke_toggle_pause())

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

    def _invoke_toggle_pause(self) -> None:
        if self._on_toggle_pause is not None:
            # Fecha modal antes — Screen vai re-poll + reabrir se desejar
            was_paused = self._is_paused
            self._close()
            self._on_toggle_pause(self.agent, was_paused)
