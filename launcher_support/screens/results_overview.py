"""Results OVERVIEW tab — metrics, equity curve, Monte Carlo, regime.

Extracted from launcher.App._results_build_overview. Same interface:
render(app, parent) mounts the Overview tab into ``parent``. Reads run
state from the App (_results_data / _results_trades / _results_run_dir /
_results_parent_menu) and calls back into helpers (_normalize_summary,
_bind_canvas_window_width, _open_file, _results_render_tab, _menu) via
the ``app`` parameter.

The App-class method is a 2-line delegate — no signature change, no
dispatch rewiring.
"""
from __future__ import annotations

import tkinter as tk

from core.ui.scroll import bind_mousewheel
from core.ui.ui_palette import (
    AMBER, AMBER_D,
    BG, BG2, BG3,
    DIM, DIM2, FONT,
    GREEN, PANEL, RED, WHITE,
)


def render(app, parent):
    """Build and pack the Results → OVERVIEW tab into ``parent``.

    Two-row key metric card grid, per-strategy breakdown (for MILLENNIUM
    multi-engine runs), equity curve, Monte Carlo paths + distribution,
    per-regime performance, and an action row.
    """
    data = app._results_data
    s = app._normalize_summary(data)
    mc = data.get("monte_carlo", {})
    bm = data.get("bear_market", {})
    eq = data.get("equity", [])

    f = tk.Frame(parent, bg=BG)
    f.pack(fill="both", expand=True)
    canvas = tk.Canvas(f, bg=BG, highlightthickness=0)
    sb = tk.Scrollbar(f, orient="vertical", command=canvas.yview)
    sf = tk.Frame(canvas, bg=BG)
    sf.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    window_id = canvas.create_window((0, 0), window=sf, anchor="nw")
    app._bind_canvas_window_width(canvas, window_id, pad_x=4)
    canvas.configure(yscrollcommand=sb.set)
    canvas.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")

    bind_mousewheel(canvas)

    pad = 24

    # -- KEY METRICS --
    # Two rows: performance (top) + risk (bottom) — previously only 6 cards
    # crammed into one row, so Calmar / Max DD / Avg R / MaxStreak weren't
    # visible. Summary payloads now include them; surface them here.
    pnl = s.get("total_pnl", 0) or 0
    roi = s.get("ret", 0) or 0
    pnl_color = GREEN if pnl >= 0 else RED
    calmar = s.get("calmar", data.get("calmar")) or 0
    mdd = s.get("max_dd_pct", data.get("max_dd_pct")) or 0
    # Max consec losses + avg R-multiple: pull from summary block first,
    # then computed-from-trades fallback so legacy reports still render.
    summary_block = data.get("summary") or {}
    max_streak = summary_block.get("max_consec_losses")
    if max_streak is None:
        cur = 0
        _ms = 0
        for t in sorted(app._results_trades,
                        key=lambda x: x.get("timestamp", "")):
            if t.get("result") == "LOSS":
                cur += 1
                _ms = max(_ms, cur)
            else:
                cur = 0
        max_streak = _ms
    rms = [t.get("r_multiple") for t in app._results_trades
           if t.get("r_multiple") is not None]
    avg_r = sum(rms) / len(rms) if rms else 0.0

    perf_row = [
        (f"+${pnl:,.0f}" if pnl >= 0 else f"-${abs(pnl):,.0f}", "PnL TOTAL", pnl_color),
        (f"{roi:+.1f}%", "ROI", pnl_color),
        (f"{s.get('sharpe', 0) or 0:.2f}", "SHARPE", AMBER),
        (f"{s.get('sortino', 0) or 0:.2f}", "SORTINO", AMBER),
        (f"{calmar:.2f}", "CALMAR", AMBER),
        (f"{s.get('win_rate', 0) or 0:.1f}%", "TX ACERTO", WHITE),
    ]
    risk_row = [
        (f"{s.get('total_trades', 0) or 0}", "TRADES", WHITE),
        (f"-{mdd:.2f}%" if mdd else "—", "MAX DD", RED),
        (f"{avg_r:+.2f}", "AVG R",
         GREEN if avg_r > 0 else RED),
        (f"{max_streak}", "MAX STREAK",
         RED if max_streak >= 6 else WHITE),
        (f"${(s.get('final_equity') or data.get('final_equity') or 0):,.0f}",
         "FINAL EQUITY", WHITE),
    ]

    def _render_metric_row(row_items):
        row_f = tk.Frame(sf, bg=BG)
        row_f.pack(fill="x", padx=pad, pady=(4, 4))
        for val, label, color in row_items:
            mf = tk.Frame(row_f, bg=BG3, padx=12, pady=8)
            mf.pack(side="left", padx=2, fill="x", expand=True)
            tk.Label(mf, text=val, font=(FONT, 14, "bold"),
                     fg=color, bg=BG3).pack()
            tk.Label(mf, text=label, font=(FONT, 7, "bold"),
                     fg=DIM, bg=BG3).pack()

    tk.Frame(sf, bg=BG, height=4).pack(fill="x", padx=pad, pady=(8, 0))
    _render_metric_row(perf_row)
    _render_metric_row(risk_row)

    # -- PER-STRATEGY BREAKDOWN --
    # Multi-engine runs (MILLENNIUM) carry per-strategy aggregates.
    # Render as a compact table so the user can see which sub-engine
    # contributed what (CITADEL / RENAISSANCE / JUMP).
    per_strat = data.get("per_strategy") or {}
    if isinstance(per_strat, dict) and per_strat:
        tk.Label(sf, text="BREAKDOWN POR ENGINE",
                 font=(FONT, 8, "bold"), fg=AMBER_D, bg=BG
                 ).pack(anchor="w", padx=pad, pady=(10, 4))
        table = tk.Frame(sf, bg=BG3)
        table.pack(fill="x", padx=pad, pady=(0, 8))
        hdr = tk.Frame(table, bg=BG2)
        hdr.pack(fill="x")
        for col, w_ in [("ENGINE", 14), ("N", 6), ("WR%", 7),
                        ("L/S", 10), ("PnL", 12), ("AvgR", 7),
                        ("STREAK", 8)]:
            tk.Label(hdr, text=col, font=(FONT, 7, "bold"),
                     fg=DIM, bg=BG2, width=w_, anchor="w",
                     padx=4, pady=4).pack(side="left")
        for eng, stats in per_strat.items():
            r = tk.Frame(table, bg=BG3)
            r.pack(fill="x")
            eng_pnl = float(stats.get("total_pnl", 0) or 0)
            eng_col = GREEN if eng_pnl >= 0 else RED
            tk.Label(r, text=eng, font=(FONT, 8, "bold"),
                     fg=AMBER, bg=BG3, width=14, anchor="w",
                     padx=4, pady=3).pack(side="left")
            tk.Label(r, text=str(stats.get("n", 0)),
                     font=(FONT, 8), fg=WHITE, bg=BG3,
                     width=6, anchor="w", padx=4).pack(side="left")
            tk.Label(r, text=f"{stats.get('win_rate_pct', 0) or 0:.2f}",
                     font=(FONT, 8), fg=WHITE, bg=BG3,
                     width=7, anchor="w", padx=4).pack(side="left")
            tk.Label(r,
                     text=f"{stats.get('longs', 0)}L/{stats.get('shorts', 0)}S",
                     font=(FONT, 8), fg=DIM, bg=BG3,
                     width=10, anchor="w", padx=4).pack(side="left")
            tk.Label(r,
                     text=(f"+${eng_pnl:,.0f}" if eng_pnl >= 0
                           else f"-${abs(eng_pnl):,.0f}"),
                     font=(FONT, 8, "bold"), fg=eng_col, bg=BG3,
                     width=12, anchor="w", padx=4).pack(side="left")
            tk.Label(r,
                     text=f"{stats.get('avg_r_multiple', 0) or 0:.3f}",
                     font=(FONT, 8), fg=WHITE, bg=BG3,
                     width=7, anchor="w", padx=4).pack(side="left")
            tk.Label(r, text=str(stats.get("max_consec_losses", 0)),
                     font=(FONT, 8), fg=WHITE, bg=BG3,
                     width=8, anchor="w", padx=4).pack(side="left")

    def _fit_points(series, width, height, pad_x=10, pad_y=10, mn=None, mx=None):
        if not series or len(series) < 2:
            return []
        mn = min(series) if mn is None else mn
        mx = max(series) if mx is None else mx
        rng = (mx - mn) or 1
        pts = []
        for i, v in enumerate(series):
            x = pad_x + (width - pad_x * 2) * i / max(len(series) - 1, 1)
            y = height - pad_y - (height - pad_y * 2) * (v - mn) / rng
            pts.append((x, y))
        return pts

    def _draw_line_chart(widget, series, line_color, fill_color=None,
                         min_label=None, max_label=None, end_label=None):
        widget.delete("all")
        w = widget.winfo_width() or 700
        h = int(widget.cget("height")) or 120
        if not series or len(series) < 2:
            return
        mn, mx = min(series), max(series)
        pts = _fit_points(series, w, h, mn=mn, mx=mx)
        if fill_color:
            fill_pts = [(pts[0][0], h - 10)] + pts + [(pts[-1][0], h - 10)]
            widget.create_polygon(*[c for p in fill_pts for c in p], fill=fill_color, outline="")
        widget.create_line(*[c for p in pts for c in p], fill=line_color, width=1.8, smooth=True)
        if max_label is not None:
            widget.create_text(8, 8, text=max_label, font=(FONT, 7), fill=DIM, anchor="nw")
        if min_label is not None:
            widget.create_text(8, h - 8, text=min_label, font=(FONT, 7), fill=DIM, anchor="sw")
        if end_label is not None:
            widget.create_text(w - 8, 8, text=end_label, font=(FONT, 7, "bold"),
                               fill=line_color, anchor="ne")

    # -- EQUITY CURVE --
    if eq and len(eq) > 2:
        tk.Label(sf, text="CURVA DE EQUITY", font=(FONT, 8, "bold"),
                 fg=AMBER_D, bg=BG).pack(anchor="w", padx=pad, pady=(8, 4))
        eq_canvas = tk.Canvas(sf, bg=PANEL, highlightthickness=0, height=140)
        eq_canvas.pack(fill="x", padx=pad, pady=(0, 8))

        def draw_equity(event=None):
            _draw_line_chart(
                eq_canvas,
                eq,
                AMBER,
                fill_color="#1a1400",
                min_label=f"${min(eq):,.0f}",
                max_label=f"${max(eq):,.0f}",
                end_label=f"FINAL ${eq[-1]:,.0f}",
            )
        eq_canvas.bind("<Configure>", draw_equity)

    # -- MONTE CARLO --
    if mc:
        tk.Label(sf, text="MONTE CARLO  (1000 simulações)",
                 font=(FONT, 8, "bold"), fg=AMBER_D, bg=BG
                 ).pack(anchor="w", padx=pad, pady=(8, 4))
        mc_f = tk.Frame(sf, bg=BG)
        mc_f.pack(fill="x", padx=pad, pady=(0, 8))
        mc_items = [
            (f"{mc.get('pct_pos', 0):.1f}%", "POSITIVO",
             GREEN if mc.get('pct_pos', 0) > 50 else RED),
            (f"${mc.get('p5', 0):,.0f}", "P5 (PIOR)", DIM),
            (f"${mc.get('median', 0):,.0f}", "MEDIANA", AMBER),
            (f"${mc.get('p95', 0):,.0f}", "P95 (MELHOR)", GREEN),
            (f"{mc.get('ror', 0):.1f}%", "RISCO RUÍNA",
             GREEN if mc.get('ror', 0) == 0 else RED),
        ]
        for val, label, color in mc_items:
            mf = tk.Frame(mc_f, bg=BG3, padx=10, pady=6)
            mf.pack(side="left", padx=2, fill="x", expand=True)
            tk.Label(mf, text=val, font=(FONT, 12, "bold"),
                     fg=color, bg=BG3).pack()
            tk.Label(mf, text=label, font=(FONT, 7), fg=DIM, bg=BG3).pack()

        mc_paths = mc.get("paths") or []
        if mc_paths:
            mc_canvas = tk.Canvas(sf, bg=PANEL, highlightthickness=0, height=150)
            mc_canvas.pack(fill="x", padx=pad, pady=(0, 8))

            def draw_mc_paths(event=None):
                mc_canvas.delete("all")
                w = mc_canvas.winfo_width() or 700
                h = int(mc_canvas.cget("height")) or 150
                valid = [p for p in mc_paths if p and len(p) > 1]
                if not valid:
                    return
                mn = min(min(p) for p in valid)
                mx = max(max(p) for p in valid)
                for path in valid[:120]:
                    pts = _fit_points(path, w, h, mn=mn, mx=mx)
                    if len(pts) >= 2:
                        mc_canvas.create_line(*[c for p in pts for c in p],
                                              fill="#274d3d", width=1)
                median_path = sorted(valid, key=lambda p: p[-1])[len(valid) // 2]
                median_pts = _fit_points(median_path, w, h, mn=mn, mx=mx)
                if len(median_pts) >= 2:
                    mc_canvas.create_line(*[c for p in median_pts for c in p],
                                          fill=AMBER, width=2.0, smooth=True)
                base_line = [eq[0]] * len(valid[0]) if eq else [0] * len(valid[0])
                base_pts = _fit_points(base_line, w, h, mn=mn, mx=mx)
                if len(base_pts) >= 2:
                    mc_canvas.create_line(*[c for p in base_pts for c in p],
                                          fill=DIM2, width=1, dash=(4, 3))
                mc_canvas.create_text(8, 8, text=f"${mx:,.0f}",
                                      font=(FONT, 7), fill=DIM, anchor="nw")
                mc_canvas.create_text(8, h - 8, text=f"${mn:,.0f}",
                                      font=(FONT, 7), fill=DIM, anchor="sw")
                mc_canvas.create_text(w - 8, 8, text="PATHS + MEDIANA",
                                      font=(FONT, 7, "bold"), fill=AMBER, anchor="ne")
            mc_canvas.bind("<Configure>", draw_mc_paths)

        mc_finals = mc.get("finals") or []
        if mc_finals:
            dist_canvas = tk.Canvas(sf, bg=PANEL, highlightthickness=0, height=110)
            dist_canvas.pack(fill="x", padx=pad, pady=(0, 8))

            def draw_mc_distribution(event=None):
                dist_canvas.delete("all")
                w = dist_canvas.winfo_width() or 700
                h = int(dist_canvas.cget("height")) or 110
                if len(mc_finals) < 2:
                    return
                vals = mc_finals
                mn = min(vals)
                mx = max(vals)
                rng = (mx - mn) or 1
                bins = min(28, max(8, len(vals) // 25))
                counts = [0] * bins
                for v in vals:
                    idx = min(bins - 1, int((v - mn) / rng * bins))
                    counts[idx] += 1
                top = max(counts) or 1
                usable_w = w - 20
                bar_w = usable_w / bins
                for i, ct in enumerate(counts):
                    x0 = 10 + i * bar_w
                    x1 = x0 + max(bar_w - 2, 1)
                    y1 = h - 12
                    y0 = y1 - (h - 28) * ct / top
                    dist_canvas.create_rectangle(x0, y0, x1, y1, fill="#2c3e34", outline="")

                def _mark(value, color, label):
                    x = 10 + usable_w * ((value - mn) / rng)
                    dist_canvas.create_line(x, 10, x, h - 10, fill=color, width=1)
                    dist_canvas.create_text(x + 4, 8, text=label, font=(FONT, 7),
                                            fill=color, anchor="nw")

                _mark(mc.get("p5", mn), RED, "P5")
                _mark(mc.get("median", vals[len(vals) // 2]), AMBER, "MED")
                _mark(mc.get("p95", mx), GREEN, "P95")
                dist_canvas.create_text(8, h - 8, text=f"${mn:,.0f}",
                                        font=(FONT, 7), fill=DIM, anchor="sw")
                dist_canvas.create_text(w - 8, h - 8, text=f"${mx:,.0f}",
                                        font=(FONT, 7), fill=DIM, anchor="se")
                dist_canvas.create_text(w - 8, 8, text="DISTRIBUICAO FINAL",
                                        font=(FONT, 7, "bold"), fill=WHITE, anchor="ne")
            dist_canvas.bind("<Configure>", draw_mc_distribution)

    # -- REGIME PERFORMANCE --
    if bm:
        tk.Label(sf, text="PERFORMANCE POR REGIME",
                 font=(FONT, 8, "bold"), fg=AMBER_D, bg=BG
                 ).pack(anchor="w", padx=pad, pady=(8, 4))
        for regime, rd in bm.items():
            if not rd:
                continue
            rf = tk.Frame(sf, bg=BG3)
            rf.pack(fill="x", padx=pad, pady=1)
            rc = GREEN if regime == "BULL" else RED if regime == "BEAR" else AMBER
            tk.Label(rf, text=f" {regime} ", font=(FONT, 8, "bold"),
                     fg=BG, bg=rc, padx=4).pack(side="left", padx=4, pady=4)
            tk.Label(rf, text=(f"{rd.get('n',0)} trades  "
                               f"WR {rd.get('wr',0):.1f}%  "
                               f"Sharpe {rd.get('sharpe',0):.2f}  "
                               f"DD {rd.get('max_dd',0):.1f}%"),
                     font=(FONT, 8), fg=WHITE, bg=BG3, padx=8
                     ).pack(side="left", pady=4)
            pnl_r = rd.get("pnl", 0)
            tk.Label(rf, text=f"${pnl_r:+,.0f}", font=(FONT, 9, "bold"),
                     fg=GREEN if pnl_r >= 0 else RED, bg=BG3, padx=8
                     ).pack(side="right", pady=4)

    # -- ACTIONS --
    tk.Frame(sf, bg=DIM2, height=1).pack(fill="x", padx=pad, pady=(12, 8))
    act_f = tk.Frame(sf, bg=BG)
    act_f.pack(padx=pad, pady=(0, 16))

    report_html = app._results_run_dir / "report.html"
    if report_html.exists():
        oh = tk.Label(act_f, text="  ABRIR HTML  ", font=(FONT, 9, "bold"),
                      fg=BG, bg=AMBER, cursor="hand2", padx=10, pady=3)
        oh.pack(side="left", padx=4)
        oh.bind("<Button-1>", lambda e: app._open_file(report_html))

    ti = tk.Label(act_f, text="  TRADE INSPECTOR →  ",
                  font=(FONT, 9, "bold"), fg=BG, bg=GREEN,
                  cursor="hand2", padx=10, pady=3)
    ti.pack(side="left", padx=4)
    ti.bind("<Button-1>", lambda e: app._results_render_tab("trades"))

    bk = tk.Label(act_f, text="  VOLTAR  ", font=(FONT, 9),
                  fg=DIM, bg=BG3, cursor="hand2", padx=10, pady=3)
    bk.pack(side="left", padx=4)
    bk.bind("<Button-1>", lambda e: app._menu(app._results_parent_menu))
