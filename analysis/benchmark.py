"""AURUM — Benchmark comparison, bear market analysis, year-by-year."""
import requests
import numpy as np
from config.params import ACCOUNT_SIZE, SCAN_DAYS, INTERVAL
from analysis.stats import equity_stats, calc_ratios

def bear_market_analysis(all_trades: list) -> dict:
    regimes = {"BULL": [], "BEAR": [], "CHOP": []}
    for t in all_trades:
        b = t.get("macro_bias", "CHOP")
        if b in regimes:
            regimes[b].append(t)
    result = {}
    for regime, ts in regimes.items():
        closed = [t for t in ts if t["result"] in ("WIN","LOSS")]
        if not closed:
            result[regime] = None; continue
        w   = sum(1 for t in closed if t["result"] == "WIN")
        wr  = w / len(closed) * 100
        pnl = sum(t["pnl"] for t in closed)
        eq, _, mdd, _ = equity_stats([t["pnl"] for t in closed])
        r   = calc_ratios([t["pnl"] for t in closed])
        result[regime] = {
            "n":      len(closed),
            "wr":     round(wr, 1),
            "pnl":    round(pnl, 2),
            "sharpe": r["sharpe"],
            "max_dd": round(mdd, 1),
            "bull_n": sum(1 for t in closed if t["direction"]=="BULLISH"),
            "bear_n": sum(1 for t in closed if t["direction"]=="BEARISH"),
        }
    return result

def year_by_year_analysis(all_trades: list, start_equity: float = ACCOUNT_SIZE) -> dict:
    from collections import defaultdict
    by_year: dict[int, list] = defaultdict(list)
    for t in all_trades:
        ts = t.get("timestamp")
        if ts is None: continue
        yr = ts.year if hasattr(ts, "year") else int(str(ts)[:4])
        by_year[yr].append(t)

    years = sorted(by_year.keys())
    result = {}
    running_eq = start_equity

    for yr in years:
        ts_ = by_year[yr]
        closed = [t for t in ts_ if t["result"] in ("WIN", "LOSS")]
        if not closed:
            result[yr] = None; continue

        wins   = sum(1 for t in closed if t["result"] == "WIN")
        wr     = wins / len(closed) * 100
        pnl    = sum(t["pnl"] for t in closed)
        longs  = [t for t in closed if t["direction"] == "BULLISH"]
        shorts = [t for t in closed if t["direction"] == "BEARISH"]

        eq, _, mdd_pct, streak = equity_stats([t["pnl"] for t in closed], running_eq)
        roi = (eq[-1] - running_eq) / running_eq * 100

        bear_ts = [t for t in closed if t.get("macro_bias") == "BEAR"]
        bull_ts = [t for t in closed if t.get("macro_bias") == "BULL"]

        r = calc_ratios([t["pnl"] for t in closed], running_eq)

        result[yr] = {
            "n":       len(closed),
            "wins":    wins,
            "wr":      round(wr, 1),
            "pnl":     round(pnl, 2),
            "roi":     round(roi, 2),
            "mdd":     round(mdd_pct, 2),
            "sharpe":  r["sharpe"],
            "streak":  streak,
            "longs":   len(longs),
            "shorts":  len(shorts),
            "bear_n":  len(bear_ts),
            "bull_n":  len(bull_ts),
            "eq_end":  round(eq[-1], 2),
        }
        running_eq = eq[-1]

    return result

