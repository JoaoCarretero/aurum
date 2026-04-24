"""
AURUM · CITADEL v3.6 — Standalone tkinter Results Dashboard
============================================================
Opens AFTER a backtest run. Embeds matplotlib charts inline using
FigureCanvasTkAgg with a Bloomberg-dark aesthetic.
"""
import matplotlib
matplotlib.use("TkAgg")

import tkinter as tk
import webbrowser
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from collections import defaultdict

from config.params import ACCOUNT_SIZE

# ── Color Palette ────────────────────────────────────────────
# UI chrome vem do SSOT (core/ui_palette) — alinha com launcher
# e demais cockpits. Cores específicas de chart (GOLD, BLUE, TEAL,
# LGRAY, DGRAY) ficam locais porque são paleta de matplotlib.
from core.ui.ui_palette import (
    BG as BG_WINDOW, PANEL, AMBER, WHITE, DIM, GREEN, RED, FONT,
)

BG_CHART  = BG_WINDOW
GOLD      = "#e8b84b"   # chart accent
BLUE      = "#4a9eff"   # chart line (drawdown etc)
TEAL      = "#2dd4bf"   # chart line (benchmark)
LGRAY     = "#6b7280"   # grid lines
DGRAY     = "#1f2937"   # chart pane inner
WHITE_C   = "#f0f0f0"   # bright label on chart


