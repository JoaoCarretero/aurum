"""EnginesScreen — unified /engines view (single pane, no tabs).

Fundido num so render (antes era chip bar HISTORY / LIVE / LOGS):
runs_history ja mostra toda a timeline (local + VPS merged, filtro
ALL/SHADOW/PAPER), com detail pane enriquecido que cobre:

  - heartbeat (ticks/novel/equity/roi) — ex-LIVE RUNS
  - SCAN funnel (scanned/dedup/stale/live) — ex-heartbeat do VPS
  - HEALTH (drawdown/ks_state/primed/tick cadence)
  - PROBE DIAGNOSTIC (top_score/threshold/n_above_*)
  - LOG TAIL ultimas 25 linhas — ex-ENGINE LOGS
  - TRADES ultimos 10 — ex-RUNS HISTORY

Usuario pediu: "comprima em 1 so lugar as 3 abas de dados, sem
buncar". Chip bar removido. LiveRunsScreen + engine_logs_view
continuam registrados em registry.py pra navegacao direta (R toggle,
splash quick-link), mas DATA > ENGINES vai direto pro unificado.
"""
from __future__ import annotations

import tkinter as tk
from typing import Any, Optional

from core.ui.ui_palette import AMBER, AMBER_D, BG, DIM, DIM2, FONT
from launcher_support.screens.base import Screen


class EnginesScreen(Screen):
    def __init__(self, parent: tk.Misc, app: Any, client_factory: Any):
        super().__init__(parent)
        self.app = app
        self._client_factory = client_factory
        self._body: Optional[tk.Frame] = None
        self._history_root: Optional[tk.Frame] = None

    def build(self) -> None:
        outer = tk.Frame(self.container, bg=BG)
        outer.pack(fill="both", expand=True, padx=20, pady=14)

        head = tk.Frame(outer, bg=BG); head.pack(fill="x")
        tk.Label(head, text="ENGINES", font=(FONT, 14, "bold"),
                 fg=AMBER, bg=BG, anchor="w").pack(anchor="w")
        tk.Label(head,
                 text="Timeline unificada de runs — local + VPS merged. "
                      "Click row pra heartbeat, scan funnel, health, probe, "
                      "log tail e trades — tudo num so detail pane.",
                 font=(FONT, 8), fg=DIM, bg=BG, anchor="w"
                 ).pack(anchor="w", pady=(3, 8))
        tk.Frame(outer, bg=DIM2, height=1).pack(fill="x", pady=(0, 8))

        body = tk.Frame(outer, bg=BG)
        body.pack(fill="both", expand=True)
        self._body = body

    def on_enter(self, **kwargs: Any) -> None:
        del kwargs
        app = self.app
        if hasattr(app, "h_path"):
            app.h_path.configure(text="> DATA > ENGINES")
        if hasattr(app, "h_stat"):
            app.h_stat.configure(text="BROWSE", fg=AMBER_D)
        if hasattr(app, "f_lbl"):
            app.f_lbl.configure(
                text="ESC voltar  |  click row pra detail completo"
            )
        if hasattr(app, "_kb"):
            app._kb("<Escape>", lambda: app._data_center())
        self._mount()

    def on_exit(self) -> None:
        self._teardown()
        super().on_exit()

    def _teardown(self) -> None:
        try:
            self.app._engines_tab_active = False
        except Exception:
            pass
        if self._body is None:
            return
        if self._history_root is not None:
            try:
                from launcher_support.runs_history import pause_runs_history
                pause_runs_history(self._history_root, self.app)
            except Exception:
                pass
            self._history_root = None
        for w in list(self._body.winfo_children()):
            try:
                w.destroy()
            except Exception:
                pass

    def _mount(self) -> None:
        if self._body is None:
            return
        # Sinaliza pro runs_history que esta dentro do wrapper (suprime
        # titulo duplicado — ENGINES ja no header acima).
        self.app._engines_tab_active = True
        try:
            from launcher_support.runs_history import render_runs_history
            self._history_root = render_runs_history(
                self._body, self.app,
                client_factory=self._client_factory,
            )
        except Exception as exc:
            tk.Label(self._body, text=f"\n  render failed: {exc}",
                     font=(FONT, 9), fg="#ff6666", bg=BG,
                     anchor="w", justify="left").pack(anchor="w", pady=10)


# ─────────────────────────────────────────────────────────────────────────────
# Functions extracted from launcher.App in Fase 3 refactor (Task 7)
# ─────────────────────────────────────────────────────────────────────────────

