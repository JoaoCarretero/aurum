"""RiskScreen for the RISK routing console.

Surfaces:
- PORTFOLIO basics (positions, P&L, exposure) — placeholder dashboards
- RISK METRICS — sourced from roadmap (area=RISK), click → roadmap deep-link
- COMPLIANCE & AUDIT — sourced from roadmap (area=COMPLIANCE)
- ALREADY SHIPPED — kill-switch / audit_trail / key_store (Fase 3)

Items in RISK METRICS / COMPLIANCE come from
``launcher_support/roadmap_data.py`` so they stay in sync with the
ROADMAP screen. Clicking a row opens ROADMAP focused on that item's
detail panel via deep-link.
"""
from __future__ import annotations

import tkinter as tk
from typing import Any

from core.ui.ui_palette import (
    AMBER, AMBER_B, AMBER_D, BG, BG2, CYAN, DIM, FONT, GREEN,
)
from launcher_support.roadmap_data import by_area
from launcher_support.screens.base import Screen


_STATUS_TAG_BG = {
    "PLANNED":     BG2,
    "SCAFFOLDED":  CYAN,
    "IN_PROGRESS": AMBER_B,
    "DONE":        GREEN,
}


class RiskScreen(Screen):
    def __init__(self, parent: tk.Misc, app: Any):
        super().__init__(parent)
        self.app = app

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
            text="RISK CONSOLE",
            font=(FONT, 14, "bold"),
            fg=AMBER,
            bg=BG,
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            title_wrap,
            text="Portfolio and risk management surfaces",
            font=(FONT, 8),
            fg=DIM,
            bg=BG,
            anchor="w",
        ).pack(anchor="w", pady=(3, 0))

        tk.Frame(outer, bg=BG2, height=6).pack(fill="x")
        tk.Frame(outer, bg=DIM, height=1).pack(fill="x", pady=(0, 12))

        app = self.app
        panel = app._ui_panel_frame(
            outer,
            "RISK ROUTER",
            "Current dashboards, planned modules and shipped foundations",
        )

        # ── PORTFOLIO (basic dashboards, not roadmap items) ─────────
        sec = app._ui_section(panel, "PORTFOLIO")
        for key_label, name, desc in [
            ("1", "Open Positions", "All active positions across venues"),
            ("2", "P&L Today", "Real-time daily P&L"),
            ("3", "P&L History", "Historical equity curve"),
            ("4", "Exposure Map", "Sector/asset heatmap"),
        ]:
            app._ui_action_row(
                sec, key_label, name, desc,
                available=False, tag="COMING SOON",
                tag_fg=DIM, tag_bg=BG2, title_width=22,
            )

        # ── RISK METRICS (roadmap area=RISK, deep-linked) ───────────
        sec = app._ui_section(panel, "RISK METRICS")
        risk_items = by_area("RISK")
        for idx, item in enumerate(risk_items, start=5):
            self._roadmap_row(sec, str(idx)[-1] if idx < 10 else chr(ord("A") + idx - 10),
                              item)

        # ── COMPLIANCE & AUDIT (roadmap area=COMPLIANCE) ────────────
        sec = app._ui_section(panel, "COMPLIANCE & AUDIT")
        compliance_items = by_area("COMPLIANCE")
        for idx, item in enumerate(compliance_items):
            label = chr(ord("F") + idx)  # F G H I ...
            self._roadmap_row(sec, label, item)

        # ── ALREADY SHIPPED (Fase 3 — surfacing what exists) ────────
        sec = app._ui_section(panel, "ALREADY SHIPPED")
        for key_label, name, desc in [
            ("K", "Kill Switch (3-layer)",
             "DD velocity · consecutive losses · API latency anomaly"),
            ("L", "Audit Trail",
             "Append-only JSONL · SHA-256 hash chain · per-engine writer"),
            ("M", "Key Store",
             "Encrypted-at-rest · PBKDF2 · memory-only after unlock"),
        ]:
            app._ui_action_row(
                sec, key_label, name, desc,
                available=True, tag="LIVE",
                tag_fg=BG, tag_bg=GREEN, title_width=22,
            )

        # ── FULL ROADMAP entry point ────────────────────────────────
        sec = app._ui_section(panel, "FULL ROADMAP")
        app._ui_action_row(
            sec, "R", "Open Roadmap",
            "All capabilities — institutional · differentiator · cutting-edge",
            command=app._roadmap, available=True,
            tag="ROADMAP", tag_fg=AMBER_D, tag_bg=BG2, title_width=22,
        )

        app._ui_note(
            panel,
            "Risk console modules in development — click any row above for full plan.",
            fg=DIM,
        )
        app._ui_note(
            panel,
            "Backtest stress tests remain available in STRATEGIES > MILLENNIUM.",
            fg=AMBER_D,
        )
        app._ui_back_row(panel, lambda: app._menu("main"))

    def _roadmap_row(self, parent: tk.Misc, key_label: str,
                     item: dict[str, Any]) -> None:
        """Render a row sourced from roadmap_data, deep-linked on click."""
        app = self.app
        status = item["status"]
        tag_bg = _STATUS_TAG_BG.get(status, BG2)
        tag_fg = BG if status in ("DONE", "IN_PROGRESS") else AMBER_D
        if status == "PLANNED":
            tag_fg = DIM
        app._ui_action_row(
            parent,
            key_label,
            f"{item['sigil']} {item['name']}",
            item["summary"],
            command=lambda i=item["id"]: app._roadmap(item_id=i),
            available=True,
            tag=status,
            tag_fg=tag_fg,
            tag_bg=tag_bg,
            title_width=26,
        )

    def on_enter(self, **kwargs: Any) -> None:
        del kwargs
        app = self.app
        app.h_path.configure(text="> RISK")
        app.h_stat.configure(text="CONSOLE", fg=AMBER_D)
        app.f_lbl.configure(text="ESC voltar  |  R roadmap  |  H hub")
        app._kb("<Escape>", lambda: app._menu("main"))
        app._kb("<Key-0>", lambda: app._menu("main"))
        app._kb("<Key-r>", app._roadmap)
        app._bind_global_nav()
