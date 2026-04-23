"""AURUM — All matplotlib plotting functions."""
import math
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.ticker as mticker
from collections import defaultdict
from config.params import *

# ── Paleta ────────────────────────────────────────────────────
BG, PANEL = "#0a0a12", "#0f0f1a"
GOLD, GREEN, RED, BLUE, PURPLE, TEAL = "#e8b84b", "#26d47c", "#e85d5d", "#4a9eff", "#9b7fe8", "#2dd4bf"
LGRAY, DGRAY, WHITE = "#6b7280", "#1f2937", "#f0f0f0"

def _ax(ax, title="", xlabel="", ylabel=""):
    ax.set_facecolor(PANEL)
    for sp in ax.spines.values(): sp.set_edgecolor(DGRAY); sp.set_linewidth(0.5)
    ax.tick_params(colors=LGRAY, labelsize=7, length=3)
    ax.xaxis.set_tick_params(labelcolor=LGRAY)
    ax.yaxis.set_tick_params(labelcolor=LGRAY)
    ax.grid(color=DGRAY, linewidth=0.4, linestyle="--", alpha=0.6)
    if title:   ax.set_title(title, color=LGRAY, fontsize=8, loc="left", pad=5)
    if xlabel:  ax.set_xlabel(xlabel, color=LGRAY, fontsize=7)
    if ylabel:  ax.set_ylabel(ylabel, color=LGRAY, fontsize=7)

