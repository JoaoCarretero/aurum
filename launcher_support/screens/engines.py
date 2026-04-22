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