def print_year_by_year(yy: dict, start_equity: float = ACCOUNT_SIZE):
    years = [yr for yr, d in yy.items() if d is not None]
    if len(years) < 2:
        return

    S_ = "─" * 82
    print(f"\n  {'ANO':4s}  {'N':>4s}  {'WR':>6s}  {'ROI':>7s}  {'PnL':>10s}  "
          f"{'MaxDD':>6s}  {'Sharpe':>7s}  {'L/S':>7s}  {'BEAR/BULL':>9s}  STATUS")
    print(f"  {S_}")

    for yr in sorted(years):
        d = yy[yr]
        if d is None:
            print(f"  {yr}  sem trades"); continue

        sh     = d["sharpe"] or 0.0
        roi_s  = f"{d['roi']:>+6.1f}%"

        if   d["roi"] > 15 and d["mdd"] < 15: status = "✓ BOM"
        elif d["roi"] > 0:                    status = "~ OK"
        elif d["roi"] == 0:                   status = "= NEUTRO"
        else:                                 status = "✗ PERDA"

        print(f"  {yr}  {d['n']:>4d}  {d['wr']:>5.1f}%  {roi_s}  "
              f"${d['pnl']:>+8,.0f}  {d['mdd']:>5.1f}%  {sh:>7.3f}  "
              f"L{d['longs']}/S{d['shorts']}  "
              f"B{d['bear_n']}/U{d['bull_n']}   {status}")

    print(f"  {S_}")
    print()
    max_abs = max(abs(yy[yr]["roi"]) for yr in years if yy[yr]) or 1
    bar_max = 30
    for yr in sorted(years):
        d = yy[yr]
        if not d: continue
        bar_len = int(abs(d["roi"]) / max_abs * bar_max)
        bar_c   = "█" if d["roi"] >= 0 else "░"
        bar     = bar_c * bar_len
        sign    = "+" if d["roi"] >= 0 else "-"
        print(f"  {yr}  {sign}{abs(d['roi']):>5.1f}%  {bar}")

    pos_years = sum(1 for yr in years if yy[yr] and yy[yr]["roi"] > 0)
    print(f"\n  ► {pos_years}/{len(years)} anos positivos  |  "
          f"Capital: ${start_equity:,.0f} → ${yy[sorted(years)[-1]]['eq_end']:,.0f}")

def print_bear_market_enhanced(bm: dict, yy: dict):
    print(f"\n  PERFORMANCE POR REGIME MACRO")
    print(f"  {'─'*72}")
    print(f"  {'REGIME':6s}  {'N':>4s}  {'WR':>6s}  {'Sharpe':>7s}  "
          f"{'MaxDD':>6s}  {'L/S':>7s}  {'PnL':>12s}  EDGE?")
    print(f"  {'─'*72}")

    icons = {"BULL": "↑", "BEAR": "↓", "CHOP": "↔"}
    totals = {}
    for regime in ("BULL", "BEAR", "CHOP"):
        d = bm.get(regime)
        if not d:
            print(f"  {icons.get(regime,'')} {regime:5s}   sem dados"); continue
        sh   = d["sharpe"] or 0.0
        edge = "✓" if d["wr"] >= 50 and d["pnl"] > 0 else "~" if d["pnl"] > 0 else "✗"
        bar_len = min(20, max(0, int(abs(d["pnl"]) / 300)))
        bar = ("█" * bar_len if d["pnl"] >= 0 else "░" * bar_len)
        print(f"  {icons.get(regime,'')} {regime:5s}  {d['n']:>4d}  {d['wr']:>5.1f}%  "
              f"{sh:>7.3f}  {d['max_dd']:>5.1f}%  "
              f"L{d['bull_n']}/S{d['bear_n']}  ${d['pnl']:>+10,.0f}  {edge}  {bar}")
        totals[regime] = d

    bear = totals.get("BEAR")
    bull = totals.get("BULL")
    chop = totals.get("CHOP")
    print()
    if bear and bear["pnl"] > 0:
        print(f"  ► BEAR: lucrativo em crash  (+${bear['pnl']:,.0f}, WR {bear['wr']:.1f}%) — edge anti-cíclico ✓")
    if bull and bull["pnl"] > 0:
        print(f"  ► BULL: lucrativo em alta   (+${bull['pnl']:,.0f}, WR {bull['wr']:.1f}%) — edge bidirecional ✓")
    elif bull and bull["pnl"] < 0:
        print(f"  ► BULL: perdendo em alta     (${bull['pnl']:,.0f}, WR {bull['wr']:.1f}%) — SHORT bias confirmado")
    if chop and chop["n"] > 0:
        chop_mr_n = chop["n"]
        print(f"  ► CHOP: {chop_mr_n} trades (inclui CHOP-MR [U3])  WR {chop['wr']:.1f}%  ${chop['pnl']:,.0f}")
    if bear and bull and bear["wr"] > bull["wr"]:
        delta = bear["wr"] - bull["wr"]
        print(f"  ► SHORT bias: WR BEAR {bear['wr']:.1f}% vs BULL {bull['wr']:.1f}% "
              f"(Δ+{delta:.1f}%) — sistema SHORT-dominant")