def plot_dashboard(trades, eq, cond, wf, ratios, mdd_pct, run_dir=None):
    closed  = [t for t in trades if t["result"] in ("WIN","LOSS")]
    wins    = [t for t in closed if t["result"]=="WIN"]
    losses  = [t for t in closed if t["result"]=="LOSS"]
    bull_t  = [t for t in closed if t["direction"]=="BULLISH"]
    bear_t  = [t for t in closed if t["direction"]=="BEARISH"]
    chop_t  = [t for t in closed if t.get("chop_trade")]
    wr      = len(wins)/len(closed)*100 if closed else 0
    bull_wr = sum(1 for t in bull_t if t["result"]=="WIN")/max(len(bull_t),1)*100
    bear_wr = sum(1 for t in bear_t if t["result"]=="WIN")/max(len(bear_t),1)*100
    roi     = (eq[-1]-ACCOUNT_SIZE)/ACCOUNT_SIZE*100

    fig = plt.figure(figsize=(26,14), facecolor=BG)
    fig.suptitle(
        f"☿  AZOTH v3.6   ·   {INTERVAL}   ·   {len(closed)} trades   ·   "
        f"[U1]Ω-risk  [U2]SoftCorr  [U3]CHOP-MR  ·   RR {TARGET_RR}×",
        color=GOLD, fontsize=11, y=0.98, fontweight="bold", fontfamily="monospace")
    gs = gridspec.GridSpec(3,4, figure=fig, hspace=0.50, wspace=0.35,
                           top=0.93, bottom=0.06, left=0.05, right=0.97)

    ax1 = fig.add_subplot(gs[0,:3])
    _ax(ax1, ylabel="Capital (USD)")
    x = list(range(len(eq)))
    ax1.fill_between(x, ACCOUNT_SIZE, eq, where=[v>=ACCOUNT_SIZE for v in eq], color=GREEN, alpha=0.06)
    ax1.fill_between(x, ACCOUNT_SIZE, eq, where=[v<ACCOUNT_SIZE  for v in eq], color=RED,   alpha=0.12)
    ax1.plot(x, eq, color=GOLD, linewidth=1.8, zorder=4)
    ax1.axhline(ACCOUNT_SIZE, color=DGRAY, linewidth=0.8, linestyle="--")
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"${v:,.0f}"))
    ax1.set_title(
        f"${ACCOUNT_SIZE:,.0f} → ${eq[-1]:,.0f}   ROI {roi:+.1f}%   "
        f"Sharpe {ratios['sharpe']}   Sortino {ratios['sortino']}   "
        f"Calmar {ratios['calmar']}   MaxDD {mdd_pct:.1f}%   "
        f"L/S/MR {len(bull_t)}/{len(bear_t)}/{len(chop_t)}",
        color=LGRAY, fontsize=7, loc="left", pad=5)
    pk = [ACCOUNT_SIZE]
    for e in eq[1:]: pk.append(max(pk[-1],e))
    ddc = [(p-e)/p*100 if p else 0 for p,e in zip(pk,eq)]
    ax1b = ax1.twinx()
    ax1b.fill_between(x, 0, [-d for d in ddc], color=RED, alpha=0.18)
    ax1b.set_ylim(-50,5); ax1b.set_ylabel("DD%", color=RED, fontsize=6)
    ax1b.tick_params(colors=RED, labelsize=6); ax1b.set_facecolor(PANEL)

    ax2 = fig.add_subplot(gs[0,3])
    _ax(ax2, title=f"Score Ω   WR {wr:.1f}%  n={len(closed)}")
    bins = [i/50 for i in range(26,36)]
    ax2.hist([t["score"] for t in wins],   bins=bins, color=GREEN, alpha=0.7, label=f"WIN {len(wins)}",  density=True)
    ax2.hist([t["score"] for t in losses], bins=bins, color=RED,   alpha=0.7, label=f"LOSS {len(losses)}", density=True)
    ax2.axvline(SCORE_THRESHOLD, color=GOLD, linewidth=1.5, linestyle="--")
    ax2.legend(facecolor=DGRAY, labelcolor=WHITE, fontsize=7)

    ax3 = fig.add_subplot(gs[1,0])
    _ax(ax3, title="WR por Faixa Ω", ylabel="%")
    lc  = list(cond.keys())
    wrs = [cond[k]["wr"]  if cond[k] else 0 for k in lc]
    ns  = [cond[k]["n"]   if cond[k] else 0 for k in lc]
    exps= [cond[k]["exp"] if cond[k] else 0 for k in lc]
    bars = ax3.bar(lc, wrs, color=[GREEN if w>=55 else GOLD if w>=40 else RED for w in wrs], alpha=0.8, zorder=3)
    ax3.axhline(50, color=LGRAY, linewidth=0.8, linestyle="--", alpha=0.5)
    for bar,n,exp in zip(bars,ns,exps):
        ax3.text(bar.get_x()+bar.get_width()/2, bar.get_height()+1,
                 f"n={n}\nE${exp:+.0f}", ha="center", va="bottom", color=LGRAY, fontsize=6)
    ax3.set_ylim(0,100)

    ax4 = fig.add_subplot(gs[1,1])
    _ax(ax4, title="Vetor Ω  WIN vs LOSS")
    dims = ["omega_struct","omega_flow","omega_cascade","omega_momentum","omega_pullback"]
    dlb  = ["struct","flow","casc","mom","pull"]
    aw   = [sum(t[d] for t in wins)/max(len(wins),1)   for d in dims]
    al   = [sum(t[d] for t in losses)/max(len(losses),1) for d in dims]
    xd, bw = range(len(dims)), 0.35
    ax4.bar([i-bw/2 for i in xd], aw, bw, color=GREEN, alpha=0.75, label="WIN", zorder=3)
    ax4.bar([i+bw/2 for i in xd], al, bw, color=RED,   alpha=0.75, label="LOSS", zorder=3)
    ax4.axhline(OMEGA_MIN_COMPONENT, color=GOLD, linewidth=1.0, linestyle=":", alpha=0.7)
    ax4.set_xticks(list(xd)); ax4.set_xticklabels(dlb, fontsize=7, color=LGRAY)
    ax4.set_ylim(0,1.05); ax4.legend(facecolor=DGRAY, labelcolor=WHITE, fontsize=6)

    ax5 = fig.add_subplot(gs[1,2])
    _ax(ax5, title="Long / Short / CHOP-MR  WR%")
    chop_wr = sum(1 for t in chop_t if t["result"]=="WIN")/max(len(chop_t),1)*100
    sides    = ["LONG","SHORT","CHOP-MR"]
    wrs_ls   = [bull_wr, bear_wr, chop_wr]
    ns_ls    = [len(bull_t), len(bear_t), len(chop_t)]
    pnl_ls   = [sum(t["pnl"] for t in bull_t),
                sum(t["pnl"] for t in bear_t),
                sum(t["pnl"] for t in chop_t)]
    colors_ls = [GREEN if w>=50 else RED for w in wrs_ls]
    colors_ls[2] = TEAL
    bars2 = ax5.bar(sides, wrs_ls, color=colors_ls, alpha=0.8, width=0.4, zorder=3)
    ax5.axhline(50, color=LGRAY, linewidth=0.8, linestyle="--", alpha=0.5)
    for bar,n,pnl in zip(bars2, ns_ls, pnl_ls):
        ax5.text(bar.get_x()+bar.get_width()/2, bar.get_height()+1,
                 f"n={n}\n${pnl:+,.0f}", ha="center", va="bottom", color=LGRAY, fontsize=7)
    ax5.set_ylim(0,100)

    ax6 = fig.add_subplot(gs[1,3])
    _ax(ax6, title="PnL por Símbolo")
    by_sym  = defaultdict(list)
    for t in closed: by_sym[t["symbol"]].append(t)
    sp = dict(sorted({s:sum(t["pnl"] for t in ts) for s,ts in by_sym.items()}.items(), key=lambda x:x[1]))
    ax6.barh([s.replace("USDT","") for s in sp], list(sp.values()),
             color=[GREEN if v>=0 else RED for v in sp.values()], alpha=0.8, zorder=3)
    ax6.axvline(0, color=LGRAY, linewidth=0.8)
    ax6.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"${v:,.0f}"))
    ax6.tick_params(axis="y", labelsize=7)

    ax7 = fig.add_subplot(gs[2,:3])
    _ax(ax7, title="Walk-Forward  —  Treino vs Fora da Amostra", ylabel="WR%")
    if wf:
        wf_x  = [w["w"] for w in wf]; wf_tr = [w["train"]["wr"] for w in wf]; wf_te = [w["test"]["wr"] for w in wf]
        ok    = sum(1 for w in wf if abs(w["test"]["wr"]-w["train"]["wr"])<=15)
        ax7.plot(wf_x, wf_tr, color=BLUE,  linewidth=1.2, marker=".", markersize=3, label="Treino")
        ax7.plot(wf_x, wf_te, color=GREEN, linewidth=1.5, marker=".", markersize=3, label="Fora da amostra")
        ax7.fill_between(wf_x, [t-20 for t in wf_tr], [t+20 for t in wf_tr], alpha=0.06, color=BLUE)
        ax7.axhline(50, color=LGRAY, linewidth=0.8, linestyle="--", alpha=0.5)
        ax7.set_title(f"Walk-Forward  {ok}/{len(wf)} estáveis ({ok/len(wf)*100:.0f}%)",
                      color=LGRAY, fontsize=8, loc="left", pad=5)
        ax7.set_ylim(0,105); ax7.legend(facecolor=DGRAY, labelcolor=WHITE, fontsize=7)

    ax8 = fig.add_subplot(gs[2,3])
    _ax(ax8, title="WR% por Regime Macro")
    bm_data = {}
    for t in closed:
        b = t.get("macro_bias","CHOP")
        bm_data.setdefault(b, []).append(t)
    regimes   = ["BULL","BEAR","CHOP"]
    bm_wrs, bm_ns, bm_pnls = [], [], []
    for regime in regimes:
        ts2 = bm_data.get(regime, [])
        if ts2:
            w2 = sum(1 for t in ts2 if t["result"]=="WIN")
            bm_wrs.append(round(w2/len(ts2)*100,1))
            bm_ns.append(len(ts2))
            bm_pnls.append(round(sum(t["pnl"] for t in ts2),0))
        else:
            bm_wrs.append(0); bm_ns.append(0); bm_pnls.append(0)
    bars_bm = ax8.bar(regimes, bm_wrs, color=[GREEN, RED, TEAL], alpha=0.8, zorder=3)
    ax8.axhline(50, color=LGRAY, linewidth=0.8, linestyle="--", alpha=0.5)
    for bar, n, pnl in zip(bars_bm, bm_ns, bm_pnls):
        if n:
            ax8.text(bar.get_x()+bar.get_width()/2, bar.get_height()+1,
                     f"n={n}\n${pnl:+,.0f}", ha="center", va="bottom",
                     color=LGRAY, fontsize=6)
    ax8.set_ylim(0, 100)

    from pathlib import Path
    fname = str(Path(run_dir) / "charts" / f"dashboard_{INTERVAL}.png")
    plt.savefig(fname, dpi=100, bbox_inches="tight", facecolor=BG)
    plt.close(); print(f"  Dashboard → {fname}")