def engine_extra_cli_flags(engine_name: str) -> list:
    """Engine-specific CLI overrides injected by the launcher.

    Extend here for future engines whose params differ from config.params
    defaults. Flags applied here do not touch config.params (core-
    protected) -- they only change the in-process dataclass for the run.

    Extracted from launcher.App._engine_extra_cli_flags in Fase 3 refactor.
    """
    name = engine_name.upper().replace(" ", "").replace("_", "")
    return []


def refresh(app) -> None:
    """Rebuild the proc list with RUNNING + STOPPED sections, always
    visible. Each section sorted by recency DESC. Reschedules 2s tick.

    Extracted from launcher.App._eng_refresh in Fase 3 refactor.
    """
    from launcher_support import engine_logs_view

    engine_logs_view.refresh_list(app)


def normalize_local_proc(proc: dict) -> dict:
    """Normalize a local proc dict via run_catalog.

    Extracted from launcher.App._eng_normalize_local_proc in Fase 3 refactor.
    """
    from core.ops import run_catalog

    return run_catalog.normalize_engine_log_local_proc(proc)


def known_slugs() -> set:
    """Return the set of known engine slugs.

    Extracted from launcher.App._eng_known_slugs in Fase 3 refactor.
    """
    from core.ops import run_catalog

    try:
        from core.ops.proc import ENGINES as _ENGINES
        proc_engines = _ENGINES
    except Exception:
        proc_engines = {}
    return run_catalog.engine_known_slugs(proc_engines)


def base_slug(row: dict) -> str:
    """Return the base slug for a run row.

    Extracted from launcher.App._eng_base_slug in Fase 3 refactor.
    """
    from core.ops import run_catalog

    return run_catalog.engine_base_slug(row)


def is_engine_row(app, row: dict) -> bool:
    """Return True if row belongs to a known engine.

    Extracted from launcher.App._eng_is_engine_row in Fase 3 refactor.
    """
    from core.ops import run_catalog

    return run_catalog.is_engine_log_row(
        row,
        known_slugs=app._eng_known_slugs(),
    )


def matches_mode_filter(app, row: dict) -> bool:
    """Return True if row passes the current mode filter.

    Extracted from launcher.App._eng_matches_mode_filter in Fase 3 refactor.
    """
    from core.ops import run_catalog

    return run_catalog.matches_engine_mode_filter(
        row,
        getattr(app, "_eng_mode_filter", "all"),
    )


def row_key(row: dict) -> str:
    """Return the canonical key for an engine log row.

    Extracted from launcher.App._eng_row_key in Fase 3 refactor.
    """
    from core.ops import run_catalog

    return run_catalog.engine_log_row_key(row)


def set_mode_filter(app, mode_name: str) -> None:
    """Set the mode filter and trigger a refresh.

    Extracted from launcher.App._eng_set_mode_filter in Fase 3 refactor.
    """
    try:
        from core.ui.ui_palette import DIM
    except ImportError:
        DIM = "#888888"
    app._eng_mode_filter = mode_name
    app._eng_selected_key = None
    app._eng_selected_pid = None
    try:
        app._eng_log_text.config(state="normal")
        app._eng_log_text.delete("1.0", "end")
        app._eng_log_text.config(state="disabled")
        app._eng_log_header.configure(
            text=f" -- select an engine log in {mode_name.upper()} -- ",
            fg=DIM,
        )
    except Exception:
        pass
    app._eng_refresh()


def refresh_filter_tabs(app) -> None:
    """Refresh the filter-tab chip bar.

    Extracted from launcher.App._eng_refresh_filter_tabs in Fase 3 refactor.
    """
    from launcher_support import engine_logs_view

    engine_logs_view.refresh_filter_tabs(app)


def run_id_of(row: dict):
    """Return the run_id for a row, or None.

    Extracted from launcher.App._eng_run_id_of in Fase 3 refactor.
    """
    from core.ops import run_catalog

    return run_catalog.engine_log_run_id_of(row)


def recency_key(row: dict) -> float:
    """Higher = more recent. Delegated to shared run-catalog helpers.

    Extracted from launcher.App._eng_recency_key in Fase 3 refactor.
    """
    from core.ops import run_catalog

    return run_catalog.engine_log_recency_key(row)


