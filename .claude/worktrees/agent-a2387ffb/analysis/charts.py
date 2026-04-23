"""
AURUM — Interactive Bloomberg-terminal-style charts for post-backtest exploration.

This module provides individual chart functions that display interactively (plt.show())
and a post-run menu loop. It does NOT save to files — that's what analysis/plots.py does.
"""
import matplotlib
matplotlib.use("TkAgg")  # interactive backend — must be before pyplot import
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
from matplotlib.patches import Rectangle
from config.params import ACCOUNT_SIZE, safe_input

# ── Bloomberg Terminal Color Palette ─────────────────────────
BG      = "#0D1117"
GRID    = "#1B2028"
TEXT    = "#8B949E"
TITLE   = "#C9D1D9"
BLUE    = "#58A6FF"   # main line (equity)
GREEN   = "#3FB950"   # profit/positive
RED     = "#F85149"   # loss/negative
GOLD    = "#E3B341"   # accent/highlight
GRAY    = "#6E7681"   # secondary lines
BORDER  = "#1B2028"   # spine color


def _style(ax, title="", xlabel="", ylabel=""):
    ax.set_facecolor(BG)
    fig = ax.get_figure()
    fig.set_facecolor(BG)
    for sp in ax.spines.values():
        sp.set_edgecolor(BORDER)
    ax.tick_params(colors=TEXT, labelsize=8)
    ax.grid(color=GRID, linestyle="--", alpha=0.3, linewidth=0.5)
    if title:
        ax.set_title(title, color=TITLE, fontsize=11, fontfamily="monospace",
                     fontweight="bold", loc="left", pad=8)
    if xlabel:
        ax.set_xlabel(xlabel, color=TEXT, fontsize=8)
    if ylabel:
        ax.set_ylabel(ylabel, color=TEXT, fontsize=8)


def _watermark(ax):
    ax.text(0.99, 0.01, "AURUM \u00b7 CITADEL v3.6", transform=ax.transAxes,
            fontsize=9, color=BORDER, ha="right", va="bottom", fontfamily="monospace")


def _money_fmt(x, _):
    return f"${x:,.0f}"


# ─────────────────────────────────────────────────────────────
# 1. Equity Curve
# ─────────────────────────────────────────────────────────────
def chart_equity(eq, trades=None):
    if not eq:
        return
    fig, ax = plt.subplots(figsize=(14, 6))
    _style(ax, title="EQUITY CURVE", xlabel="Trade #", ylabel="Capital (USD)")

    x = list(range(len(eq)))
    ax.plot(x, eq, color=BLUE, linewidth=1.2, zorder=4)
    ax.fill_between(x, eq, alpha=0.08, color=BLUE)
    ax.axhline(ACCOUNT_SIZE, color=GRAY, linewidth=0.8, linestyle="--", alpha=0.6)

    # High-water mark
    hwm = []
    peak = eq[0]
    for v in eq:
        if v > peak:
            peak = v
        hwm.append(peak)
    ax.plot(x, hwm, color=GREEN, linewidth=0.7, linestyle="--", alpha=0.4, label="HWM")

    ax.yaxis.set_major_formatter(mticker.FuncFormatter(_money_fmt))
    ax.legend(facecolor=BG, labelcolor=TEXT, fontsize=7, edgecolor=BORDER)
    _watermark(ax)
    plt.tight_layout()
    plt.show()
    plt.close(fig)


# ─────────────────────────────────────────────────────────────
# 2. Drawdown
# ─────────────────────────────────────────────────────────────
def chart_drawdown(eq):
    if not eq:
        return
    fig, ax = plt.subplots(figsize=(14, 5))
    _style(ax, title="DRAWDOWN", xlabel="Trade #", ylabel="Drawdown %")

    peak = eq[0]
    dd = []
    for v in eq:
        if v > peak:
            peak = v
        dd_pct = (v - peak) / peak * 100 if peak else 0
        dd.append(dd_pct)

    x = list(range(len(dd)))
    ax.fill_between(x, 0, dd, color=RED, alpha=0.15)
    ax.plot(x, dd, color=RED, linewidth=0.8)

    for level in [-5, -10, -15, -20]:
        ax.axhline(level, color=GRAY, linewidth=0.5, linestyle="--", alpha=0.4)

    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    _watermark(ax)
    plt.tight_layout()
    plt.show()
    plt.close(fig)