def plot_montecarlo(mc, real_eq, run_dir=None):
    if not mc: return
    fig, axes = plt.subplots(1,3, figsize=(22,7), facecolor=BG)
    fig.suptitle(
        f"☿  AZOTH v3.6  ·  Monte Carlo  ({MC_N}×  bloco={MC_BLOCK})\n"
        f"Positivos: {mc['pct_pos']:.1f}%   Mediana: ${mc['median']:,.0f}   "
        f"p5: ${mc['p5']:,.0f}   p95: ${mc['p95']:,.0f}   RoR: {mc['ror']:.1f}%",
        color=GOLD, fontsize=11, y=0.98)
    ax1,ax2,ax3 = axes
    _ax(ax1,"Equity (200 simulações)","trades","Capital")
    for p in mc["paths"]:
        ax1.plot(range(len(p)), p, color=GREEN if p[-1]>ACCOUNT_SIZE else RED, alpha=0.05, linewidth=0.5)
    ax1.plot(range(len(real_eq)), real_eq, color=GOLD, linewidth=2.5, zorder=6, label="Real")
    for lv,c,lb in [(mc["p5"],RED,f"p5 ${mc['p5']:,.0f}"),
                    (mc["median"],GOLD,f"Med ${mc['median']:,.0f}"),
                    (mc["p95"],GREEN,f"p95 ${mc['p95']:,.0f}")]:
        ax1.axhline(lv, color=c, linewidth=1.2, linestyle=":", alpha=0.8, label=lb)
    ax1.legend(facecolor=DGRAY, labelcolor=WHITE, fontsize=7)
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"${v:,.0f}"))
    _ax(ax2,"Distribuição Final","Capital Final","Freq")
    f=mc["finals"]; mn,mx=f[0],f[-1]; rng=mx-mn if mx!=mn else 1
    bw=rng/40; hist=[0]*40; bc=[mn+(i+.5)*bw for i in range(40)]
    for v in f: hist[min(int((v-mn)/rng*40),39)] += 1
    ax2.bar(bc,hist,width=bw*.9,color=[GREEN if c>=ACCOUNT_SIZE else RED for c in bc],alpha=0.8)
    for lv,c in [(ACCOUNT_SIZE,"#ffff88"),(mc["median"],GOLD),(mc["p5"],RED),(mc["p95"],GREEN)]:
        ax2.axvline(lv,color=c,linewidth=1.5)
    ax2.xaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"${v:,.0f}"))
    ax2.tick_params(axis="x",rotation=30,labelsize=6)
    _ax(ax3,"Drawdown Máximo (%)","DD Max%","Freq")
    pdd=[]
    for p in mc["paths"]:
        pk=p[0]; dd=0.0
        for e in p:
            if e>pk: pk=e
            if pk: dd=max(dd,(pk-e)/pk*100)
        pdd.append(dd)
    ax3.hist(pdd,bins=30,color=PURPLE,alpha=0.8,edgecolor=BG)
    avg=sum(pdd)/len(pdd)
    ax3.axvline(avg, color=GOLD, linewidth=2.0, label=f"Média {avg:.1f}%")
    ax3.axvline(25,  color=RED,  linewidth=1.5, linestyle="--", alpha=0.8, label="Limite 25%")
    ax3.legend(facecolor=DGRAY, labelcolor=WHITE, fontsize=7)
    plt.tight_layout(rect=[0,0,1,0.93])
    from pathlib import Path
    fname = str(Path(run_dir) / "charts" / f"montecarlo_{INTERVAL}.png")
    plt.savefig(fname, dpi=100, bbox_inches="tight", facecolor=BG)
    plt.close(); print(f"  Monte Carlo → {fname}")

