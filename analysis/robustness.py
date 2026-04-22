"""AURUM — Symbol robustness analysis."""
from collections import defaultdict
from config.params import SCAN_DAYS
from analysis.stats import equity_stats, calc_ratios

def symbol_robustness(all_trades):
    SYM_TRAIN, SYM_TEST = 8, 4
    by_sym = defaultdict(list)
    for t in all_trades: by_sym[t["symbol"]].append(t)
    results = {}
    for sym, trades in by_sym.items():
        closed = sorted([t for t in trades if t["result"] in ("WIN","LOSS")],
                        key=lambda x: x["timestamp"])
        pnl_s = [t["pnl"] for t in closed]
        r     = calc_ratios(pnl_s, n_days=SCAN_DAYS) if len(closed) >= 2 else {"sharpe":None,"calmar":None,"ret":0}
        _,_,mdd,_ = equity_stats(pnl_s) if pnl_s else ([0],0,0,0)
        wr = sum(1 for t in closed if t["result"]=="WIN")/max(len(closed),1)*100
        wf_ok = wf_tot = 0
        i = 0
        while i + SYM_TRAIN + SYM_TEST <= len(closed):
            tr  = closed[i:i+SYM_TRAIN]
            te  = closed[i+SYM_TRAIN:i+SYM_TRAIN+SYM_TEST]
            wtr = sum(1 for t in tr if t["result"]=="WIN")/len(tr)*100
            wte = sum(1 for t in te if t["result"]=="WIN")/len(te)*100
            if abs(wte-wtr) <= 35: wf_ok += 1
            wf_tot += 1; i += SYM_TEST
        results[sym] = {
            "n":      len(closed),
            "wr":     round(wr, 1),
            "sharpe": r["sharpe"],
            "max_dd": round(mdd, 1),
            "stable": round(wf_ok/wf_tot*100, 0) if wf_tot else None,
            "pnl":    round(sum(pnl_s), 2),
        }
    return results

BG,PANEL = "#0a0a12","#0f0f1a"
GOLD,GREEN,RED,BLUE,PURPLE,TEAL = "#e8b84b","#26d47c","#e85d5d","#4a9eff","#9b7fe8","#2dd4bf"
LGRAY,DGRAY,WHITE = "#6b7280","#1f2937","#f0f0f0"

def print_symbol_robustness(r):
    print(f"  {'─'*74}")
    print(f"  {'ATIVO':12s}  {'N':>3s}  {'WR':>6s}  {'Sharpe':>7s}  {'MaxDD':>6s}  {'WF%':>5s}  {'PnL':>12s}  STATUS")
    print(f"  {'─'*74}")
    for sym, d in sorted(r.items(), key=lambda x: (x[1].get("sharpe") or -99), reverse=True):
        sh   = d["sharpe"] or 0.0
        stb  = d["stable"]
        stb_str = f"{stb:>4.0f}%" if stb is not None else "  N/A"
        status = ("✓ ROBUSTO" if sh>0.3 and (stb or 0)>=60
                  else "~ FRÁGIL" if (d["pnl"] or 0)>0
                  else "✗ DROPAR")
        print(f"  {sym:12s}  {d['n']:>3d}  {d['wr']:>5.1f}%  {sh:>7.3f}  "
              f"{d['max_dd']:>5.1f}%  {stb_str}  ${d['pnl']:>+10,.0f}  {status}")

    pos_pnls = {s: (v["pnl"] or 0) for s, v in r.items() if (v["pnl"] or 0) > 0}
    total_pos = sum(pos_pnls.values())
    if total_pos > 0:
        top_sym = max(pos_pnls, key=pos_pnls.get)
        top_pct = pos_pnls[top_sym] / total_pos * 100
        if top_pct > 50:
            print(f"\n  ⚠ CONCENTRAÇÃO: {top_sym} representa {top_pct:.0f}% do PnL positivo "
                  f"(${pos_pnls[top_sym]:,.0f}/{total_pos:,.0f})")
            print(f"    → sem esse símbolo o portfólio seria: "
                  f"${total_pos - pos_pnls[top_sym]:,.0f}")


