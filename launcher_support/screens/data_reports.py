"""DataReportsScreen for raw persisted artifact browsing."""
from __future__ import annotations

import tkinter as tk
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from core.ui.ui_palette import AMBER, AMBER_B, AMBER_D, BG, BG2, BG3, DIM, DIM2, FONT, GREEN, WHITE
from launcher_support.screens.base import Screen


class DataReportsScreen(Screen):
    _REPORTS_TTL_SEC = 10.0

    def __init__(self, parent: tk.Misc, app: Any, root_path: Path):
        super().__init__(parent)
        self.app = app
        self.root_path = root_path
        self._total_label: tk.Label | None = None
        self._count_labels: dict[str, tk.Label] = {}
        self._rows_host: tk.Frame | None = None
        self._reports_cache: tuple[float, list[tuple[Path, Any, str]]] | None = None

    def build(self) -> None:
        outer = tk.Frame(self.container, bg=BG)
        outer.pack(fill="both", expand=True, padx=28, pady=18)

        head = tk.Frame(outer, bg=BG)
        head.pack(fill="x", pady=(0, 12))
        strip = tk.Frame(head, bg=BG)
        strip.pack(fill="x")
        tk.Frame(strip, bg=AMBER, width=4, height=28).pack(side="left", padx=(0, 8))

        title_wrap = tk.Frame(strip, bg=BG)
        title_wrap.pack(side="left", fill="x", expand=True)
        tk.Label(
            title_wrap,
            text="DATA & REPORTS",
            font=(FONT, 14, "bold"),
            fg=AMBER,
            bg=BG,
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            title_wrap,
            text="Indexed JSON and report artifacts across the data tree",
            font=(FONT, 8),
            fg=DIM,
            bg=BG,
            anchor="w",
        ).pack(anchor="w", pady=(3, 0))

        tk.Frame(outer, bg=BG2, height=6).pack(fill="x")
        tk.Frame(outer, bg=DIM2, height=1).pack(fill="x", pady=(0, 12))

        app = self.app
        panel = app._ui_panel_frame(
            outer,
            "ARTIFACT INDEX",
            "Recent persisted files across runs and legacy engine directories",
        )

        meta = tk.Frame(panel, bg=BG)
        meta.pack(fill="x", pady=(0, 8))
        self._total_label = tk.Label(
            meta,
            text="TOTAL  0",
            font=(FONT, 8, "bold"),
            fg=AMBER_D,
            bg=BG,
        )
        self._total_label.pack(side="left")
        for sec_name in ("RUNS", "ARBITRAGE", "DARWIN", "LEGACY"):
            lbl = tk.Label(meta, text="", font=(FONT, 8), fg=DIM, bg=BG)
            lbl.pack(side="left", padx=(16, 0))
            self._count_labels[sec_name] = lbl
        tk.Frame(panel, bg=DIM2, height=1).pack(fill="x", pady=(0, 8))
        app._ui_note(
            panel,
            "Artifact index is chronological. Open BACKTESTS for validated run review; use this screen for raw persisted files.",
            fg=DIM,
        )

        routes = app._ui_section(panel, "ROUTES", note="review and drill-down")
        app._ui_action_row(
            routes,
            "B",
            "BACKTESTS",
            "Open validated run browser with metrics and detail panel",
            command=app._data_backtests,
            tag="PRIMARY",
            tag_fg=AMBER_D,
            tag_bg=BG,
            title_width=18,
        )
        app._ui_action_row(
            routes,
            "E",
            "ENGINE LOGS",
            "Open running-engine log tail and process inspection",
            command=app._data_engines,
            tag="OPERATIONS",
            tag_fg=AMBER_D,
            tag_bg=BG,
            title_width=18,
        )

        canvas = tk.Canvas(panel, bg=BG, highlightthickness=0)
        sb = tk.Scrollbar(panel, orient="vertical", command=canvas.yview)
        sf = tk.Frame(canvas, bg=BG)
        sf.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        window_id = canvas.create_window((0, 0), window=sf, anchor="nw")
        app._bind_canvas_window_width(canvas, window_id, pad_x=6)
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True, padx=(14, 0), pady=(0, 14))
        sb.pack(side="right", fill="y", padx=(0, 14), pady=(0, 14))

        tk.Label(
            sf,
            text=f"  {'SECTION':<10} {'FILE':<60} {'DATE':<15} {'SIZE':>8}",
            font=(FONT, 7, "bold"),
            fg=AMBER_D,
            bg=BG,
            anchor="w",
        ).pack(fill="x")
        tk.Frame(sf, bg=DIM2, height=1).pack(fill="x", pady=1)

        self._rows_host = sf
        app._ui_back_row(panel, lambda: app._menu("main"))

    def on_enter(self, **kwargs: Any) -> None:
        del kwargs
        app = self.app
        app.h_path.configure(text="> DATA")
        app.h_stat.configure(text="BROWSE", fg=AMBER_D)
        app.f_lbl.configure(text="ESC back  |  click to open file  |  latest 200 indexed artifacts")
        app._kb("<Escape>", lambda: app._menu("main"))
        app._kb("<Key-b>", app._data_backtests)
        app._kb("<Key-e>", app._data_engines)

        rows_host = self._rows_host
        if rows_host is None:
            return

        reports = self._collect_reports()
        counts: dict[str, int] = {}
        for _, _, section in reports:
            counts[section] = counts.get(section, 0) + 1

        if self._total_label is not None:
            self._total_label.configure(text=f"TOTAL  {len(reports)}")
        for sec_name, lbl in self._count_labels.items():
            n = counts.get(sec_name, 0)
            lbl.configure(text=f"{sec_name}  {n}" if n else "")

        for child in rows_host.winfo_children()[2:]:
            try:
                child.destroy()
            except Exception:
                pass

        if not reports:
            tk.Label(rows_host, text="  No reports found.", font=(FONT, 9), fg=DIM, bg=BG).pack(anchor="w", pady=8)
            return

        sec_color = {
            "RUNS": AMBER,
            "DARWIN": GREEN,
            "ARBITRAGE": AMBER_B,
            "LEGACY": DIM,
        }

        for report_path, st, section in reports[:200]:
            try:
                rel = str(report_path.relative_to(self.root_path))
            except ValueError:
                rel = str(report_path)
            mt = datetime.fromtimestamp(st.st_mtime).strftime("%m-%d %H:%M")
            sz = (
                f"{st.st_size/1024:.0f}K"
                if st.st_size < 1024 * 1024
                else f"{st.st_size/(1024*1024):.1f}M"
            )
            col = sec_color.get(section, WHITE)

            row = tk.Frame(rows_host, bg=BG, cursor="hand2")
            row.pack(fill="x")
            sec_lbl = tk.Label(
                row,
                text=f" {section:<9}",
                font=(FONT, 7, "bold"),
                fg=col,
                bg=BG,
                width=10,
                anchor="w",
            )
            sec_lbl.pack(side="left")
            name_lbl = tk.Label(row, text=f" {rel:<60}", font=(FONT, 7), fg=DIM, bg=BG, anchor="w")
            name_lbl.pack(side="left")
            date_lbl = tk.Label(row, text=f" {mt:<15}", font=(FONT, 7), fg=DIM, bg=BG, anchor="w")
            date_lbl.pack(side="left")
            size_lbl = tk.Label(row, text=f" {sz:>8}", font=(FONT, 7), fg=DIM, bg=BG, anchor="e")
            size_lbl.pack(side="left")
            tk.Frame(row, bg=DIM2, height=1).pack(side="bottom", fill="x")

            labels = (sec_lbl, name_lbl, date_lbl, size_lbl)

            def _enter(_e=None, labels=labels, n=name_lbl) -> None:
                for lbl in labels:
                    try:
                        lbl.configure(bg=BG3)
                    except tk.TclError:
                        pass
                try:
                    n.configure(fg=WHITE)
                except tk.TclError:
                    pass

            def _leave(_e=None, labels=labels, n=name_lbl) -> None:
                for lbl in labels:
                    try:
                        lbl.configure(bg=BG)
                    except tk.TclError:
                        pass
                try:
                    n.configure(fg=DIM)
                except tk.TclError:
                    pass

            for widget in (row, *labels):
                widget.bind("<Enter>", _enter)
                widget.bind("<Leave>", _leave)
                widget.bind("<Button-1>", lambda _e, p=report_path: app._open_file(p))

    def _collect_reports(self) -> list[tuple[Path, Any, str]]:
        cache = self._reports_cache
        now = time.monotonic()
        if cache is not None and (now - cache[0]) < self._REPORTS_TTL_SEC:
            return list(cache[1])

        reports: list[tuple[Path, Any, str]] = []
        data_dir = self.root_path / "data"

        def _collect(root: Path, section: str, pattern: str = "*.json") -> None:
            if not root.exists():
                return
            for report in root.rglob(pattern):
                try:
                    reports.append((report, report.stat(), section))
                except (OSError, FileNotFoundError):
                    continue

        if data_dir.exists():
            _collect(data_dir / "runs", "RUNS")
            _collect(data_dir / "darwin", "DARWIN")
            _collect(data_dir / "arbitrage", "ARBITRAGE")
            for legacy in ("mercurio", "newton", "thoth", "prometeu", "multistrategy", "live"):
                _collect(data_dir / legacy, legacy.upper())
            for dated in data_dir.iterdir():
                if dated.is_dir() and dated.name[:4].isdigit() and (dated / "reports").exists():
                    _collect(dated / "reports", "LEGACY")
            reports.sort(key=lambda entry: entry[1].st_mtime, reverse=True)
        self._reports_cache = (now, list(reports))
        return reports