# ─────────────────────────────────────────────────────────────
# 3. PnL Distribution
# ─────────────────────────────────────────────────────────────
def chart_pnl_distribution(trades):
    if not trades:
        return
    pnls = [t["pnl"] for t in trades]
    fig, ax = plt.subplots(figsize=(14, 6))
    _style(ax, title="PnL DISTRIBUTION", xlabel="Trade PnL ($)", ylabel="Frequency")

    n, bins, patches = ax.hist(pnls, bins=40, edgecolor=BG, linewidth=0.5)
    for patch, left_edge in zip(patches, bins[:-1]):
        patch.set_facecolor(GREEN if left_edge >= 0 else RED)
        patch.set_alpha(0.75)

    ax.axvline(0, color="#FFFFFF", linewidth=1.0, alpha=0.6, label="Breakeven")

    mean_pnl = np.mean(pnls)
    median_pnl = np.median(pnls)
    std_pnl = np.std(pnls)
    ax.axvline(mean_pnl, color=GOLD, linewidth=1.2, linestyle="--", label=f"Mean ${mean_pnl:+,.0f}")

    y_top = ax.get_ylim()[1]
    ax.text(0.02, 0.95, f"Mean: ${mean_pnl:+,.1f}\nMedian: ${median_pnl:+,.1f}\nStd: ${std_pnl:,.1f}",
            transform=ax.transAxes, color=TEXT, fontsize=8, va="top", fontfamily="monospace",
            bbox=dict(boxstyle="round,pad=0.4", facecolor=BG, edgecolor=BORDER, alpha=0.9))

    ax.legend(facecolor=BG, labelcolor=TEXT, fontsize=7, edgecolor=BORDER)
    _watermark(ax)
    plt.tight_layout()
    plt.show()
    plt.close(fig)