class ResultsDashboard(tk.Tk):
    """Standalone tkinter dashboard for backtest results exploration."""

    def __init__(self, all_trades, eq, mc, cond, ratios, wf, wf_regime,
                 mdd_pct, by_sym, all_vetos, run_dir, report_path=None):
        super().__init__()

        self.all_trades  = all_trades or []
        self.eq          = eq or []
        self.mc          = mc
        self.cond        = cond or {}
        self.ratios      = ratios or {}
        self.wf          = wf
        self.wf_regime   = wf_regime
        self.mdd_pct     = mdd_pct or 0.0
        self.by_sym      = by_sym or {}
        self.all_vetos   = all_vetos or []
        self.run_dir     = run_dir
        self.report_path = report_path

        self._current_canvas = None

        # ── Window setup ─────────────────────────────────────
        self.title("AURUM \u00b7 CITADEL v3.6 \u00b7 Results")
        self.configure(bg=BG_WINDOW)
        self.geometry("1200x750")
        self._center_window(1200, 750)

        # ── Layout containers ────────────────────────────────
        self._sidebar = tk.Frame(self, bg=BG_WINDOW, width=200)
        self._sidebar.pack(side="left", fill="y")
        self._sidebar.pack_propagate(False)

        self._chart_frame = tk.Frame(self, bg=BG_CHART)
        self._chart_frame.pack(side="left", fill="both", expand=True)

        self._bottom = tk.Frame(self, bg="#111111", height=30)
        self._bottom.pack(side="bottom", fill="x")
        self._bottom.pack_propagate(False)

        # ── Bottom bar summary ───────────────────────────────
        n    = len(self.all_trades)
        wins = sum(1 for t in self.all_trades if t.get("pnl", 0) > 0)
        wr   = (wins / n * 100) if n else 0
        sh   = self.ratios.get("sharpe")
        roi  = self.ratios.get("ret", 0) or 0
        sh_s = f"{sh:.3f}" if sh is not None else "N/A"
        summary = (f"{n} trades \u00b7 WR {wr:.1f}% \u00b7 Sharpe {sh_s} "
                   f"\u00b7 MaxDD {self.mdd_pct:.2f}% \u00b7 ROI {roi:+.2f}%")
        tk.Label(self._bottom, text=summary, bg="#111111", fg=DIM,
                 font=(FONT, 9), anchor="w").pack(fill="x", padx=8, pady=4)

        # ── Sidebar items ────────────────────────────────────
        self._items = [
            ("\u25b8 Equity Curve",        self._chart_equity),
            ("\u25b8 Drawdown",            self._chart_drawdown),
            ("\u25b8 PnL Distribution",    self._chart_pnl_dist),
            ("\u25b8 Monte Carlo",         self._chart_montecarlo),
            ("\u25b8 Win Rate por Simbolo", self._chart_winrate_symbol),
            ("\u25b8 PnL por Hora",        self._chart_pnl_hour),
            ("\u25b8 Regime Performance",  self._chart_regime),
            ("\u25b8 Omega Score vs Result", self._chart_omega),
            None,  # separator
            ("\u25b8 Abrir HTML Report",   self._open_report),
            ("\u25b8 Voltar ao Terminal",  self._quit),
        ]

        self._labels: list[tk.Label] = []
        self._selected_idx = 0

        for item in self._items:
            if item is None:
                tk.Label(self._sidebar, text="\u2500\u2500 \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500 \u2500\u2500",
                         bg=BG_WINDOW, fg=DIM, font=(FONT, 9),
                         anchor="w", padx=10).pack(fill="x", pady=2)
                self._labels.append(None)
                continue

            text, cmd = item
            lbl = tk.Label(self._sidebar, text=text, bg=BG_WINDOW, fg=WHITE,
                           font=(FONT, 10), anchor="w", padx=12, pady=6,
                           cursor="hand2")
            lbl.pack(fill="x")
            lbl.bind("<Enter>", lambda e, l=lbl: self._on_hover(l, True))
            lbl.bind("<Leave>", lambda e, l=lbl: self._on_hover(l, False))
            lbl.bind("<Button-1>", lambda e, c=cmd, l=lbl: self._on_click(l, c))
            self._labels.append(lbl)

        # Keyboard navigation
        self.bind("<Up>", self._nav_up)
        self.bind("<Down>", self._nav_down)
        self.bind("<Return>", self._nav_enter)

        # Select first item
        self._highlight(0)
        self._chart_equity()

    # ── Window centering ─────────────────────────────────────
    def _center_window(self, w, h):
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

    # ── Sidebar interaction ──────────────────────────────────
    def _on_hover(self, lbl, entering):
        idx = self._labels.index(lbl)
        if idx == self._selected_idx:
            return
        lbl.configure(bg="#1a1a1a" if entering else BG_WINDOW)

    def _on_click(self, lbl, cmd):
        idx = self._labels.index(lbl)
        self._highlight(idx)
        cmd()

    def _highlight(self, idx):
        for i, lbl in enumerate(self._labels):
            if lbl is None:
                continue
            if i == idx:
                lbl.configure(bg=AMBER, fg="#000000")
            else:
                lbl.configure(bg=BG_WINDOW, fg=WHITE)
        self._selected_idx = idx

    def _nav_up(self, _event=None):
        idx = self._selected_idx - 1
        while idx >= 0 and self._labels[idx] is None:
            idx -= 1
        if idx >= 0:
            self._highlight(idx)

    def _nav_down(self, _event=None):
        idx = self._selected_idx + 1
        while idx < len(self._labels) and self._labels[idx] is None:
            idx += 1
        if idx < len(self._labels):
            self._highlight(idx)

    def _nav_enter(self, _event=None):
        item = self._items[self._selected_idx]
        if item is not None:
            item[1]()

    # ── Figure display ───────────────────────────────────────
    def _show_figure(self, fig):
        for w in self._chart_frame.winfo_children():
            w.destroy()
        canvas = FigureCanvasTkAgg(fig, master=self._chart_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)
        toolbar = NavigationToolbar2Tk(canvas, self._chart_frame)
        toolbar.update()
        # Style toolbar to match dark theme
        try:
            toolbar.configure(bg="#111111")
            for child in toolbar.winfo_children():
                try:
                    child.configure(bg="#111111")
                except tk.TclError:
                    pass
        except tk.TclError:
            pass
        self._current_canvas = canvas

    # ── Axis helper ──────────────────────────────────────────
    def _ax(self, ax, title="", ylabel=""):
        ax.set_facecolor(PANEL)
        for sp in ax.spines.values():
            sp.set_edgecolor(DGRAY)
            sp.set_linewidth(0.5)
        ax.tick_params(colors=LGRAY, labelsize=7, length=3)
        ax.grid(color=DGRAY, linewidth=0.4, linestyle="--", alpha=0.6)
        if title:
            ax.set_title(title, color=LGRAY, fontsize=9, loc="left", pad=5)
        if ylabel:
            ax.set_ylabel(ylabel, color=LGRAY, fontsize=7)

    # ── Actions ──────────────────────────────────────────────
    def _open_report(self):
        if self.report_path:
            webbrowser.open(self.report_path)

    def _quit(self):
        self.destroy()

    # ════════════════════════════════════════════════════════
    # CHART METHODS
    # ════════════════════════════════════════════════════════

    def _chart_equity(self):
        if not self.eq:
            return
        fig, ax = plt.subplots(figsize=(10, 5))
        fig.set_facecolor(BG_CHART)
        self._ax(ax, title="Equity Curve", ylabel="Equity ($)")

        x = np.arange(len(self.eq))
        eq = np.array(self.eq, dtype=float)

        # Gold equity line
        ax.plot(x, eq, color=GOLD, linewidth=1.2, label="Equity")

        # Fill green above ACCOUNT_SIZE, red below
        ax.fill_between(x, eq, ACCOUNT_SIZE,
                        where=(eq >= ACCOUNT_SIZE), interpolate=True,
                        color=GREEN, alpha=0.12)
        ax.fill_between(x, eq, ACCOUNT_SIZE,
                        where=(eq < ACCOUNT_SIZE), interpolate=True,
                        color=RED, alpha=0.12)

        # High-water mark
        hwm = np.maximum.accumulate(eq)
        ax.plot(x, hwm, color=GREEN, linewidth=0.7, linestyle="--",
                alpha=0.6, label="HWM")

        ax.axhline(ACCOUNT_SIZE, color=WHITE_C, linewidth=0.5, alpha=0.3)
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(
            lambda v, _: f"${v:,.0f}"))

        # Drawdown overlay on twin axis
        dd = (hwm - eq) / hwm * 100
        ax2 = ax.twinx()
        ax2.fill_between(x, -dd, 0, color=RED, alpha=0.10)
        ax2.set_ylim(-max(dd.max() * 1.5, 1), 0)
        ax2.tick_params(colors=LGRAY, labelsize=7)
        ax2.set_ylabel("Drawdown %", color=LGRAY, fontsize=7)
        for sp in ax2.spines.values():
            sp.set_edgecolor(DGRAY)
            sp.set_linewidth(0.5)

        ax.legend(fontsize=7, loc="upper left",
                  facecolor=PANEL, edgecolor=DGRAY, labelcolor=LGRAY)
        fig.tight_layout()
        self._show_figure(fig)
        plt.close(fig)

    def _chart_drawdown(self):
        if not self.eq:
            return
        fig, ax = plt.subplots(figsize=(10, 5))
        fig.set_facecolor(BG_CHART)
        self._ax(ax, title="Running Drawdown", ylabel="Drawdown %")

        eq = np.array(self.eq, dtype=float)
        hwm = np.maximum.accumulate(eq)
        dd = (hwm - eq) / hwm * 100
        x = np.arange(len(dd))

        ax.fill_between(x, -dd, 0, color=RED, alpha=0.35)
        ax.plot(x, -dd, color=RED, linewidth=0.8)

        for lvl in [5, 10, 15, 20]:
            ax.axhline(-lvl, color=LGRAY, linewidth=0.5, linestyle=":",
                       alpha=0.5)
            ax.text(len(dd) * 0.98, -lvl + 0.3, f"-{lvl}%",
                    color=LGRAY, fontsize=7, ha="right")

        ax.set_ylim(-max(dd.max() * 1.3, 1), 1)
        fig.tight_layout()
        self._show_figure(fig)
        plt.close(fig)

    def _chart_pnl_dist(self):
        pnls = [t.get("pnl", 0) for t in self.all_trades]
        if not pnls:
            return
        fig, ax = plt.subplots(figsize=(10, 5))
        fig.set_facecolor(BG_CHART)
        self._ax(ax, title="PnL Distribution", ylabel="Frequency")

        arr = np.array(pnls, dtype=float)
        bins = np.linspace(arr.min(), arr.max(), 50)
        n_vals, bin_edges, patches = ax.hist(arr, bins=bins, edgecolor="none",
                                             alpha=0.85)
        for patch, left in zip(patches, bin_edges):
            patch.set_facecolor(GREEN if left >= 0 else RED)

        ax.axvline(0, color=WHITE_C, linewidth=0.8, alpha=0.6)
        mean_v = float(np.mean(arr))
        ax.axvline(mean_v, color=GOLD, linewidth=1, linestyle="--",
                   label=f"Mean: ${mean_v:.1f}")

        med_v = float(np.median(arr))
        std_v = float(np.std(arr))
        ax.text(0.02, 0.95, f"Mean: ${mean_v:.1f}\nMedian: ${med_v:.1f}\n"
                f"Std: ${std_v:.1f}", transform=ax.transAxes,
                color=LGRAY, fontsize=8, va="top",
                fontfamily="monospace",
                bbox=dict(facecolor=PANEL, edgecolor=DGRAY, alpha=0.9))

        ax.legend(fontsize=7, facecolor=PANEL, edgecolor=DGRAY, labelcolor=LGRAY)
        fig.tight_layout()
        self._show_figure(fig)
        plt.close(fig)

    def _chart_montecarlo(self):
        if self.mc is None:
            return
        paths  = self.mc.get("paths")
        finals = self.mc.get("finals")
        if paths is None or finals is None:
            return

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6),
                                        gridspec_kw={"height_ratios": [3, 2]})
        fig.set_facecolor(BG_CHART)

        # Top: fan chart
        self._ax(ax1, title="Monte Carlo Simulation", ylabel="Equity ($)")
        paths_arr = np.array(paths, dtype=float)
        for i in range(min(len(paths_arr), 200)):
            ax1.plot(paths_arr[i], color=LGRAY, alpha=0.04, linewidth=0.5)

        # Real equity on top
        if self.eq:
            real_len = min(len(self.eq), paths_arr.shape[1] if paths_arr.ndim > 1 else 0)
            if real_len > 0:
                ax1.plot(self.eq[:real_len], color=WHITE_C, linewidth=1.2,
                         label="Real Equity")

        # P5 / P50 / P95
        if paths_arr.ndim == 2 and paths_arr.shape[0] > 1:
            p5  = np.percentile(paths_arr, 5, axis=0)
            p50 = np.percentile(paths_arr, 50, axis=0)
            p95 = np.percentile(paths_arr, 95, axis=0)
            xp = np.arange(paths_arr.shape[1])
            ax1.plot(xp, p5,  color=RED,  linewidth=0.7, linestyle="--", label="P5")
            ax1.plot(xp, p50, color=GOLD, linewidth=0.7, linestyle="--", label="P50")
            ax1.plot(xp, p95, color=GREEN, linewidth=0.7, linestyle="--", label="P95")

        ax1.yaxis.set_major_formatter(mticker.FuncFormatter(
            lambda v, _: f"${v:,.0f}"))
        ax1.legend(fontsize=7, loc="upper left",
                   facecolor=PANEL, edgecolor=DGRAY, labelcolor=LGRAY)

        # Bottom: histogram of finals
        self._ax(ax2, title="Final Equity Distribution", ylabel="Count")
        finals_arr = np.array(finals, dtype=float)
        bins = 40
        n_vals, bin_edges, patches = ax2.hist(finals_arr, bins=bins,
                                               edgecolor="none", alpha=0.85)
        for patch, left in zip(patches, bin_edges):
            patch.set_facecolor(GREEN if left >= ACCOUNT_SIZE else RED)

        # VaR line (P5)
        var5 = float(np.percentile(finals_arr, 5))
        ax2.axvline(var5, color=RED, linewidth=1, linestyle="--",
                    label=f"VaR 5%: ${var5:,.0f}")
        ax2.axvline(ACCOUNT_SIZE, color=WHITE_C, linewidth=0.6, alpha=0.4)
        ax2.legend(fontsize=7, facecolor=PANEL, edgecolor=DGRAY, labelcolor=LGRAY)

        fig.tight_layout()
        self._show_figure(fig)
        plt.close(fig)

    def _chart_winrate_symbol(self):
        if not self.by_sym:
            return
        fig, ax = plt.subplots(figsize=(10, 5))
        fig.set_facecolor(BG_CHART)
        self._ax(ax, title="Win Rate por Simbolo", ylabel="")

        # Compute per-symbol stats
        sym_data = []
        for sym, trades in self.by_sym.items():
            if not trades:
                continue
            total_pnl = sum(t.get("pnl", 0) for t in trades)
            wins = sum(1 for t in trades if t.get("pnl", 0) > 0)
            wr = wins / len(trades) * 100 if trades else 0
            sym_data.append((sym, total_pnl, wr, len(trades)))

        if not sym_data:
            plt.close(fig)
            return

        # Sort by PnL descending
        sym_data.sort(key=lambda s: s[1], reverse=True)
        names  = [s[0] for s in sym_data]
        pnls   = [s[1] for s in sym_data]
        wrs    = [s[2] for s in sym_data]

        y_pos = np.arange(len(names))
        colors = [GREEN if wr > 50 else RED for wr in wrs]

        ax.barh(y_pos, pnls, color=colors, alpha=0.8, height=0.6)
        ax.set_yticks(y_pos)
        ax.set_yticklabels(names, fontsize=8, color=LGRAY, fontfamily="monospace")
        ax.invert_yaxis()

        for i, (name, pnl, wr, n) in enumerate(sym_data):
            label = f"WR {wr:.0f}%  ${pnl:+,.0f}"
            x_pos = pnl + (max(abs(p) for p in pnls) * 0.02 * (1 if pnl >= 0 else -1))
            ha = "left" if pnl >= 0 else "right"
            ax.text(x_pos, i, label, color=LGRAY, fontsize=7,
                    va="center", ha=ha, fontfamily="monospace")

        ax.axvline(0, color=WHITE_C, linewidth=0.5, alpha=0.3)
        fig.tight_layout()
        self._show_figure(fig)
        plt.close(fig)

    def _chart_pnl_hour(self):
        if not self.all_trades:
            return
        fig, ax = plt.subplots(figsize=(10, 5))
        fig.set_facecolor(BG_CHART)
        self._ax(ax, title="PnL por Hora (UTC)", ylabel="Avg PnL ($)")

        hour_pnl = defaultdict(list)
        for t in self.all_trades:
            time_val = t.get("time")
            pnl_val = t.get("pnl", 0)
            if time_val is None:
                continue
            try:
                if hasattr(time_val, "hour"):
                    h = time_val.hour
                else:
                    h = int(str(time_val).split(" ")[-1].split(":")[0]) % 24
                hour_pnl[h].append(pnl_val)
            except (ValueError, IndexError, AttributeError):
                continue

        if not hour_pnl:
            plt.close(fig)
            return

        hours = list(range(24))
        avgs = [np.mean(hour_pnl[h]) if h in hour_pnl and hour_pnl[h] else 0
                for h in hours]

        colors = [GREEN if v >= 0 else RED for v in avgs]
        ax.bar(hours, avgs, color=colors, alpha=0.8, width=0.7)
        ax.axhline(0, color=WHITE_C, linewidth=0.5, alpha=0.3)
        ax.set_xticks(hours)
        ax.set_xticklabels([f"{h:02d}" for h in hours], fontsize=7)
        ax.set_xlabel("Hour (UTC)", color=LGRAY, fontsize=7)

        fig.tight_layout()
        self._show_figure(fig)
        plt.close(fig)

    def _chart_regime(self):
        if not self.all_trades:
            return
        fig, ax = plt.subplots(figsize=(10, 5))
        fig.set_facecolor(BG_CHART)
        self._ax(ax, title="Regime Performance", ylabel="")

        # Aggregate by regime
        regime_data = defaultdict(lambda: {"wins": 0, "total": 0, "pnl": 0.0})
        for t in self.all_trades:
            regime = t.get("macro_bias", "UNKNOWN")
            if regime is None:
                regime = "UNKNOWN"
            regime = regime.upper()
            regime_data[regime]["total"] += 1
            regime_data[regime]["pnl"] += t.get("pnl", 0)
            if t.get("pnl", 0) > 0:
                regime_data[regime]["wins"] += 1

        if not regime_data:
            plt.close(fig)
            return

        regime_colors = {
            "BULL": GREEN,
            "BEAR": RED,
            "CHOP": TEAL,
        }

        regimes = sorted(regime_data.keys())
        x = np.arange(len(regimes))
        width = 0.35

        wrs = []
        pnls = []
        for r in regimes:
            d = regime_data[r]
            wr = d["wins"] / d["total"] * 100 if d["total"] else 0
            wrs.append(wr)
            pnls.append(d["pnl"])

        colors = [regime_colors.get(r, BLUE) for r in regimes]

        bars1 = ax.bar(x - width / 2, wrs, width, label="Win Rate %",
                       color=colors, alpha=0.7)
        ax2 = ax.twinx()
        bars2 = ax2.bar(x + width / 2, pnls, width, label="Total PnL ($)",
                        color=colors, alpha=0.4, edgecolor=colors, linewidth=1)

        ax.set_xticks(x)
        ax.set_xticklabels(regimes, fontsize=9, color=LGRAY, fontfamily="monospace")
        ax.set_ylabel("Win Rate %", color=LGRAY, fontsize=7)
        ax2.set_ylabel("Total PnL ($)", color=LGRAY, fontsize=7)
        ax2.tick_params(colors=LGRAY, labelsize=7)
        for sp in ax2.spines.values():
            sp.set_edgecolor(DGRAY)
            sp.set_linewidth(0.5)

        # Annotate
        for i, r in enumerate(regimes):
            d = regime_data[r]
            wr = wrs[i]
            ax.text(i - width / 2, wr + 1, f"{wr:.0f}%", ha="center",
                    color=LGRAY, fontsize=7)
            ax.text(i + width / 2, 0, f"n={d['total']}\n${d['pnl']:+,.0f}",
                    ha="center", va="bottom" if d["pnl"] >= 0 else "top",
                    color=LGRAY, fontsize=7, fontfamily="monospace")

        ax.axhline(50, color=WHITE_C, linewidth=0.4, linestyle=":", alpha=0.3)
        ax.legend(fontsize=7, loc="upper left",
                  facecolor=PANEL, edgecolor=DGRAY, labelcolor=LGRAY)
        ax2.legend(fontsize=7, loc="upper right",
                   facecolor=PANEL, edgecolor=DGRAY, labelcolor=LGRAY)

        fig.tight_layout()
        self._show_figure(fig)
        plt.close(fig)

    def _chart_omega(self):
        if not self.all_trades:
            return
        fig, ax = plt.subplots(figsize=(10, 5))
        fig.set_facecolor(BG_CHART)
        self._ax(ax, title="Omega Score vs Result", ylabel="PnL ($)")

        scores = []
        pnls   = []
        colors_pts = []
        for t in self.all_trades:
            score = t.get("score")
            pnl   = t.get("pnl", 0)
            if score is None:
                continue
            scores.append(float(score))
            pnls.append(float(pnl))
            colors_pts.append(GREEN if pnl > 0 else RED)

        if not scores:
            plt.close(fig)
            return

        ax.scatter(scores, pnls, c=colors_pts, s=18, alpha=0.6, edgecolors="none")

        # Score threshold line
        from config.params import SCORE_THRESHOLD
        ax.axvline(SCORE_THRESHOLD, color=GOLD, linewidth=0.8, linestyle="--",
                   label=f"Threshold {SCORE_THRESHOLD:.2f}")
        ax.axhline(0, color=WHITE_C, linewidth=0.4, alpha=0.3)

        # Trend line
        if len(scores) > 2:
            z = np.polyfit(scores, pnls, 1)
            p = np.poly1d(z)
            xs = np.linspace(min(scores), max(scores), 100)
            ax.plot(xs, p(xs), color=BLUE, linewidth=1, alpha=0.7,
                    label="Trend")

        ax.set_xlabel("Omega Score", color=LGRAY, fontsize=7)
        ax.legend(fontsize=7, facecolor=PANEL, edgecolor=DGRAY, labelcolor=LGRAY)
        fig.tight_layout()
        self._show_figure(fig)
        plt.close(fig)
