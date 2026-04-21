"""Deploy pipeline screen for terminal-first backtest -> paper flow."""
from __future__ import annotations

import time
import tkinter as tk
from typing import Any

from core.ui.ui_palette import AMBER, AMBER_D, BG, BG2, BG3, BORDER, DIM, DIM2, FONT, PANEL, WHITE
from launcher_support import deploy_pipeline
from launcher_support.screens.base import Screen

_LIST_COLS: list[tuple[str, int]] = [
    ("STAGE", 12),
    ("ENGINE", 12),
    ("ROI", 9),
    ("SH", 7),
    ("RUN", 18),
]


class DeployPipelineScreen(Screen):
    _TTL_SEC = 3.0

    def __init__(self, parent: tk.Misc, app: Any):
        super().__init__(parent)
        self.app = app
        self._subtitle_label: tk.Label | None = None
        self._stat_tags: dict[str, tk.Label] = {}
        self._list_frame: tk.Frame | None = None
        self._list_canvas: tk.Canvas | None = None
        self._detail_frame: tk.Frame | None = None
        self._selected_slug: str | None = None
        self._current_candidates: list[deploy_pipeline.DeployCandidate] = []
        self._snapshot_cache: tuple[float, dict[str, Any]] | None = None

    def build(self) -> None:
        outer = tk.Frame(self.container, bg=BG)
        outer.pack(fill="both", expand=True, padx=20, pady=14)

        head = tk.Frame(outer, bg=BG)
        head.pack(fill="x", pady=(0, 12))
        strip = tk.Frame(head, bg=BG)
        strip.pack(fill="x")
        tk.Frame(strip, bg=AMBER, width=4, height=28).pack(side="left", padx=(0, 8))

        title_wrap = tk.Frame(strip, bg=BG)
        title_wrap.pack(side="left", fill="x", expand=True)
        tk.Label(title_wrap, text="DEPLOY PIPELINE", font=(FONT, 14, "bold"), fg=AMBER, bg=BG, anchor="w").pack(anchor="w")
        self._subtitle_label = tk.Label(title_wrap, text="", font=(FONT, 8), fg=DIM, bg=BG, anchor="w")
        self._subtitle_label.pack(anchor="w", pady=(3, 0))

        tk.Frame(outer, bg=BG2, height=6).pack(fill="x")
        tk.Frame(outer, bg=DIM, height=1).pack(fill="x", pady=(0, 12))

        content = tk.Frame(outer, bg=BG)
        content.pack(fill="both", expand=True)

        app = self.app
        panel = app._ui_panel_frame(
            content,
            "TERMINAL-FIRST EXECUTION",
            "Backtest, validate, shortlist deployable engines and launch paper with explicit operator control",
        )

        items = [
            ("B", "Run Backtest", "engine picker with inline backtest execution", "backtest", app._strategies_backtest),
            ("V", "Validated Runs DB", "latest persisted runs and result browser", "validated", app._data_backtests),
            ("P", "Start Selected PAPER", "launch the selected paper-ready candidate", "paper", self._start_selected_candidate),
            ("C", "Open LIVE Cockpit", "paper / shadow / bootstrap control plane", "cockpit", self._open_selected_cockpit),
            ("H", "Runs History", "unified timeline local + VPS + DB", "history", app._data_runs_history),
            ("E", "Engine Logs", "running and recent engines with live tail", "engines", app._data_engines),
        ]
        for key_label, name, desc, stat_key, cmd in items:
            row, _, _ = app._ui_action_row(
                panel,
                key_label,
                name,
                desc,
                command=cmd,
                available=True,
                tag="",
                tag_fg=AMBER_D,
                tag_bg=BG2,
                title_width=22,
            )
            self._stat_tags[stat_key] = row.winfo_children()[-1]

        split = tk.Frame(panel, bg=BG)
        split.pack(fill="both", expand=True, pady=(12, 0))
        split.grid_columnconfigure(0, weight=3, uniform="deploy_split")
        split.grid_columnconfigure(1, weight=2, uniform="deploy_split")
        split.grid_rowconfigure(0, weight=1)

        left = tk.Frame(split, bg=BG, highlightbackground=BORDER, highlightthickness=1)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        hrow = tk.Frame(left, bg=BG)
        hrow.pack(fill="x")
        for label, width in _LIST_COLS:
            tk.Label(hrow, text=label, font=(FONT, 7, "bold"), fg=DIM, bg=BG, width=width, anchor="w").pack(side="left")
        tk.Frame(left, bg=DIM2, height=1).pack(fill="x", pady=(1, 2))

        list_canvas = tk.Canvas(left, bg=BG, highlightthickness=0)
        list_sb = tk.Scrollbar(left, orient="vertical", command=list_canvas.yview)
        self._list_frame = tk.Frame(list_canvas, bg=BG)
        self._list_frame.bind("<Configure>", lambda _e: list_canvas.configure(scrollregion=list_canvas.bbox("all")))
        list_canvas.create_window((0, 0), window=self._list_frame, anchor="nw")
        list_canvas.configure(yscrollcommand=list_sb.set)
        list_canvas.pack(side="left", fill="both", expand=True)
        list_sb.pack(side="right", fill="y")
        self._list_canvas = list_canvas

        def _list_wheel(event: tk.Event) -> None:
            try:
                list_canvas.yview_scroll(-1 * (event.delta // 120), "units")
            except Exception:
                pass

        self._bind(list_canvas, "<Enter>", lambda _e: list_canvas.bind_all("<MouseWheel>", _list_wheel))
        self._bind(list_canvas, "<Leave>", lambda _e: list_canvas.unbind_all("<MouseWheel>"))

        right = tk.Frame(split, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        right.grid(row=0, column=1, sticky="nsew")
        tk.Label(right, text="DETAILS", font=(FONT, 7, "bold"), fg=AMBER_D, bg=PANEL, anchor="w").pack(anchor="nw", padx=10, pady=(10, 4))
        tk.Frame(right, bg=DIM2, height=1).pack(fill="x", padx=10, pady=(0, 6))
        self._detail_frame = tk.Frame(right, bg=PANEL)
        self._detail_frame.pack(fill="both", expand=True, padx=10, pady=(2, 10))

        app._ui_back_row(panel, app._terminal)

    def on_enter(self, **kwargs: Any) -> None:
        del kwargs
        app = self.app
        app.h_path.configure(text="> TERMINAL > DEPLOY")
        app.h_stat.configure(text="PIPELINE", fg=AMBER_D)
        app.f_lbl.configure(text="ESC terminal  |  B backtest  |  V validated  |  P paper  |  C cockpit  |  R refresh")
        app._kb("<Escape>", app._terminal)
        app._kb("<Key-0>", app._terminal)
        app._bind_global_nav()

        for key_label, cmd in {
            "b": app._strategies_backtest,
            "v": app._data_backtests,
            "p": self._start_selected_candidate,
            "c": self._open_selected_cockpit,
            "h": app._data_runs_history,
            "e": app._data_engines,
            "r": self._refresh,
        }.items():
            app._kb(f"<Key-{key_label}>", cmd)
            app._kb(f"<Key-{key_label.upper()}>", cmd)

        self._refresh()

    def _get_snapshot(self, force: bool = False) -> dict[str, Any]:
        now = time.monotonic()
        if not force and self._snapshot_cache is not None and (now - self._snapshot_cache[0]) < self._TTL_SEC:
            return self._snapshot_cache[1]
        snap = deploy_pipeline.pipeline_snapshot()
        self._snapshot_cache = (now, snap)
        return snap

    def _refresh(self) -> None:
        snap = self._get_snapshot(force=True)
        total_runs = int(snap.get("total_runs") or 0)
        candidates = list(snap.get("candidates") or [])
        paper_label = deploy_pipeline.candidate_label(snap.get("paper_candidate"))
        bootstrap_label = deploy_pipeline.candidate_label(snap.get("bootstrap_candidate"))
        if self._subtitle_label is not None:
            self._subtitle_label.configure(
                text=(
                    f"{total_runs} runs no DB"
                    f"  |  shortlist: {len(candidates)} engines"
                    f"  |  paper-ready: {paper_label}"
                    f"  |  bootstrap: {bootstrap_label}"
                )
            )

        stats = {
            "backtest": "picker inline",
            "validated": f"{total_runs} rows",
            "paper": paper_label,
            "cockpit": bootstrap_label if bootstrap_label != "none" else "paper / shadow",
            "history": "local + VPS + DB",
            "engines": "live tail",
        }
        for key, value in stats.items():
            lbl = self._stat_tags.get(key)
            if lbl is not None:
                lbl.configure(text=f" {value} ")

        self._current_candidates = candidates
        if self._list_frame is None:
            return
        for child in self._list_frame.winfo_children():
            child.destroy()
        if not candidates:
            tk.Label(self._list_frame, text="  no deploy candidates in the validated DB.", font=(FONT, 9), fg=DIM, bg=BG, anchor="w").pack(fill="x", pady=8)
            self._selected_slug = None
            self._render_detail(None)
            return

        for candidate in candidates:
            self._render_row(candidate)

        if self._selected_slug not in {c.slug for c in candidates}:
            self._selected_slug = candidates[0].slug
        self._render_detail(self._find_selected())

    def _render_row(self, candidate: deploy_pipeline.DeployCandidate) -> None:
        if self._list_frame is None:
            return
        selected = candidate.slug == self._selected_slug
        row_bg = BG3 if selected else BG
        row = tk.Frame(self._list_frame, bg=row_bg, cursor="hand2")
        row.pack(fill="x", padx=2, pady=1)
        row.bind("<Button-1>", lambda _e, slug=candidate.slug: self._select(slug))

        stage_text = deploy_pipeline.stage_badge(candidate)[:11]
        roi_text = f"{candidate.roi:+.2f}%" if candidate.roi is not None else "--"
        sh_text = f"{candidate.sharpe:.2f}" if candidate.sharpe is not None else "--"
        run_text = candidate.run_id[:17] if candidate.run_id else "-"
        roi_color = WHITE if candidate.roi is None else (AMBER if candidate.roi >= 0 else DIM)
        sh_color = WHITE if candidate.sharpe is None else (AMBER if candidate.sharpe >= 0 else DIM)

        cols = [
            (stage_text, AMBER_D, _LIST_COLS[0][1]),
            (candidate.display[:11], AMBER, _LIST_COLS[1][1]),
            (roi_text, roi_color, _LIST_COLS[2][1]),
            (sh_text, sh_color, _LIST_COLS[3][1]),
            (run_text, DIM, _LIST_COLS[4][1]),
        ]
        for text, color, width in cols:
            lbl = tk.Label(row, text=text, font=(FONT, 8), fg=color, bg=row_bg, width=width, anchor="w")
            lbl.pack(side="left")
            lbl.bind("<Button-1>", lambda _e, slug=candidate.slug: self._select(slug))

    def _select(self, slug: str) -> None:
        self._selected_slug = slug
        self._refresh()

    def _find_selected(self) -> deploy_pipeline.DeployCandidate | None:
        return next((c for c in self._current_candidates if c.slug == self._selected_slug), None)

    def _render_detail(self, candidate: deploy_pipeline.DeployCandidate | None) -> None:
        if self._detail_frame is None:
            return
        for child in self._detail_frame.winfo_children():
            child.destroy()
        if candidate is None:
            tk.Label(self._detail_frame, text="select a candidate", font=(FONT, 9), fg=DIM, bg=PANEL).pack(anchor="w")
            return

        tk.Label(self._detail_frame, text=f"{candidate.display} / {deploy_pipeline.stage_badge(candidate)}", font=(FONT, 10, "bold"), fg=AMBER, bg=PANEL, anchor="w").pack(anchor="w")
        tk.Label(self._detail_frame, text=candidate.run_id or "-", font=(FONT, 8), fg=DIM, bg=PANEL, anchor="w").pack(anchor="w", pady=(0, 8))

        self._detail_section("IDENTITY", [
            ("engine", candidate.slug),
            ("stage", candidate.stage),
            ("timestamp", candidate.timestamp[:19] if candidate.timestamp else "-"),
            ("interval", candidate.interval or "-"),
            ("days", str(candidate.scan_days) if candidate.scan_days is not None else "-"),
            ("basket", candidate.basket or "-"),
        ])
        self._detail_section("BACKTEST METRICS", [
            ("roi", f"{candidate.roi:+.2f}%" if candidate.roi is not None else "--"),
            ("sharpe", f"{candidate.sharpe:.2f}" if candidate.sharpe is not None else "--"),
            ("sortino", f"{candidate.sortino:.2f}" if candidate.sortino is not None else "--"),
            ("max_dd", f"{candidate.max_dd:.2f}" if candidate.max_dd is not None else "--"),
            ("symbols", str(candidate.n_symbols) if candidate.n_symbols is not None else "-"),
            ("leverage", f"{candidate.leverage:.2f}x" if candidate.leverage is not None else "-"),
        ])
        self._detail_section("DEPLOY PATH", [
            ("launch", deploy_pipeline.launch_hint(candidate)),
            ("paper ready", "yes" if candidate.can_paper else "no"),
            ("bootstrap", "yes" if candidate.needs_cockpit else "no"),
        ])

        actions = tk.Frame(self._detail_frame, bg=PANEL)
        actions.pack(fill="x", pady=(10, 0))
        action_specs = [
            ("PAPER", self._start_selected_candidate, AMBER if candidate.can_paper else DIM),
            ("COCKPIT", self._open_selected_cockpit, AMBER_D),
            ("BACKTESTS", self.app._data_backtests, WHITE),
            ("HISTORY", self.app._data_runs_history, DIM),
            ("LOGS", self.app._data_engines, DIM),
        ]
        for label, cmd, color in action_specs:
            b = tk.Label(actions, text=f"  {label}  ", font=(FONT, 8, "bold"), fg=color, bg=BG3, cursor="hand2", padx=8, pady=3)
            b.pack(side="left", padx=(0, 6))
            b.bind("<Button-1>", lambda _e, c=cmd: c())

    def _detail_section(self, title: str, rows: list[tuple[str, str]]) -> None:
        if self._detail_frame is None:
            return
        tk.Label(self._detail_frame, text=title, font=(FONT, 8, "bold"), fg=AMBER_D, bg=PANEL, anchor="w").pack(anchor="w", pady=(6, 2))
        tk.Frame(self._detail_frame, bg=DIM2, height=1).pack(fill="x")
        for key, value in rows:
            row = tk.Frame(self._detail_frame, bg=PANEL)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=f"  {key}", font=(FONT, 8), fg=DIM, bg=PANEL, anchor="w", width=18).pack(side="left")
            tk.Label(row, text=str(value), font=(FONT, 8), fg=WHITE, bg=PANEL, anchor="w").pack(side="left")

    def _start_selected_candidate(self) -> None:
        deploy_pipeline.start_candidate(self.app, self._find_selected())

    def _open_selected_cockpit(self) -> None:
        deploy_pipeline.open_live_cockpit(self.app, self._find_selected())