# ─────────────────────────────────────────────────────────────
# 4. Monte Carlo
# ─────────────────────────────────────────────────────────────
def chart_montecarlo(mc, eq):
    if not mc or not eq:
        return
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8),
                                    gridspec_kw={"height_ratios": [3, 2]})
    fig.set_facecolor(BG)

    # ── Top: Fan chart ──
    _style(ax1, title="MONTE CARLO  \u2014  Fan Chart", xlabel="Trade #", ylabel="Capital (USD)")
    paths = mc["paths"]

    # Plot all paths with very low alpha
    for p in paths:
        ax1.plot(range(len(p)), p, color=GRAY, alpha=0.02, linewidth=0.5)

    # Calculate percentile bands
    max_len = max(len(p) for p in paths)
    # Pad paths to same length
    padded = np.full((len(paths), max_len), np.nan)
    for i, p in enumerate(paths):
        padded[i, :len(p)] = p

    p5  = np.nanpercentile(padded, 5, axis=0)
    p25 = np.nanpercentile(padded, 25, axis=0)
    p50 = np.nanpercentile(padded, 50, axis=0)
    p75 = np.nanpercentile(padded, 75, axis=0)
    p95 = np.nanpercentile(padded, 95, axis=0)
    xp  = list(range(max_len))

    ax1.fill_between(xp, p5, p95, color=BLUE, alpha=0.06)
    ax1.fill_between(xp, p25, p75, color=BLUE, alpha=0.10)
    ax1.plot(xp, p50, color=GOLD, linewidth=0.8, alpha=0.6, label="P50")
    ax1.plot(xp, p5,  color=RED,  linewidth=0.6, alpha=0.5, linestyle=":", label=f"P5 ${mc['p5']:,.0f}")
    ax1.plot(xp, p95, color=GREEN, linewidth=0.6, alpha=0.5, linestyle=":", label=f"P95 ${mc['p95']:,.0f}")

    # Real equity on top
    ax1.plot(range(len(eq)), eq, color="#FFFFFF", linewidth=2, zorder=6, label="Real")
    ax1.axhline(ACCOUNT_SIZE, color=GRAY, linewidth=0.7, linestyle="--", alpha=0.5)

    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(_money_fmt))
    ax1.legend(facecolor=BG, labelcolor=TEXT, fontsize=7, edgecolor=BORDER, loc="upper left")
    _watermark(ax1)

    # ── Bottom: Histogram of finals ──
    _style(ax2, title="DISTRIBUTION OF FINAL EQUITY", xlabel="Final Capital ($)", ylabel="Frequency")
    finals = mc["finals"]

    n, bins, patches = ax2.hist(finals, bins=40, edgecolor=BG, linewidth=0.5)
    for patch, left_edge in zip(patches, bins[:-1]):
        patch.set_facecolor(GREEN if left_edge >= ACCOUNT_SIZE else RED)
        patch.set_alpha(0.75)

    real_final = eq[-1]
    ax2.axvline(real_final, color="#FFFFFF", linewidth=1.5, label=f"Real ${real_final:,.0f}")
    ax2.axvline(mc["p5"], color=RED, linewidth=1.0, linestyle="--", label=f"VaR P5 ${mc['p5']:,.0f}")
    ax2.axvline(mc["median"], color=GOLD, linewidth=1.0, linestyle="--", label=f"Median ${mc['median']:,.0f}")

    # Annotations
    info_text = (
        f"Median PnL: ${mc['median'] - ACCOUNT_SIZE:+,.0f}\n"
        f"P5 VaR: ${mc['p5'] - ACCOUNT_SIZE:+,.0f}\n"
        f"P(Loss): {100 - mc['pct_pos']:.1f}%\n"
        f"Median MaxDD: {mc['avg_dd']:.1f}%"
    )
    ax2.text(0.02, 0.95, info_text, transform=ax2.transAxes, color=TEXT, fontsize=8,
             va="top", fontfamily="monospace",
             bbox=dict(boxstyle="round,pad=0.4", facecolor=BG, edgecolor=BORDER, alpha=0.9))

    ax2.xaxis.set_major_formatter(mticker.FuncFormatter(_money_fmt))
    ax2.legend(facecolor=BG, labelcolor=TEXT, fontsize=7, edgecolor=BORDER)

    plt.tight_layout()
    plt.show()
    plt.close(fig)


# ─────────────────────────────────────────────────────────────
# 5. Win Rate by Symbol
# ─────────────────────────────────────────────────────────────
def chart_winrate_by_symbol(by_sym):
    if not by_sym:
        return
    fig, ax = plt.subplots(figsize=(14, 6))
    _style(ax, title="WIN RATE BY SYMBOL", xlabel="Trades", ylabel="")

    # Sort by PnL descending
    sym_data = {}
    for sym, trades_list in by_sym.items():
        wins = sum(1 for t in trades_list if t["result"] == "WIN")
        total = len(trades_list)
        wr = wins / total * 100 if total else 0
        pnl = sum(t["pnl"] for t in trades_list)
        sym_data[sym] = {"n": total, "wr": wr, "pnl": pnl}

    sorted_syms = sorted(sym_data.keys(), key=lambda s: sym_data[s]["pnl"], reverse=True)
    labels = [s.replace("USDT", "") for s in sorted_syms]
    n_trades = [sym_data[s]["n"] for s in sorted_syms]
    colors = [GREEN if sym_data[s]["wr"] > 50 else RED for s in sorted_syms]

    bars = ax.barh(labels, n_trades, color=colors, alpha=0.75, edgecolor=BG, height=0.6)

    for bar, sym in zip(bars, sorted_syms):
        d = sym_data[sym]
        ax.text(bar.get_width() + 0.5, bar.get_y() + bar.get_height() / 2,
                f"  WR {d['wr']:.0f}%  |  ${d['pnl']:+,.0f}",
                color=TEXT, fontsize=8, va="center", fontfamily="monospace")

    ax.invert_yaxis()
    _watermark(ax)
    plt.tight_layout()
    plt.show()
    plt.close(fig)


