"""Alignment Panel — visao de drift entre canon e realidade.

Layout (Toplevel 720x640):
  - Header: overall status pill + last scan timestamp + [Refresh] + [Export]
  - 5 check rows (engine_roster / path_existence / protected_files /
    staleness / paperclip_sync), cada uma com icon + summary + expandable
    details.

Zero deps extra. Pattern igual ao open_cost_dashboard (Toplevel + refresh
callback). Scan e rapido (<100ms) — roda no main thread.
"""
from __future__ import annotations

import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

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
from launcher_support.research_desk.alignment_scan import (
    AlignmentReport,
    CheckResult,
    run_alignment_scan,
)


# Status -> (text, bg color for pill, fg color).
_STATUS_PILL: dict[str, tuple[str, str, str]] = {
    "green": (" GREEN ", GREEN, BG),
    "yellow": (" YELLOW ", AMBER, BG),
    "red": (" RED ", RED, WHITE),
}


def open_alignment_modal(
    parent: tk.Misc,
    *,
    root_path: Path,
) -> "AlignmentModal":
    """Open the alignment status modal. Caller does not need to hold
    a ref — modal manages its own lifecycle via Toplevel."""
    return AlignmentModal(parent, root_path=root_path)


class AlignmentModal:
    def __init__(self, parent: tk.Misc, *, root_path: Path):
        self._root_path = root_path
        self._closed = False
        self._body_frame: tk.Frame | None = None
        self._last_report: AlignmentReport | None = None

        self.top = tk.Toplevel(parent)
        self.top.title("ALIGNMENT STATUS  ·  aurum research")
        self.top.configure(bg=BG)
        self.top.geometry("720x640")
        self.top.transient(parent)
        self.top.protocol("WM_DELETE_WINDOW", self._close)
        self.top.bind("<Escape>", lambda _e: self._close())

        self._build()
        self._refresh()

    # ── UI ───────────────────────────────────────────────────────
    def _build(self) -> None:
        outer = tk.Frame(self.top, bg=BG)
        outer.pack(fill="both", expand=True, padx=14, pady=12)

        # Header
        head = tk.Frame(outer, bg=BG)
        head.pack(fill="x", pady=(0, 8))
        tk.Frame(head, bg=AMBER, width=4, height=24).pack(side="left", padx=(0, 8))
        title_wrap = tk.Frame(head, bg=BG)
        title_wrap.pack(side="left", fill="x", expand=True)
        tk.Label(
            title_wrap, text="ALIGNMENT STATUS", font=(FONT, 12, "bold"),
            fg=AMBER, bg=BG, anchor="w",
        ).pack(anchor="w")
        self._subtitle = tk.Label(
            title_wrap, text="", font=(FONT, 8), fg=DIM, bg=BG, anchor="w",
        )
        self._subtitle.pack(anchor="w", pady=(2, 0))

        # Overall pill (right)
        self._overall_pill = tk.Label(
            head, text=" - ", font=(FONT, 8, "bold"),
            fg=BG, bg=DIM, padx=8, pady=3,
        )
        self._overall_pill.pack(side="right", padx=(8, 0))

        # Refresh + Export buttons
        btns = tk.Frame(head, bg=BG)
        btns.pack(side="right", padx=(0, 8))
        self._refresh_btn = tk.Label(
            btns, text="  REFRESH  ", font=(FONT, 7, "bold"),
            fg=BG, bg=AMBER, cursor="hand2", padx=4, pady=3,
        )
        self._refresh_btn.pack(side="left", padx=2)
        self._refresh_btn.bind("<Button-1>", lambda _e: self._refresh())

        self._export_btn = tk.Label(
            btns, text="  EXPORT  ", font=(FONT, 7, "bold"),
            fg=BG, bg=BG3, cursor="hand2", padx=4, pady=3,
        )
        self._export_btn.pack(side="left", padx=2)
        self._export_btn.bind("<Button-1>", lambda _e: self._export())

        # Separator
        tk.Frame(outer, bg=DIM, height=1).pack(fill="x", pady=(0, 8))

        # Body — rows populated by _refresh
        self._body_frame = tk.Frame(outer, bg=BG)
        self._body_frame.pack(fill="both", expand=True)

    def _refresh(self) -> None:
        if self._closed or self._body_frame is None:
            return
        # Clear body
        for w in self._body_frame.winfo_children():
            w.destroy()

        try:
            report = run_alignment_scan(repo_root=self._root_path)
        except Exception as exc:  # noqa: BLE001
            self._render_error(str(exc))
            return

        self._last_report = report

        # Update header
        pill_text, pill_bg, pill_fg = _STATUS_PILL.get(report.overall, (" ? ", DIM, BG))
        self._overall_pill.configure(text=pill_text, bg=pill_bg, fg=pill_fg)
        self._subtitle.configure(text=f"last scan: {report.timestamp}")

        # Rows
        for name, result in report.checks.items():
            self._render_row(name, result).pack(fill="x", pady=4)

    def _render_row(self, name: str, result: CheckResult) -> tk.Frame:
        assert self._body_frame is not None
        row = tk.Frame(
            self._body_frame, bg=PANEL,
            highlightbackground=BORDER, highlightthickness=1,
        )

        top = tk.Frame(row, bg=PANEL)
        top.pack(fill="x", padx=10, pady=8)

        status_color = {"green": GREEN, "yellow": AMBER, "red": RED}.get(result.status, DIM)
        tk.Label(
            top, text="●", font=(FONT, 14, "bold"), fg=status_color, bg=PANEL,
        ).pack(side="left")
        tk.Label(
            top, text=name.replace("_", " ").upper(),
            font=(FONT, 9, "bold"), fg=WHITE, bg=PANEL, anchor="w",
        ).pack(side="left", padx=(8, 12))
        tk.Label(
            top, text=result.summary, font=(FONT, 8),
            fg=DIM, bg=PANEL, anchor="w",
        ).pack(side="left", fill="x", expand=True)

        if result.details:
            # Expander toggle
            detail_frame = tk.Frame(row, bg=BG2)
            toggle_state = {"open": False}
            toggle_btn = tk.Label(
                top,
                text=f"▸ {len(result.details)}",
                font=(FONT, 7, "bold"),
                fg=AMBER_D, bg=PANEL, cursor="hand2",
            )
            toggle_btn.pack(side="right")

            def toggle(_e=None):
                if toggle_state["open"]:
                    detail_frame.pack_forget()
                    toggle_btn.configure(text=f"▸ {len(result.details)}")
                    toggle_state["open"] = False
                else:
                    detail_frame.pack(fill="x", padx=10, pady=(0, 8))
                    toggle_btn.configure(text=f"▾ {len(result.details)}")
                    toggle_state["open"] = True

            toggle_btn.bind("<Button-1>", toggle)

            tk.Frame(detail_frame, bg=DIM2, height=1).pack(fill="x", pady=(0, 4))
            for detail in result.details[:30]:
                line = _format_detail(detail)
                tk.Label(
                    detail_frame, text=f"  · {line}",
                    font=(FONT, 7), fg=WHITE, bg=BG2,
                    anchor="w", justify="left", wraplength=640,
                ).pack(anchor="w", padx=4, pady=1)
            if len(result.details) > 30:
                tk.Label(
                    detail_frame,
                    text=f"  ... +{len(result.details) - 30} mais",
                    font=(FONT, 7, "italic"), fg=DIM, bg=BG2, anchor="w",
                ).pack(anchor="w", padx=4, pady=1)

        return row

    def _render_error(self, msg: str) -> None:
        assert self._body_frame is not None
        tk.Label(
            self._body_frame,
            text=f"Scan falhou: {msg}",
            font=(FONT, 9), fg=RED, bg=BG, anchor="w",
        ).pack(fill="x", padx=8, pady=16)

    def _export(self) -> None:
        """Serialize current report to docs/audits/repo/YYYY-MM-DD_alignment.md."""
        if self._closed or self._last_report is None:
            return
        report = self._last_report
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        out_dir = self._root_path / "docs" / "audits" / "repo"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{today}_alignment.md"
        try:
            out_path.write_text(_render_markdown(report), encoding="utf-8")
        except OSError as exc:
            self._flash(f"Export falhou: {exc}", color=RED)
            return
        self._flash(f"Salvo em {out_path.relative_to(self._root_path)}", color=GREEN)

    def _flash(self, msg: str, *, color: str) -> None:
        """Briefly update subtitle with feedback message."""
        orig = self._subtitle.cget("text")
        self._subtitle.configure(text=msg, fg=color)
        self.top.after(3000, lambda: self._subtitle.configure(text=orig, fg=DIM))

    def _close(self) -> None:
        self._closed = True
        try:
            self.top.destroy()
        except tk.TclError:
            pass


