"""LiveRunsScreen — histórico de runs live/paper/shadow/demo/testnet.

Espelha BACKTESTS visualmente: left scrollable list + right detail panel.
Reads from aurum.db live_runs table — not the filesystem.
"""
from __future__ import annotations

import shutil
import subprocess
import time
import tkinter as tk
from pathlib import Path
from typing import Any

from config.paths import DATA_DIR
from core.ui.scroll import bind_mousewheel
from core.ui.ui_palette import AMBER, AMBER_D, BG, BG3, BORDER, DIM, DIM2, FONT, PANEL, WHITE
from launcher_support.screens.base import Screen
from launcher_support.runs_history import (
    _render_detail_health, _render_detail_probe, _render_detail_scan,
    _render_error_banner, lazy_fetch_heartbeat,
)
from core import db_live_runs
from core.ops import run_catalog


_LIST_COLS: list[tuple[str, int]] = [
    ("STATE", 7), ("ENGINE", 11), ("MODE", 7), ("STARTED", 16),
    ("TICKS", 6), ("SIG", 5), ("EQUITY", 10),
]


def _archive_run(run_id: str) -> bool:
    """Soft-delete: mv run_dir into data/_archive/live/. Returns True on success."""
    run = db_live_runs.get_live_run(run_id)
    if run is None:
        return False
    src = Path(run["run_dir"])
    if not src.is_absolute():
        src = DATA_DIR.parent / src
    if not src.exists():
        return False
    dst = DATA_DIR / "_archive" / "live" / src.parent.name / src.name
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return False
    shutil.move(str(src), str(dst))
    return True


def _open_dir(run_dir: str | None) -> None:
    if not run_dir:
        return
    p = Path(run_dir)
    if not p.is_absolute():
        p = DATA_DIR.parent / p
    if not p.exists():
        return
    subprocess.Popen(["explorer", str(p)])