# ─────────────────────────────────────────────────────────────
# 6. PnL by Hour
# ─────────────────────────────────────────────────────────────
def chart_pnl_by_hour(trades):
    if not trades:
        return
    fig, ax = plt.subplots(figsize=(14, 5))
    _style(ax, title="PnL BY HOUR (UTC)", xlabel="Hour", ylabel="Avg PnL ($)")

    # Extract hour from trade time
    hour_pnl = {}
    for t in trades:
        h = None
        if "time" in t:
            try:
                h = t["time"].hour
            except Exception:
                pass
        elif "entry_idx" in t:
            # fallback: use entry_idx modulo 24 if no time field
            h = t.get("entry_hour", None)
        if h is None:
            continue
        hour_pnl.setdefault(h, []).append(t["pnl"])

    if not hour_pnl:
        ax.text(0.5, 0.5, "No hour data available", transform=ax.transAxes,
                color=TEXT, fontsize=12, ha="center", va="center")
        _watermark(ax)
        plt.tight_layout()
        plt.show()
        plt.close(fig)
        return

    hours = sorted(hour_pnl.keys())
    avg_pnl = [np.mean(hour_pnl[h]) for h in hours]
    colors = [GREEN if v >= 0 else RED for v in avg_pnl]

    ax.bar(hours, avg_pnl, color=colors, alpha=0.75, width=0.7, edgecolor=BG)
    ax.axhline(0, color=GRAY, linewidth=0.6, linestyle="-")

    for h, v in zip(hours, avg_pnl):
        n = len(hour_pnl[h])
        ax.text(h, v + (abs(v) * 0.05 + 1) * (1 if v >= 0 else -1),
                f"n={n}", color=TEXT, fontsize=6, ha="center", va="bottom" if v >= 0 else "top")

    ax.set_xticks(list(range(24)))
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{int(v):02d}h"))
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(_money_fmt))
    _watermark(ax)
    plt.tight_layout()
    plt.show()
    plt.close(fig)