# ── Helpers ──────────────────────────────────────────────────────
def _format_detail(detail: dict) -> str:
    """Format a check detail dict into a single-line string for display."""
    # Prioritize specific keys known per check; fall back to generic join.
    if "engine" in detail:
        files = ", ".join(detail.get("files", []))
        return f"{detail['engine']}  ←  {files}"
    if "path" in detail and "cited_in" in detail:
        cited = ", ".join(detail["cited_in"])
        return f"{detail['path']}  ←  {cited}"
    if "path" in detail:
        return detail["path"]
    if "agent" in detail:
        reason = detail.get("reason", "?")
        extra = detail.get("first_line", "")
        return f"{detail['agent']}: {reason}{(' — ' + extra) if extra else ''}"
    if "persona" in detail:
        return f"{detail['persona']} ({detail.get('days_behind_canon', '?')}d)"
    # Fallback
    return ", ".join(f"{k}={v}" for k, v in detail.items())


def _render_markdown(report: AlignmentReport) -> str:
    """Serialize an AlignmentReport as a human-readable markdown document."""
    lines: list[str] = []
    lines.append(f"# Alignment audit — {report.timestamp}")
    lines.append("")
    lines.append(f"**Overall:** `{report.overall.upper()}`")
    lines.append("")

    for name, result in report.checks.items():
        lines.append(f"## {name.replace('_', ' ')} — `{result.status.upper()}`")
        lines.append("")
        lines.append(result.summary)
        lines.append("")
        if result.details:
            for d in result.details:
                lines.append(f"- {_format_detail(d)}")
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("Gerado por `launcher_support/research_desk/alignment_scan.py`.")
    return "\n".join(lines)