def scan_vps_runs(limit: int = 10) -> list:
    """Resolve VPS engine-log rows via the shared run catalog.

    Extracted from launcher.App._eng_scan_vps_runs in Fase 3 refactor.
    """
    try:
        from launcher_support.engines_live_view import _get_cockpit_client
        from core.ops import run_catalog
        client = _get_cockpit_client()
    except Exception:
        return []
    try:
        return run_catalog.collect_engine_log_vps_rows(client, limit=limit)
    except Exception:
        return []


def scan_historical_runs(app, *, limit: int = 15, hours: int = 48) -> list:
    """Resolve recent local historical rows via the shared run catalog.

    Extracted from launcher.App._eng_scan_historical_runs in Fase 3 refactor.
    """
    import time
    now_ts = time.time()
    cached = getattr(app, "_eng_historical_cache", None)
    cached_ts = float(getattr(app, "_eng_historical_cache_ts", 0.0) or 0.0)
    if cached is not None and (now_ts - cached_ts) < 30.0:
        return list(cached[:limit])
    try:
        from core.ops import run_catalog
        result = run_catalog.collect_engine_log_local_rows(
            limit=limit,
            hours=hours,
        )
    except Exception:
        result = []
    app._eng_historical_cache = result
    app._eng_historical_cache_ts = now_ts
    return result[:limit]


def render_row(app, proc: dict) -> None:
    """Render a single engine row into the list pane.

    Extracted from launcher.App._eng_render_row in Fase 3 refactor.
    """
    from launcher_support import engine_logs_view

    engine_logs_view.render_row(app, proc)


def uptime_of(proc: dict, hb: dict) -> str:
    """Short uptime string (e.g. '2h15m', '45m'). Empty if unknown.

    Extracted from launcher.App._eng_uptime_of in Fase 3 refactor.
    """
    from datetime import datetime, timezone
    started_raw = (hb.get("started_at") or proc.get("started_at")
                   or proc.get("started") or "")
    if not started_raw:
        return "—"
    try:
        t0 = datetime.fromisoformat(str(started_raw).replace("Z", "+00:00"))
        if t0.tzinfo is None:
            t0 = t0.replace(tzinfo=timezone.utc)
    except Exception:
        return "—"
    if not proc.get("alive"):
        stopped_raw = hb.get("stopped_at")
        try:
            t1 = datetime.fromisoformat(
                str(stopped_raw).replace("Z", "+00:00"))
            if t1.tzinfo is None:
                t1 = t1.replace(tzinfo=timezone.utc)
        except Exception:
            t1 = datetime.now(timezone.utc)
    else:
        t1 = datetime.now(timezone.utc)
    secs = max(0, int((t1 - t0).total_seconds()))
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m"
    h = secs // 3600
    mins = (secs % 3600) // 60
    return f"{h}h{mins:02d}m" if h < 24 else f"{h // 24}d{h % 24}h"


def select(app, proc: dict) -> None:
    """Stop old log tail, start a new one for the selected proc.

    Extracted from launcher.App._eng_select in Fase 3 refactor.
    """
    from launcher_support import engine_logs_view

    engine_logs_view.select_proc(app, proc)


def load_entries(app, proc: dict) -> None:
    """Load log entries for the selected proc.

    Extracted from launcher.App._eng_load_entries in Fase 3 refactor.
    """
    from launcher_support import engine_logs_view

    engine_logs_view.load_entries(app, proc)


def fetch_entries(proc: dict, stop) -> tuple:
    """Blocking fetch of entries. Returns (formatted_lines, summary).

    Extracted from launcher.App._eng_fetch_entries in Fase 3 refactor.
    """
    from core.ops import run_catalog

    if proc.get("_remote"):
        rid = proc.get("_run_id")
        if not rid:
            return [], "no run_id"
        try:
            from launcher_support.engines_live_view import _get_cockpit_client
            client = _get_cockpit_client()
        except Exception:
            return [], "cockpit client unavailable"
        lines, summary = run_catalog.fetch_remote_entries(
            client,
            rid,
            mode=str(proc.get("mode") or "").lower(),
            limit=50,
        )
        if stop.is_set():
            return [], summary
        return lines, summary

    # Local
    rd = proc.get("run_dir")
    lines, summary = run_catalog.read_local_entries(rd, limit=50)
    if stop.is_set():
        return [], summary
    return lines, summary


def apply_entries(app, lines: list, summary: str) -> None:
    """Apply fetched log entries to the text widget.

    Extracted from launcher.App._eng_apply_entries in Fase 3 refactor.
    """
    from launcher_support import engine_logs_view

    engine_logs_view.apply_entries(app, lines, summary)
