"""EnginesScreen — unified /engines view.

Consolida RUNS HISTORY + LIVE RUNS + ENGINE LOGS num unico screen com
chip bar no topo. Cada chip mapeia pra um sub-render que ja existe:

  HISTORY → launcher_support.runs_history.render_runs_history
  LIVE    → launcher_support.screens.live_runs.LiveRunsScreen (nested)
  LOGS    → launcher_support.engine_logs_view.render_screen

Ao trocar chip, faz teardown especifico (cancel refresh, cleanup list,
on_exit) antes de recriar o sub-render no body. Visual segue o padrao
de /backtests — chrome unificado, UX de tab switcher.
"""
from __future__ import annotations

import tkinter as tk
from typing import Any, Optional

from core.ui.ui_palette import (
    AMBER, AMBER_D, AMBER_H,
    BG, BG3,
    DIM, DIM2, FONT,
)
from launcher_support.screens.base import Screen
from launcher_support.screens.live_runs import LiveRunsScreen


_TABS = (
    ("history", "RUNS HISTORY"),
    ("live",    "LIVE RUNS"),
    ("logs",    "ENGINE LOGS"),
)


class EnginesScreen(Screen):
    def __init__(self, parent: tk.Misc, app: Any, client_factory: Any):
        super().__init__(parent)
        self.app = app
        self._client_factory = client_factory
        self._active_tab: str = "history"
        self._body: Optional[tk.Frame] = None
        self._chips: dict[str, tk.Label] = {}
        self._live_screen: Optional[LiveRunsScreen] = None
        self._history_root: Optional[tk.Frame] = None

    def build(self) -> None:
        outer = tk.Frame(self.container, bg=BG)
        outer.pack(fill="both", expand=True, padx=20, pady=14)

        head = tk.Frame(outer, bg=BG); head.pack(fill="x")
        tk.Label(head, text="ENGINES", font=(FONT, 14, "bold"),
                 fg=AMBER, bg=BG, anchor="w").pack(anchor="w")
        tk.Label(head,
                 text="Timeline unificada de todos os engines — runs historicas, "
                      "sessoes live em andamento e logs de processos ativos em uma so tela.",
                 font=(FONT, 8), fg=DIM, bg=BG, anchor="w"
                 ).pack(anchor="w", pady=(3, 8))
        tk.Frame(outer, bg=DIM2, height=1).pack(fill="x", pady=(0, 8))

        cbar = tk.Frame(outer, bg=BG); cbar.pack(fill="x", pady=(0, 2))
        for key, label in _TABS:
            chip = tk.Label(cbar, text=f"  {label}  ",
                            font=(FONT, 8, "bold"),
                            fg=DIM, bg=BG, cursor="hand2",
                            padx=8, pady=4)
            chip.pack(side="left", padx=(0, 6))
            chip.bind("<Button-1>", lambda _e, k=key: self.set_tab(k))
            self._chips[key] = chip

        # Explicacao compacta de cada aba — ajuda operador a saber o
        # que procurar em cada uma sem abrir pra descobrir.
        self._hint = tk.Label(outer, text="",
                              font=(FONT, 7), fg=DIM, bg=BG, anchor="w")
        self._hint.pack(fill="x", pady=(6, 8))

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
                text="ESC voltar  |  1 history  |  2 live  |  3 logs"
            )
        if hasattr(app, "_kb"):
            app._kb("<Escape>", lambda: app._data_center())
            app._kb("<Key-1>", lambda: self.set_tab("history"))
            app._kb("<Key-2>", lambda: self.set_tab("live"))
            app._kb("<Key-3>", lambda: self.set_tab("logs"))
        self._update_chip_styles()
        self._mount_active()

    def on_exit(self) -> None:
        self._teardown_active()
        super().on_exit()

    def set_tab(self, key: str) -> None:
        if key == self._active_tab and self._body and self._body.winfo_children():
            return
        self._teardown_active()
        self._active_tab = key
        self._update_chip_styles()
        self._mount_active()

    def _update_chip_styles(self) -> None:
        for key, chip in self._chips.items():
            if not chip.winfo_exists():
                continue
            if key == self._active_tab:
                chip.configure(fg=AMBER_H, bg=BG3)
            else:
                chip.configure(fg=DIM, bg=BG)
        # Hint context-aware: o subtitulo abaixo do chip bar explica
        # a natureza do que o usuario esta vendo, sem precisar abrir
        # pra descobrir. Curto (1 linha) porque e reference, nao manual.
        _hints = {
            "history":
                "Timeline completa: runs backtest + live concluidas — "
                "ordenado por timestamp, filtro shadow/paper, merge local + VPS.",
            "live":
                "Sessoes de trading em curso ou recentes — paper, demo, "
                "testnet, live, shadow. Tick count + equity atual + ultimo sinal.",
            "logs":
                "Processos python ativos + historico de 72h — tail de stdout "
                "em tempo real, STOP verificado por image+pid, PURGE limpa zombies.",
        }
        hint = getattr(self, "_hint", None)
        if hint is not None and hint.winfo_exists():
            hint.configure(text=_hints.get(self._active_tab, ""))

    def _teardown_active(self) -> None:
        """Tab-specific cleanup antes de destruir widgets do body."""
        # Limpa o flag antes do teardown — evita que cleanups que
        # remontem algo herdem o contexto errado.
        try:
            self.app._engines_tab_active = False
        except Exception:
            pass
        if self._body is None:
            return
        k = self._active_tab
        if k == "logs":
            try:
                from launcher_support import engine_logs_view
                engine_logs_view.cleanup(self.app)
            except Exception:
                pass
        elif k == "history":
            if self._history_root is not None:
                try:
                    from launcher_support.runs_history import pause_runs_history
                    pause_runs_history(self._history_root, self.app)
                except Exception:
                    pass
                self._history_root = None
        elif k == "live":
            if self._live_screen is not None:
                try:
                    self._live_screen.on_exit()
                except Exception:
                    pass
                try:
                    self._live_screen.pack_forget()
                except Exception:
                    pass
                self._live_screen = None
        for w in list(self._body.winfo_children()):
            try:
                w.destroy()
            except Exception:
                pass

    def _mount_active(self) -> None:
        if self._body is None:
            return
        k = self._active_tab
        # Sinaliza pros sub-renders que eles estao dentro do wrapper —
        # usado pra suprimir titulo duplicado (ENGINES ja esta no header
        # do wrapper; nao precisa repintar "LIVE RUNS"/"ENGINE LOGS" em
        # fonte 14 bold de novo).
        self.app._engines_tab_active = True
        if k == "history":
            try:
                from launcher_support.runs_history import render_runs_history
                self._history_root = render_runs_history(
                    self._body, self.app,
                    client_factory=self._client_factory,
                )
            except Exception as exc:
                self._render_error(f"HISTORY render failed: {exc}")
        elif k == "live":
            try:
                # client_factory repassado pra LiveRunsScreen puxar
                # heartbeats VPS e ter as metricas SCAN/HEALTH/PROBE
                # no detail pane — antes renderizava so DB local sem
                # heartbeat.
                self._live_screen = LiveRunsScreen(
                    self._body, self.app,
                    client_factory=self._client_factory,
                )
                self._live_screen.mount()
                self._live_screen.pack()
                self._live_screen.on_enter()
            except Exception as exc:
                self._render_error(f"LIVE render failed: {exc}")
        elif k == "logs":
            try:
                from launcher_support.engine_logs_view import render_screen
                render_screen(
                    self.app, self._body,
                    on_escape=lambda: self.app._data_center(),
                )
            except Exception as exc:
                self._render_error(f"LOGS render failed: {exc}")

    def _render_error(self, msg: str) -> None:
        if self._body is None:
            return
        tk.Label(self._body, text=f"\n  {msg}",
                 font=(FONT, 9), fg="#ff6666", bg=BG,
                 anchor="w", justify="left").pack(anchor="w", pady=10)