class LiveRunsScreen(Screen):
    _TTL_SEC = 3.0
    _MODES = ("all", "live", "paper", "shadow", "demo", "testnet")

    def __init__(self, parent: tk.Misc, app: Any,
                 client_factory: Any = None):
        super().__init__(parent)
        self.app = app
        # client_factory() -> cockpit client ou None. Quando passado,
        # _fetch_runs puxa tambem os heartbeats do VPS (permitindo
        # renderizar SCAN/HEALTH/PROBE no detail pane). Sem factory,
        # fica em modo local-only como antes — sem regressao.
        self._client_factory = client_factory
        self._mode_filter: str = "all"
        self._list_cache: tuple[float, str, list[dict]] | None = None
        self._selected_run_id: str | None = None
        self._list_frame: tk.Frame | None = None
        self._list_canvas: tk.Canvas | None = None
        self._detail_frame: tk.Frame | None = None
        self._filter_tabs: dict[str, tk.Label] = {}
        self._current_rows: list[run_catalog.RunSummary] = []

    def build(self) -> None:
        outer = tk.Frame(self.container, bg=BG)
        outer.pack(fill="both", expand=True, padx=20, pady=14)

        head = tk.Frame(outer, bg=BG); head.pack(fill="x")
        tk.Label(
            head, text="LIVE RUNS", font=(FONT, 14, "bold"),
            fg=AMBER, bg=BG, anchor="w",
        ).pack(anchor="w")
        tk.Label(
            head, text="Ops snapshot do live_runs DB. Use RUNS HISTORY para timeline unificada local + VPS.",
            font=(FONT, 8), fg=DIM, bg=BG, anchor="w",
        ).pack(anchor="w", pady=(3, 8))
        tk.Frame(outer, bg=DIM2, height=1).pack(fill="x", pady=(0, 8))

        # Filter bar
        fbar = tk.Frame(outer, bg=BG); fbar.pack(fill="x", pady=(0, 8))
        tk.Label(
            fbar, text="FILTER", font=(FONT, 7, "bold"),
            fg=DIM, bg=BG,
        ).pack(side="left", padx=(0, 10))
        for idx, mode in enumerate(self._MODES, start=1):
            tab = tk.Label(
                fbar, text=f" {idx}:{mode.upper()} ",
                font=(FONT, 7, "bold"),
                fg=AMBER_D if mode == self._mode_filter else DIM,
                bg=BG3 if mode == self._mode_filter else BG,
                cursor="hand2", padx=6, pady=2,
            )
            tab.pack(side="left", padx=(0, 4))
            tab.bind("<Button-1>",
                     lambda _e, m=mode: self.set_filter(m))
            self._filter_tabs[mode] = tab

        # Split: list | detail
        split = tk.Frame(outer, bg=BG)
        split.pack(fill="both", expand=True)
        split.grid_columnconfigure(0, weight=3, uniform="lr_split")
        split.grid_columnconfigure(1, weight=2, uniform="lr_split")
        split.grid_rowconfigure(0, weight=1)

        left = tk.Frame(
            split, bg=BG, highlightbackground=BORDER, highlightthickness=1,
        )
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        hrow = tk.Frame(left, bg=BG); hrow.pack(fill="x")
        for label, width in _LIST_COLS:
            tk.Label(hrow, text=label, font=(FONT, 7, "bold"),
                     fg=DIM, bg=BG, width=width, anchor="w").pack(side="left")
        tk.Frame(left, bg=DIM2, height=1).pack(fill="x", pady=(1, 2))

        # Scrollable list area — Canvas + Scrollbar (mirrors connections.py pattern)
        list_canvas = tk.Canvas(left, bg=BG, highlightthickness=0)
        list_sb = tk.Scrollbar(left, orient="vertical", command=list_canvas.yview)
        self._list_frame = tk.Frame(list_canvas, bg=BG)
        self._list_frame.bind(
            "<Configure>",
            lambda _e: list_canvas.configure(scrollregion=list_canvas.bbox("all")),
        )
        list_canvas.create_window((0, 0), window=self._list_frame, anchor="nw")
        list_canvas.configure(yscrollcommand=list_sb.set)
        list_canvas.pack(side="left", fill="both", expand=True)
        list_sb.pack(side="right", fill="y")
        self._list_canvas = list_canvas

        bind_mousewheel(list_canvas)

        right = tk.Frame(
            split, bg=PANEL, highlightbackground=BORDER, highlightthickness=1,
        )
        right.grid(row=0, column=1, sticky="nsew")
        tk.Label(right, text="DETAILS", font=(FONT, 7, "bold"),
                 fg=AMBER_D, bg=PANEL, anchor="w").pack(
            anchor="nw", padx=10, pady=(10, 4),
        )
        tk.Frame(right, bg=DIM2, height=1).pack(fill="x", padx=10, pady=(0, 6))
        self._detail_frame = tk.Frame(right, bg=PANEL)
        self._detail_frame.pack(fill="both", expand=True, padx=10, pady=(2, 10))

    def on_enter(self, **kwargs: Any) -> None:
        del kwargs
        app = self.app
        if hasattr(app, "h_path"):
            app.h_path.configure(text="> DATA > LIVE RUNS")
        if hasattr(app, "h_stat"):
            app.h_stat.configure(text="BROWSE", fg=AMBER_D)
        if hasattr(app, "f_lbl"):
            app.f_lbl.configure(
                text="ESC voltar  |  1-6 filter  |  R runs history  |  click row for details",
            )
        if hasattr(app, "_kb"):
            app._kb("<Escape>", lambda: app._data_center())
            app._kb("<Key-r>", lambda: app._data_runs_history())
            app._kb("<Key-R>", lambda: app._data_runs_history())
            for idx, mode in enumerate(self._MODES, start=1):
                app._kb(f"<Key-{idx}>",
                        lambda m=mode: self.set_filter(m))
        self._render()

    def on_exit(self) -> None:
        app = self.app
        if hasattr(app, "_clear_kb"):
            try:
                app._clear_kb()
            except Exception:
                pass
        super().on_exit()

    def set_filter(self, mode: str) -> None:
        if mode not in self._MODES:
            return
        self._mode_filter = mode
        for m, tab in self._filter_tabs.items():
            tab.configure(
                fg=AMBER_D if m == mode else DIM,
                bg=BG3 if m == mode else BG,
            )
        self._list_cache = None  # force refresh on filter change
        self._selected_run_id = None  # reset so auto-select picks newest in new mode
        self._render()

    def _fetch_runs(self) -> list[run_catalog.RunSummary]:
        now = time.monotonic()
        cache = self._list_cache
        if cache is not None and cache[1] == self._mode_filter and \
                (now - cache[0]) < self._TTL_SEC:
            return cache[2]
        mode = None if self._mode_filter == "all" else self._mode_filter
        # client_factory() pode retornar None (tunnel down) — nesse caso
        # list_runs_catalog segue so com local+DB e nao renderiza SCAN/
        # HEALTH/PROBE no detail (heartbeat fica None). Sem crash, sem
        # regressao — modo graceful degradation quando VPS esta offline.
        client = None
        if self._client_factory is not None:
            try:
                client = self._client_factory()
            except Exception:
                client = None
        runs = run_catalog.list_runs_catalog(
            mode=mode, client=client, limit_db=500,
        )
        self._list_cache = (now, self._mode_filter, runs)
        return runs

    def _render(self) -> None:
        runs = self._fetch_runs()
        if self._list_frame is None:
            return
        for w in self._list_frame.winfo_children():
            w.destroy()
        if not runs:
            tk.Label(self._list_frame,
                     text="  no runs in this mode.",
                     font=(FONT, 9), fg=DIM, bg=BG,
                     anchor="w").pack(fill="x", pady=8)
            return
        self._current_rows = list(runs)
        for run in runs:
            self._render_row(run)
        # auto-select newest if nothing selected
        # TODO(task-10): clear _selected_run_id if it no longer appears in list
        # (e.g., after ARCHIVE). For now, detail panel falls back to "run not found".
        if self._selected_run_id is None and runs:
            self._select(runs[0].run_id)

    def _render_row(self, run: run_catalog.RunSummary) -> None:
        if self._list_frame is None:
            return
        state_color = {
            "running": AMBER, "stopped": DIM, "crashed": DIM,
        }.get(run.status or "", DIM)
        row = tk.Frame(self._list_frame, bg=BG, cursor="hand2")
        row.pack(fill="x", padx=2, pady=1)
        row.bind("<Button-1>",
                 lambda _e, rid=run.run_id: self._select(rid))
        cols = [
            ((run.status or "?")[:6].upper(), state_color, _LIST_COLS[0][1]),
            (run.engine[:10], AMBER, _LIST_COLS[1][1]),
            ((run.mode or "?")[:5].upper(), AMBER_D, _LIST_COLS[2][1]),
            ((run.started_at or "")[:16], DIM, _LIST_COLS[3][1]),
            (str(run.ticks_ok or 0), DIM, _LIST_COLS[4][1]),
            (str(run.novel or 0), DIM, _LIST_COLS[5][1]),
            (f"{run.equity or 0:.0f}", DIM, _LIST_COLS[6][1]),
        ]
        for text, color, width in cols:
            lbl = tk.Label(row, text=text, font=(FONT, 8),
                           fg=color, bg=BG, width=width, anchor="w")
            lbl.pack(side="left")
            lbl.bind("<Button-1>",
                     lambda _e, rid=run.run_id: self._select(rid))

    def _select(self, run_id: str) -> None:
        self._selected_run_id = run_id
        self._render_detail(run_id)

    def _reload_if_still_selected(self, run_id: str) -> None:
        """Re-render detail pane APENAS se o mesmo run_id continua
        selecionado. Protege contra race quando operador clicou em
        outra run durante o fetch async do heartbeat."""
        if self._selected_run_id == run_id:
            self._render_detail(run_id)

    def _render_detail(self, run_id: str) -> None:
        if self._detail_frame is None:
            return
        for w in self._detail_frame.winfo_children():
            w.destroy()
        run = next((row for row in self._current_rows if row.run_id == run_id), None)
        if run is None:
            tk.Label(self._detail_frame, text="run not found",
                     font=(FONT, 9), fg=DIM, bg=PANEL).pack(anchor="w")
            return

        tk.Label(
            self._detail_frame,
            text=f"{run.engine} / {run.mode}",
            font=(FONT, 10, "bold"), fg=AMBER, bg=PANEL, anchor="w",
        ).pack(anchor="w")
        tk.Label(
            self._detail_frame, text=run.run_id,
            font=(FONT, 8), fg=DIM, bg=PANEL, anchor="w",
        ).pack(anchor="w", pady=(0, 8))

        self._detail_section("IDENTITY", [
            ("engine", run.engine or "?"),
            ("mode", run.mode or "?"),
            ("host", run.host or "?"),
            ("label", run.label or "-"),
            ("run_dir", str(run.run_dir) if run.run_dir is not None else "?"),
        ])
        self._detail_section("TIMELINE", [
            ("started", (run.started_at or "?")[:19]),
            ("ended", (run.stopped_at or "-")[:19]),
            ("last tick", (run.last_tick_at or "-")[:19]),
            ("status", run.status or "unknown"),
        ])
        self._detail_section("PERFORMANCE", [
            ("equity", f"{run.equity or 0:.2f}"),
            ("open positions", str(run.open_count or 0)),
        ])
        self._detail_section("ACTIVITY", [
            ("ticks", str(run.ticks_ok or 0)),
            ("novel signals", str(run.novel or 0)),
        ])

        # Health metrics vindos do cockpit heartbeat. Async lazy-fetch:
        # antes bloqueava UI ate 5s em tunnel lento (audit 2026-04-22).
        # Agora pinta detail com hb=None, dispara fetch em daemon
        # thread, e ao completar reentra via app.after(0, _render_detail).
        # Guard _hb_fetch_attempted evita loop infinito quando fetch
        # falha.
        attempted = getattr(self, "_hb_fetch_attempted", None)
        if attempted is None:
            attempted = set()
            self._hb_fetch_attempted = attempted
        if (run.heartbeat is None and run.source == "vps"
                and self._client_factory is not None
                and run.run_id not in attempted):
            attempted.add(run.run_id)

            def _after(_rid=run.run_id):
                try:
                    self.app.after(
                        0, lambda: self._reload_if_still_selected(_rid),
                    )
                except Exception:
                    pass
            lazy_fetch_heartbeat(run, self._client_factory, on_complete=_after)
        hb = run.heartbeat or {}
        if hb.get("last_error"):
            _render_error_banner(self._detail_frame, str(hb["last_error"]))
        _render_detail_scan(self._detail_frame, run)
        _render_detail_health(self._detail_frame, run)
        _render_detail_probe(self._detail_frame, run)

        actions = tk.Frame(self._detail_frame, bg=PANEL)
        actions.pack(fill="x", pady=(10, 0))
        for label, cmd, color in [
            ("OPEN DIR", lambda rd=(str(run.run_dir) if run.run_dir is not None else None): _open_dir(rd), AMBER),
            ("ARCHIVE", self._archive_selected, AMBER_D),
        ]:
            b = tk.Label(
                actions, text=f"  {label}  ", font=(FONT, 8, "bold"),
                fg=color, bg=BG3, cursor="hand2", padx=8, pady=3,
            )
            b.pack(side="left", padx=(0, 6))
            b.bind("<Button-1>", lambda _e, c=cmd: c())

    def _archive_selected(self) -> None:
        if not self._selected_run_id:
            return
        ok = _archive_run(self._selected_run_id)
        if ok:
            self._list_cache = None
            self._selected_run_id = None
            self._render()

    def _detail_section(self, title: str, rows: list[tuple[str, str]]) -> None:
        if self._detail_frame is None:
            return
        tk.Label(
            self._detail_frame, text=title,
            font=(FONT, 8, "bold"), fg=AMBER_D, bg=PANEL, anchor="w",
        ).pack(anchor="w", pady=(6, 2))
        tk.Frame(self._detail_frame, bg=DIM2, height=1).pack(fill="x")
        for k, v in rows:
            row = tk.Frame(self._detail_frame, bg=PANEL)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=f"  {k}", font=(FONT, 8),
                     fg=DIM, bg=PANEL, anchor="w", width=18).pack(side="left")
            tk.Label(row, text=str(v), font=(FONT, 8),
                     fg=WHITE, bg=PANEL, anchor="w").pack(side="left")