# ─────────────────────────────────────────────────────────────
# 7. Trade Inspector
# ─────────────────────────────────────────────────────────────
def chart_trade_inspector(trade, df_prices, all_trades):
    if not trade:
        return
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8),
                                    gridspec_kw={"height_ratios": [3, 1]},
                                    sharex=True)
    fig.set_facecolor(BG)

    sym = trade.get("symbol", "???")
    direction = trade.get("direction", "?")
    result = trade.get("result", "?")
    pnl = trade.get("pnl", 0)
    score = trade.get("score", 0)
    dir_short = "LONG" if direction == "BULLISH" else "SHORT"

    title = f"TRADE INSPECTOR  \u2014  {sym}  {dir_short}  {result}  ${pnl:+,.0f}  \u03a9={score:.3f}"

    if df_prices is None or df_prices.empty:
        # No price data — show trade info as text
        _style(ax1, title=title)
        info_lines = [
            f"Symbol:    {sym}",
            f"Direction: {direction}",
            f"Entry:     {trade.get('entry', '?')}",
            f"Stop:      {trade.get('stop', '?')}",
            f"Target:    {trade.get('target', '?')}",
            f"Exit:      {trade.get('exit_p', '?')}",
            f"Result:    {result}  PnL: ${pnl:+,.1f}",
            f"Duration:  {trade.get('duration', '?')} candles",
            f"Score:     {score:.3f}",
        ]
        ax1.text(0.05, 0.90, "\n".join(info_lines), transform=ax1.transAxes,
                 color=TEXT, fontsize=10, va="top", fontfamily="monospace",
                 bbox=dict(boxstyle="round,pad=0.6", facecolor=BG, edgecolor=BORDER))
        ax2.set_visible(False)
        _watermark(ax1)
        plt.tight_layout()
        plt.show()
        plt.close(fig)
        return

    # Determine window
    entry_idx = trade.get("entry_idx", 0)
    duration = trade.get("duration", 1)
    i0 = max(0, entry_idx - 30)
    i1 = min(len(df_prices), entry_idx + duration + 15)
    window_df = df_prices.iloc[i0:i1].reset_index(drop=True)
    offset = i0

    if window_df.empty:
        _style(ax1, title=title)
        ax1.text(0.5, 0.5, "Window out of range", transform=ax1.transAxes,
                 color=TEXT, fontsize=12, ha="center", va="center")
        ax2.set_visible(False)
        _watermark(ax1)
        plt.tight_layout()
        plt.show()
        plt.close(fig)
        return

    _style(ax1, title=title, ylabel="Price")

    # Draw candles
    for xi in range(len(window_df)):
        row = window_df.iloc[xi]
        color = GREEN if row["close"] >= row["open"] else RED
        body_bottom = min(row["open"], row["close"])
        body_height = abs(row["close"] - row["open"])
        if body_height < 1e-10:
            body_height = (row["high"] - row["low"]) * 0.01 or 0.01
        ax1.add_patch(Rectangle((xi - 0.3, body_bottom), 0.6, body_height,
                                facecolor=color, edgecolor=color, alpha=0.8, zorder=2))
        ax1.plot([xi, xi], [row["low"], row["high"]], color=color, linewidth=0.5, zorder=1)

    # Entry and exit positions relative to window
    ei = entry_idx - offset
    xi_exit = entry_idx + duration - offset
    xi_exit = min(xi_exit, len(window_df) - 1)

    # Stop & target lines
    stop_p = trade.get("stop", None)
    target_p = trade.get("target", None)
    if stop_p:
        ax1.axhline(stop_p, color=RED, linewidth=0.8, linestyle="--", alpha=0.7, label="Stop")
    if target_p:
        ax1.axhline(target_p, color=GREEN, linewidth=0.8, linestyle="--", alpha=0.7, label="Target")

    # Entry arrow
    entry_price = trade.get("entry", 0)
    if direction == "BULLISH":
        ax1.annotate("", xy=(ei, entry_price), xytext=(ei, entry_price - (window_df["high"].max() - window_df["low"].min()) * 0.08),
                     arrowprops=dict(arrowstyle="->", color=GREEN, lw=2), zorder=10)
    else:
        ax1.annotate("", xy=(ei, entry_price), xytext=(ei, entry_price + (window_df["high"].max() - window_df["low"].min()) * 0.08),
                     arrowprops=dict(arrowstyle="->", color=RED, lw=2), zorder=10)

    # Exit marker
    exit_price = trade.get("exit_p", entry_price)
    exit_color = GREEN if result == "WIN" else RED
    ax1.scatter(xi_exit, exit_price, marker="D", color=exit_color, s=80, zorder=10,
                edgecolors="#FFFFFF", linewidths=0.8)

    # Score annotation
    y_mid = (window_df["high"].max() + window_df["low"].min()) / 2
    ax1.text(ei + 1, entry_price, f"\u03a9 = {score:.3f}", color=GOLD, fontsize=8,
             fontfamily="monospace", fontweight="bold",
             bbox=dict(boxstyle="round,pad=0.2", facecolor=BG, edgecolor=BORDER, alpha=0.8),
             zorder=11)

    # Omega dimensions annotation
    dims = ["omega_struct", "omega_flow", "omega_cascade", "omega_momentum", "omega_pullback"]
    dim_labels = ["Str", "Flw", "Cas", "Mom", "Plb"]
    omega_text = "  ".join(f"{lb}:{trade.get(d, 0):.2f}" for lb, d in zip(dim_labels, dims))
    ax1.text(0.02, 0.02, omega_text, transform=ax1.transAxes, color=TEXT, fontsize=7,
             fontfamily="monospace", va="bottom",
             bbox=dict(boxstyle="round,pad=0.3", facecolor=BG, edgecolor=BORDER, alpha=0.8))

    ax1.legend(facecolor=BG, labelcolor=TEXT, fontsize=7, edgecolor=BORDER, loc="upper right")
    ax1.set_xlim(-1, len(window_df) + 1)
    _watermark(ax1)

    # ── Bottom: Volume ──
    _style(ax2, ylabel="Volume")
    for xi in range(len(window_df)):
        row = window_df.iloc[xi]
        color = GREEN if row["close"] >= row["open"] else RED
        vol = row.get("vol", 0) if "vol" in window_df.columns else 0
        ax2.bar(xi, vol, color=color, alpha=0.5, width=0.7)

    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v / 1e6:.1f}M" if v >= 1e6 else f"{v / 1e3:.0f}K"))

    # X-axis labels with time if available
    if "time" in window_df.columns:
        step = max(1, len(window_df) // 10)
        tpos = list(range(0, len(window_df), step))
        try:
            ax2.set_xticks(tpos)
            ax2.set_xticklabels(
                [window_df["time"].iloc[xi].strftime("%d/%m %Hh") for xi in tpos],
                rotation=30, ha="right", fontsize=6, color=TEXT)
        except Exception:
            pass

    plt.tight_layout()
    plt.show()
    plt.close(fig)


# ─────────────────────────────────────────────────────────────
# 8. Trade Inspector Sub-Menu
# ─────────────────────────────────────────────────────────────
def _trade_inspector_menu(trades, all_dfs):
    if not trades:
        print("  Sem trades para inspeccionar.")
        return

    while True:
        print(f"\n  === TRADE INSPECTOR ({len(trades)} trades) ===")
        print(f"  {'#':>4}  {'Symbol':<12} {'Dir':<6} {'Result':<5} {'PnL':>10} {'Score':>6}")
        print(f"  {'':->4}  {'':->12} {'':->6} {'':->5} {'':->10} {'':->6}")
        for i, t in enumerate(trades):
            sym = t.get("symbol", "?").replace("USDT", "")
            d = "LONG" if t.get("direction") == "BULLISH" else "SHORT"
            r = t.get("result", "?")
            pnl = t.get("pnl", 0)
            sc = t.get("score", 0)
            color_r = r
            print(f"  {i + 1:>4}  {sym:<12} {d:<6} {color_r:<5} ${pnl:>+9,.1f} {sc:>6.3f}")
            if i >= 49:
                remaining = len(trades) - 50
                if remaining > 0:
                    print(f"  ... +{remaining} trades (digite o numero)")
                break

        print(f"  [0] Voltar")
        choice = safe_input("  trade # > ").strip()
        if choice == "0" or not choice:
            break
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(trades):
                t = trades[idx]
                sym = t.get("symbol", "")
                df = all_dfs.get(sym) if all_dfs else None
                chart_trade_inspector(t, df, trades)
            else:
                print("  Numero invalido.")


# ─────────────────────────────────────────────────────────────
# 9. Main Menu
# ─────────────────────────────────────────────────────────────
def run_menu(all_trades, eq, mc, by_sym, all_dfs):
    """Interactive post-run chart exploration menu."""
    closed = [t for t in all_trades if t["result"] in ("WIN", "LOSS")]

    while True:
        print(f"\n  === EXPLORAR RESULTADOS ===")
        print(f"  [1] Equity Curve")
        print(f"  [2] Drawdown")
        print(f"  [3] PnL Distribution")
        print(f"  [4] Monte Carlo")
        print(f"  [5] Win Rate por Symbol")
        print(f"  [6] PnL por Hora")
        print(f"  [7] Trade Inspector")
        print(f"  [8] Todas as charts (sequencial)")
        print(f"  [0] Sair")

        choice = safe_input("  > ").strip()

        if choice == "0":
            break
        elif choice == "1":
            chart_equity(eq, closed)
        elif choice == "2":
            chart_drawdown(eq)
        elif choice == "3":
            chart_pnl_distribution(closed)
        elif choice == "4":
            chart_montecarlo(mc, eq)
        elif choice == "5":
            chart_winrate_by_symbol(by_sym)
        elif choice == "6":
            chart_pnl_by_hour(closed)
        elif choice == "7":
            _trade_inspector_menu(closed, all_dfs)
        elif choice == "8":
            chart_equity(eq, closed)
            chart_drawdown(eq)
            chart_pnl_distribution(closed)
            if mc:
                chart_montecarlo(mc, eq)
            chart_winrate_by_symbol(by_sym)
            chart_pnl_by_hour(closed)