def _fetch_yahoo(ticker: str, n_days: int) -> dict | None:
    import time as _t
    end_ts   = int(_t.time())
    start_ts = end_ts - n_days * 86400 - 86400
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?interval=1d&period1={start_ts}&period2={end_ts}")
    try:
        r = requests.get(url, timeout=10, headers={"User-Agent":"Mozilla/5.0"})
        if r.status_code != 200: return None
        result = r.json()["chart"]["result"]
        if not result: return None
        closes = result[0]["indicators"]["quote"][0]["close"]
        closes = [c for c in closes if c is not None]
        if len(closes) < 5: return None
        return {"first": closes[0], "last": closes[-1], "closes": closes}
    except Exception:
        return None

def _bm_maxdd(closes: list) -> float:
    peak = closes[0]; mdd = 0.0
    for c in closes:
        if c > peak: peak = c
        dd = (peak-c)/peak*100
        if dd > mdd: mdd = dd
    return round(mdd, 2)

def _bm_sharpe(closes: list) -> float | None:
    if len(closes) < 10: return None
    rets = [(closes[i]-closes[i-1])/closes[i-1] for i in range(1, len(closes))]
    n = len(rets); mean = sum(rets)/n
    std = (sum((r-mean)**2 for r in rets)/(n-1))**0.5 if n>1 else 0
    return round((mean/std)*(252**0.5), 3) if std else None

def print_benchmark(azoth_roi: float, azoth_sharpe: float,
                    azoth_mdd: float, n_days: int):
    S = "─" * 80
    print(f"\n{S}")
    print(f"  BENCHMARK   AZOTH v3.6  vs  Buy-and-Hold  ({n_days} dias)")
    print(S)

    specs = [
        ("BTC-USD",  "Bitcoin (BTC)"),
        ("SPY",      "S&P 500 (SPY) "),
        ("GC=F",     "Ouro (XAU)    "),
        ("^DXY",     "Dólar (DXY)   "),
    ]

    rows = []
    for ticker, label in specs:
        d = _fetch_yahoo(ticker, n_days)
        if d:
            roi    = round((d["last"]-d["first"])/d["first"]*100, 2)
            mdd    = _bm_maxdd(d["closes"])
            sharpe = _bm_sharpe(d["closes"])
            rows.append((label, roi, mdd, sharpe))
        else:
            rows.append((label, None, None, None))

    print(f"  {'Ativo':20s}  {'ROI':>8s}  {'MaxDD':>7s}  {'Sharpe':>8s}  {'AZOTH alpha':>12s}")
    print(f"  {'─'*20}  {'─'*8}  {'─'*7}  {'─'*8}  {'─'*12}")

    valid_rois = []
    for label, roi, mdd, sharpe in rows:
        if roi is None:
            print(f"  {label:20s}  {'—':>8s}  {'—':>7s}  {'—':>8s}  {'N/A':>12s}")
            continue
        roi_s = f"{roi:+.1f}%"
        mdd_s = f"{mdd:.1f}%"
        sh_s  = f"{sharpe:.3f}" if sharpe else "—"
        alpha = azoth_roi - roi
        alp_s = f"{alpha:+.1f}pp"
        marker = " ◄ AZOTH lidera" if alpha > 0 else " ✗ AZOTH atrás "
        print(f"  {label:20s}  {roi_s:>8s}  {mdd_s:>7s}  {sh_s:>8s}  {alp_s:>6s}{marker}")
        valid_rois.append(roi)

    print(f"  {'─'*20}  {'─'*8}  {'─'*7}  {'─'*8}  {'─'*12}")
    az_roi = f"{azoth_roi:+.1f}%"
    az_mdd = f"{azoth_mdd:.1f}%"
    az_sh  = f"{azoth_sharpe:.3f}"
    print(f"  {'☿ AZOTH v3.6':20s}  {az_roi:>8s}  {az_mdd:>7s}  {az_sh:>8s}  {'◄ REFERÊNCIA':>12s}")

    if valid_rois:
        beat = sum(1 for r in valid_rois if azoth_roi > r)
        best = max(valid_rois)
        print(f"\n  ► AZOTH supera {beat}/{len(valid_rois)} benchmarks   "
              f"Melhor bench: {best:+.1f}%   "
              f"Alpha s/ melhor: {azoth_roi-best:+.1f}pp   "
              f"MaxDD AZOTH {azoth_mdd:.1f}% vs BTC {rows[0][2] or 0:.1f}%")
    print(S)