def plot_trades(df, trades, symbol, run_dir=None):
    closed = [t for t in trades if t["result"] in ("WIN","LOSS")]
    if not closed: return
    wins   = [t for t in closed if t["result"]=="WIN"]
    losses = [t for t in closed if t["result"]=="LOSS"]
    all_i  = []
    for t in closed: all_i.extend([t["idx"]-20, t["entry_idx"]+t["duration"]+8])
    i0  = max(0, min(all_i)-5); i1 = min(len(df), max(all_i)+5)
    sub = df.iloc[i0:i1].reset_index(drop=True); off = i0
    wr_str = f"{len(wins)/len(closed)*100:.0f}%WR" if closed else "—"
    pnl_total = sum(t["pnl"] for t in closed)

    fig = plt.figure(figsize=(26,16), facecolor=BG)
    fig.suptitle(
        f"☿ AZOTH v3.6  ·  {symbol}  ·  {INTERVAL}  ·  "
        f"{len(closed)} trades  ·  {len(wins)}W/{len(losses)}L  ·  {wr_str}  ·  "
        f"PnL ${pnl_total:+,.0f}",
        color=GOLD, fontsize=12, y=0.99, fontweight="bold", fontfamily="monospace")
    gs2 = gridspec.GridSpec(5,1, figure=fig, height_ratios=[4,.5,1,.8,.8],
                            hspace=0.06, top=0.95, bottom=0.04, left=0.06, right=0.97)
    ax1 = fig.add_subplot(gs2[0]); _ax(ax1, ylabel="Preço")

    if "vol_regime" in sub.columns:
        vol_c_map = {"LOW":"#1e3a5f","HIGH":"#3b1f1f","EXTREME":"#4c1010"}
        prev_r = None; si = 0
        for xi,vr in enumerate(sub["vol_regime"].values):
            if vr != prev_r:
                if prev_r and prev_r in vol_c_map:
                    ax1.axvspan(si-.5, xi-.5, color=vol_c_map[prev_r], alpha=0.25, zorder=0)
                si = xi; prev_r = vr
        if prev_r and prev_r in vol_c_map:
            ax1.axvspan(si-.5, len(sub)-.5, color=vol_c_map[prev_r], alpha=0.25, zorder=0)

    for xi in range(len(sub)):
        o=sub["open"].iloc[xi]; c=sub["close"].iloc[xi]
        h=sub["high"].iloc[xi]; l=sub["low"].iloc[xi]
        col = GREEN if c>=o else RED
        ax1.plot([xi,xi],[l,h],color=col,linewidth=0.5,alpha=0.5)
        ax1.bar(xi, max(abs(c-o),0.0001), bottom=min(o,c), width=0.7, color=col, alpha=0.75, zorder=2)

    for s,ec,lw,lb in [(9,TEAL,.9,"EMA9"),(21,BLUE,1.4,"EMA21"),(50,PURPLE,1.3,"EMA50"),(200,"#fb923c",2.1,"EMA200")]:
        cn = f"ema{s}"
        if cn in sub.columns:
            ev=sub[cn].values; vx=[xi for xi,v in enumerate(ev) if not(isinstance(v,float) and math.isnan(v))]
            if vx: ax1.plot(vx,[ev[xi] for xi in vx],color=ec,linewidth=lw,alpha=0.85,label=lb)

    if "bb_upper" in sub.columns:
        bbu = sub["bb_upper"].values; bbl = sub["bb_lower"].values; bbm = sub["bb_mid"].values
        vx  = [xi for xi in range(len(sub)) if not(isinstance(bbu[xi],float) and math.isnan(bbu[xi]))]
        if vx:
            ax1.plot(vx, [bbu[xi] for xi in vx], color=TEAL, linewidth=0.7, alpha=0.5, linestyle="--", label="BB")
            ax1.plot(vx, [bbl[xi] for xi in vx], color=TEAL, linewidth=0.7, alpha=0.5, linestyle="--")
            ax1.plot(vx, [bbm[xi] for xi in vx], color=TEAL, linewidth=0.5, alpha=0.3, linestyle=":")

    for xi,v in enumerate(sub["swing_high"].values):
        if v>0: ax1.scatter(xi,v,marker="^",color="#fb923c",s=20,zorder=7,alpha=0.5)
    for xi,v in enumerate(sub["swing_low"].values):
        if v>0: ax1.scatter(xi,v,marker="v",color=BLUE,s=20,zorder=7,alpha=0.5)

    price_range = sub["high"].max() - sub["low"].min()
    offset_step  = price_range * 0.025
    entry_positions = {}
    for t in closed:
        ei = t["entry_idx"] - off
        if ei < 0 or ei >= len(sub): continue
        entry_positions[ei] = entry_positions.get(ei, 0) + 1
    annotation_slots: dict = {}

    for t in closed:
        ei = t["entry_idx"] - off
        xi = t["entry_idx"] + t["duration"] - off
        if ei < 0 or ei >= len(sub): continue
        xi  = min(xi, len(sub)-1)
        if t.get("chop_trade"):
            col = TEAL if t["result"] == "WIN" else PURPLE
        else:
            col = GREEN if t["result"] == "WIN" else RED
        mk  = "^" if t["direction"] == "BULLISH" else "v"

        nearby = sum(1 for e in entry_positions if abs(e - ei) <= 3 and entry_positions[e] > 0)
        dense  = nearby > 2

        x0 = max(0, ei-1); x1 = min(len(sub), xi+2)
        if not dense:
            ax1.hlines(t["stop"],   x0, x1, colors=RED,   lw=1.0, linestyle=":", alpha=0.55, zorder=3)
            ax1.hlines(t["target"], x0, x1, colors=GREEN, lw=1.0, linestyle="--",alpha=0.55, zorder=3)
            ax1.fill_between([max(0,ei-1), min(len(sub)-1,xi+1)],
                             t["entry"], t["stop"], color=RED, alpha=0.05, zorder=1)
        else:
            ax1.hlines(t["stop"],   x0, x1, colors=RED,   lw=0.6, linestyle=":", alpha=0.30, zorder=2)
            ax1.hlines(t["target"], x0, x1, colors=GREEN, lw=0.6, linestyle="--",alpha=0.30, zorder=2)

        ax1.hlines(t["entry"], x0, x1, colors=WHITE, lw=0.5, linestyle="-", alpha=0.15, zorder=2)
        mk_size = 200 if not dense else 100
        ax1.scatter(ei, t["entry"], marker=mk, color=col, s=mk_size,
                    zorder=10, edgecolors=WHITE, linewidths=1.2 if not dense else 0.7)
        ax1.scatter(xi, t["exit_p"], marker="D", color=col, s=60 if not dense else 30,
                    zorder=10, edgecolors=WHITE, linewidths=0.7)
        ax1.plot([ei, xi], [t["entry"], t["exit_p"]],
                 color=col, lw=1.0 if not dense else 0.5, alpha=0.4, linestyle="--", zorder=4)

        slot_key = round(ei / 3)
        used_y   = annotation_slots.get(slot_key, [])
        base_y   = (t["entry"] + t["exit_p"]) / 2
        cand_y = base_y
        for used in sorted(used_y):
            if abs(cand_y - used) < offset_step * 1.5:
                cand_y = used + offset_step * 1.8
        annotation_slots.setdefault(slot_key, []).append(cand_y)

        ann_x  = ei + (xi - ei) * 0.3
        type_pfx = "MR" if t.get("chop_trade") else ("L" if t["direction"] == "BULLISH" else "S")
        lbl = f"{type_pfx} ${t['pnl']:+.0f}\nΩ{t['score']:.2f}"
        fs  = 6 if not dense else 5
        ax1.annotate(lbl, (ann_x, cand_y), color=col, fontsize=fs,
                     ha="center", fontweight="bold",
                     bbox=dict(boxstyle="round,pad=0.15", facecolor=BG,
                               alpha=0.70, edgecolor="none"))

    from matplotlib.lines import Line2D
    handles,labels = ax1.get_legend_handles_labels()
    extra = [Line2D([0],[0],color=RED,lw=1.1,linestyle=":",label="Stop"),
             Line2D([0],[0],color=GREEN,lw=1.1,linestyle="--",label="Target"),
             Line2D([0],[0],color=LGRAY,lw=0,marker="^",markersize=8,label="Long"),
             Line2D([0],[0],color=LGRAY,lw=0,marker="v",markersize=8,label="Short"),
             Line2D([0],[0],color=TEAL,lw=1.0,linestyle="--",label="BB / CHOP-MR")]
    ax1.legend(handles=handles+extra, labels=labels+[e.get_label() for e in extra],
               facecolor=DGRAY,labelcolor=WHITE,fontsize=7,loc="upper left",ncol=9,framealpha=0.8)
    ax1.set_xlim(-1,len(sub)+1)

    ax_vs = fig.add_subplot(gs2[1],sharex=ax1)
    ax_vs.set_facecolor(PANEL); ax_vs.set_yticks([])
    ax_vs.set_ylabel("Vol",color=LGRAY,fontsize=6)
    for sp in ax_vs.spines.values(): sp.set_edgecolor(DGRAY)
    vol_cmap2 = {"LOW":BLUE,"NORMAL":LGRAY,"HIGH":"#fb923c","EXTREME":RED}
    if "vol_pct_rank" in sub.columns:
        vpr=sub["vol_pct_rank"].fillna(0.5).values
        vrc=[vol_cmap2.get(sub["vol_regime"].iloc[xi] if "vol_regime" in sub.columns else "NORMAL",LGRAY)
             for xi in range(len(sub))]
        ax_vs.bar(range(len(sub)),vpr,color=vrc,alpha=0.8,width=0.8)
        ax_vs.axhline(VOL_HIGH_PCT,color="#fb923c",lw=0.7,linestyle="--",alpha=0.6)
        ax_vs.axhline(VOL_LOW_PCT, color=BLUE,     lw=0.7,linestyle="--",alpha=0.6)
    ax_vs.set_ylim(0,1); ax_vs.tick_params(labelbottom=False,labelsize=5,colors=LGRAY)

    ax2=fig.add_subplot(gs2[2],sharex=ax1); _ax(ax2,ylabel="RSI")
    if "rsi" in sub.columns:
        rv=sub["rsi"].values
        vx=[xi for xi,v in enumerate(rv) if not(isinstance(v,float) and math.isnan(v))]
        vy=[rv[xi] for xi in vx]
        ax2.plot(vx,vy,color=GOLD,linewidth=1.2)
        ax2.fill_between(vx,50,vy,where=[v>50 for v in vy],color=GREEN,alpha=0.12)
        ax2.fill_between(vx,50,vy,where=[v<50 for v in vy],color=RED,alpha=0.12)
        for t in closed:
            ei2=t["entry_idx"]-off
            if 0<=ei2<len(sub):
                rv2=sub["rsi"].iloc[ei2]
                if not math.isnan(rv2):
                    c_dot = TEAL if t.get("chop_trade") else (GREEN if t["result"]=="WIN" else RED)
                    ax2.scatter(ei2,rv2,marker="o",color=c_dot,s=28,zorder=5,alpha=0.8)
    ax2.axhline(CHOP_RSI_SHORT, color=RED,   lw=0.8,linestyle="--",alpha=0.5)
    ax2.axhline(70, color=RED,  lw=0.5,linestyle=":",alpha=0.3)
    ax2.axhline(50,color=LGRAY,lw=0.5,linestyle="--",alpha=0.3)
    ax2.axhline(CHOP_RSI_LONG,  color=GREEN, lw=0.8,linestyle="--",alpha=0.5)
    ax2.axhline(30, color=GREEN,lw=0.5,linestyle=":",alpha=0.3)
    ax2.set_ylim(0,100)

    ax3=fig.add_subplot(gs2[3],sharex=ax1); _ax(ax3,ylabel="Flow")
    if "taker_ratio" in sub.columns:
        tr=sub["taker_ratio"].values
        vx=[xi for xi,v in enumerate(tr) if not(isinstance(v,float) and math.isnan(v))]
        vy=[tr[xi] for xi in vx]
        ax3.bar(vx,[(v-.5)*2 for v in vy],color=[GREEN if v>.5 else RED for v in vy],alpha=0.45,width=0.8)
        ax3.axhline(0,color=LGRAY,lw=0.8)
    if "taker_ma" in sub.columns:
        tm=sub["taker_ma"].values
        vx=[xi for xi,v in enumerate(tm) if not(isinstance(v,float) and math.isnan(v))]
        ax3.plot(vx,[(tm[xi]-.5)*2 for xi in vx],color=GOLD,lw=1.2)
    ax3.set_ylim(-1.1,1.1)

    ax4=fig.add_subplot(gs2[4],sharex=ax1); _ax(ax4,ylabel="Vol")
    vc=[GREEN if sub["close"].iloc[xi]>=sub["open"].iloc[xi] else RED for xi in range(len(sub))]
    ax4.bar(range(len(sub)),sub["vol"].values,color=vc,alpha=0.5,width=0.8)
    ax4.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v,_: f"{v/1e6:.1f}M"))
    step=max(1,len(sub)//14); tpos=list(range(0,len(sub),step))
    ax4.set_xticks(tpos)
    ax4.set_xticklabels([sub["time"].iloc[xi].strftime("%d/%m\n%Hh") for xi in tpos],
                        rotation=0,ha="center",fontsize=6,color=LGRAY)
    from pathlib import Path
    fname=str(Path(run_dir)/"charts"/f"trades_{symbol}_{INTERVAL}.png")
    plt.savefig(fname,dpi=120,bbox_inches="tight",facecolor=BG); plt.close()
    print(f"  Chart → {fname}")

SEP = "=" * 80

