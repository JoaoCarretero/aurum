"""Results dashboard entry — locates latest report, builds tab strip.

Extracted from launcher.App._show_results. render(app, parent_menu,
run_id=None) resolves the requested run's JSON + price_data, parks
state on the App instance (_results_* attrs), and mounts a tabbed
dashboard. Tab 1 (Overview) is rendered by screens.results_overview;
tab 2 (Trades) stays on App (_results_build_trades) until a later
extraction moves it too.
"""
from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path

from core.ui.ui_palette import (
    AMBER, AMBER_D,
    BG,
    DIM, DIM2, FONT,
    GREEN, RED,
)

_SKIP_NAMES = {
    "config.json", "equity.json", "index.json", "overfit.json",
    "price_data.json", "summary.json", "trades.json",
}


def render(app, parent_menu, run_id=None):
    """Build the results dashboard for ``run_id`` or the latest run.

    Report-location precedence:
      1. Explicit ``run_id`` via app._bt_resolve_run()
      2. Newest mtime under data/runs/<run_id>/*.json
      3. Legacy layout: data/<engine>/<run_id>/reports/*.json

    Once a report is loaded:
      - data/trades list filtered to closed (WIN/LOSS)
      - Parks state on App: _results_data / _results_report /
        _results_run_dir / _results_trades / _results_filtered /
        _results_active_idx / _results_filter / _results_tab /
        _results_tab_btns / _results_body + related widget handles
      - Renders title + tab strip, then invokes the Overview tab
    """
    # ROOT is launcher.py module-level — pull lazily to avoid cycle
    import launcher as _launcher_mod
    ROOT = _launcher_mod.ROOT

    app._clr()
    app._clear_kb()
    app._results_parent_menu = parent_menu
    app.h_stat.configure(text="RESULTADOS", fg=GREEN)
    app.f_lbl.configure(
        text="ESC voltar  |  1 overview  2 trades  |  ← → navegar trade")
    app._kb("<Escape>", lambda: app._menu(parent_menu))
    app._kb("<Key-1>", lambda: app._results_render_tab("overview"))
    app._kb("<Key-2>", lambda: app._results_render_tab("trades"))
    app._kb("<Left>", lambda: app._results_prev_trade())
    app._kb("<Up>", lambda: app._results_prev_trade())
    app._kb("<Right>", lambda: app._results_next_trade())
    app._kb("<Down>", lambda: app._results_next_trade())

    # Locate the requested run (preferred) or latest run + its exported JSON.
    # New layout (preferred): data/runs/<run_id>/<engine>_*.json  (run_dir = parent)
    # Legacy layout (fallback): data/<engine>/<run_id>/reports/<engine>_*.json
    report = None
    run_dir = None

    if run_id:
        run_meta = app._bt_resolve_run(run_id)
        report_path = str(run_meta.get("report_json_path") or "").strip()
        run_dir_path = str(run_meta.get("run_dir") or "").strip()
        if report_path:
            cand = Path(report_path)
            if cand.exists():
                report = cand
        if run_dir_path:
            cand_dir = Path(run_dir_path)
            if cand_dir.exists():
                run_dir = cand_dir
        if report is None and run_dir is not None:
            candidates = sorted(
                [p for p in run_dir.glob("*.json") if p.name not in _SKIP_NAMES],
                key=lambda p: p.stat().st_mtime, reverse=True,
            )
            if candidates:
                report = candidates[0]

    if report is None:
        runs_root = ROOT / "data" / "runs"
        if runs_root.exists():
            run_dirs = sorted(
                [d for d in runs_root.iterdir() if d.is_dir()],
                key=lambda p: p.stat().st_mtime, reverse=True,
            )
            for rd in run_dirs:
                candidates = sorted(
                    [p for p in rd.glob("*.json") if p.name not in _SKIP_NAMES],
                    key=lambda p: p.stat().st_mtime, reverse=True,
                )
                if candidates:
                    report = candidates[0]
                    run_dir = rd
                    break

    if report is None:
        data_dir = ROOT / "data"
        legacy = sorted(
            [
                p for p in data_dir.rglob("*.json")
                if p.name not in _SKIP_NAMES and "reports" in str(p.parent)
            ],
            key=lambda p: p.stat().st_mtime, reverse=True
        )
        for r in legacy:
            report = r
            run_dir = r.parent.parent
            break

    if report is None:
        f = tk.Frame(app.main, bg=BG)
        f.pack(expand=True)
        tk.Label(f, text="Nenhum relatório encontrado.", font=(FONT, 10),
                 fg=DIM, bg=BG).pack(pady=20)
        return

    try:
        with open(report, "r", encoding="utf-8") as fj:
            data = json.load(fj)
    except Exception as e:
        f = tk.Frame(app.main, bg=BG)
        f.pack(expand=True)
        tk.Label(f, text=f"Erro ao ler relatório: {e}", font=(FONT, 9),
                 fg=RED, bg=BG).pack(pady=20)
        return

    app._results_data = data
    app._results_report = report
    app._results_run_dir = run_dir

    # Load OHLC (optional — older runs may not have it)
    app._price_data = {}
    price_path = app._results_run_dir / "price_data.json"
    if price_path.exists():
        try:
            with open(price_path, "r", encoding="utf-8") as pf:
                app._price_data = json.load(pf)
        except Exception:
            app._price_data = {}

    all_trades = data.get("trades", [])
    closed = [t for t in all_trades if t.get("result") in ("WIN", "LOSS")]
    app._results_trades = closed
    app._results_filtered = list(range(len(closed)))
    app._results_active_idx = 0
    app._results_filter = "all"
    app._results_tab = "overview"
    app._results_tab_btns = {}
    app._results_item_widgets = {}
    app._results_canvas = None
    app._results_chart_frame = None
    app._results_data_panel = None
    app._results_list_canvas = None
    app._results_list_inner = None
    app._results_counter = None
    app._results_stats = None

    # Outer layout: title bar + tab strip + tab body
    root = tk.Frame(app.main, bg=BG)
    root.pack(fill="both", expand=True)

    title = tk.Frame(root, bg=BG)
    title.pack(fill="x", padx=20, pady=(10, 4))
    tk.Label(title, text="RESULTADOS DO BACKTEST",
             font=(FONT, 12, "bold"), fg=AMBER, bg=BG).pack(side="left")
    meta = f"{data.get('version','')}  ·  {data.get('run_id','')}"
    tk.Label(title, text=meta, font=(FONT, 7), fg=DIM, bg=BG).pack(side="left", padx=10)
    n_closed = len(closed)
    wr = (sum(1 for t in closed if t.get("result") == "WIN") / n_closed * 100) if n_closed else 0
    tk.Label(title, text=f"{n_closed}t  WR {wr:.1f}%",
             font=(FONT, 8, "bold"), fg=AMBER_D, bg=BG).pack(side="right")

    # Tab strip
    strip = tk.Frame(root, bg=BG, height=30)
    strip.pack(fill="x")
    strip.pack_propagate(False)
    for tab_id, label in [("overview", "1 OVERVIEW"), ("trades", "2 TRADES")]:
        btn = tk.Label(strip, text=f" {label} ", font=(FONT, 9, "bold"),
                       fg=DIM, bg=BG, padx=14, pady=5, cursor="hand2")
        btn.pack(side="left", padx=(0, 10), pady=1)
        btn.bind("<Button-1>", lambda e, t=tab_id: app._results_render_tab(t))
        app._results_tab_btns[tab_id] = btn

    tk.Frame(root, bg=DIM2, height=1).pack(fill="x")
    app._results_body = tk.Frame(root, bg=BG)
    app._results_body.pack(fill="both", expand=True)

    app._results_render_tab("overview")
