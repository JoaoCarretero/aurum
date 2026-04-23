"""AURUM — Equity statistics and conditional analysis."""
import numpy as np
from config.params import ACCOUNT_SIZE

def equity_stats(pnl_list, start=ACCOUNT_SIZE):
    eq = [start]
    for p in pnl_list: eq.append(eq[-1]+p)
    peak, mdd, mdd_pct, streak, ms = start, 0.0, 0.0, 0, 0
    for e in eq:
        if e > peak: peak = e
        dd = peak-e; dp = dd/peak*100 if peak else 0
        if dd > mdd: mdd = dd; mdd_pct = dp
    for p in pnl_list:
        streak = streak+1 if p<0 else 0
        ms = max(ms, streak)
    return eq, round(mdd,2), round(mdd_pct,2), ms

def calc_ratios(pnl_list, start=ACCOUNT_SIZE, n_days=None):
    if len(pnl_list) < 2: return {"sharpe":None,"sortino":None,"calmar":None,"ret":0.0,"sharpe_daily":None}
    n      = len(pnl_list)
    mean   = sum(pnl_list)/n
    std    = (sum((p-mean)**2 for p in pnl_list)/(n-1))**0.5
    n_loss = sum(1 for p in pnl_list if p < 0)
    dd_std = (sum(p**2 for p in pnl_list if p<0)/max(n_loss,1))**0.5
    eq,_,mdd_pct,_ = equity_stats(pnl_list, start)
    ret = (eq[-1]-start)/start*100
    _days  = n_days if (n_days and n_days > 0) else 180
    tpy    = n * 365.0 / _days          # trades por ano
    ann    = tpy ** 0.5                 # anualizador per-trade
    dpd    = n / _days                  # trades por dia
    # Sharpe diário: agrega PnL em dias, calcula Sharpe sobre retornos diários
    daily: dict = {}
    for i, p in enumerate(pnl_list):
        day = int(i / max(dpd, 0.01))
        daily[day] = daily.get(day, 0.0) + p
    d_rets = list(daily.values())
    d_mean = sum(d_rets) / len(d_rets) if d_rets else 0
    d_std  = (sum((r-d_mean)**2 for r in d_rets)/max(len(d_rets)-1,1))**0.5
    sharpe_daily = round((d_mean/d_std)*(252**0.5), 3) if d_std else None
    return {
        "sharpe":       round((mean/std)*ann, 3)    if std    else None,
        "sharpe_daily": sharpe_daily,                           # R5: Sharpe diário (benchmark-comparable)
        "sortino":      round((mean/dd_std)*ann, 3) if dd_std else None,
        "calmar":       round(ret/mdd_pct, 3)       if mdd_pct else None,
        "ret":          round(ret, 2),
    }

def extended_metrics(pnl_list, start=ACCOUNT_SIZE):
    """Compute extended performance metrics for terminal display."""
    if not pnl_list:
        return {}
    wins = [p for p in pnl_list if p > 0]
    losses = [p for p in pnl_list if p <= 0]
    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 0
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else float('inf')
    avg_win = round(sum(wins) / len(wins), 2) if wins else 0
    avg_loss = round(sum(losses) / len(losses), 2) if losses else 0
    payoff = round(avg_win / abs(avg_loss), 2) if avg_loss != 0 else float('inf')
    expectancy = round(sum(pnl_list) / len(pnl_list), 2)
    best = round(max(pnl_list), 2)
    worst = round(min(pnl_list), 2)

    # Max consecutive losses
    streak, max_streak = 0, 0
    for p in pnl_list:
        streak = streak + 1 if p < 0 else 0
        max_streak = max(max_streak, streak)

    # Recovery: trades from max DD trough back to previous peak
    eq = [start]
    for p in pnl_list:
        eq.append(eq[-1] + p)
    peak = start
    trough_idx = 0
    max_dd_val = 0
    for i, e in enumerate(eq):
        if e > peak:
            peak = e
        dd = peak - e
        if dd > max_dd_val:
            max_dd_val = dd
            trough_idx = i
    # Find recovery from trough
    recovery = 0
    if trough_idx < len(eq) - 1:
        trough_peak = eq[trough_idx]
        for j in range(trough_idx + 1, len(eq)):
            if eq[j] >= peak:
                recovery = j - trough_idx
                break
        if recovery == 0:
            recovery = len(eq) - 1 - trough_idx  # still recovering

    # Max DD in dollars
    max_dd_dollars = round(max_dd_val, 2)

    # Ulcer Index: RMS of drawdown percentages
    peaks = []
    p = start
    for e in eq:
        p = max(p, e)
        peaks.append(p)
    dd_pcts = [(peaks[i] - eq[i]) / peaks[i] * 100 if peaks[i] > 0 else 0
               for i in range(len(eq))]
    ulcer = round((sum(d ** 2 for d in dd_pcts) / len(dd_pcts)) ** 0.5, 2)

    return {
        "profit_factor": profit_factor,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "payoff_ratio": payoff,
        "expectancy": expectancy,
        "best_trade": best,
        "worst_trade": worst,
        "max_consec_loss": max_streak,
        "recovery_trades": recovery,
        "max_dd_dollars": max_dd_dollars,
        "ulcer_index": ulcer,
    }


def conditional_backtest(trades):
    buckets = {"0.53-0.59":[], "0.59-0.65":[], "0.65+":[]}
    for t in trades:
        s = t["score"]
        if   s < 0.59: buckets["0.53-0.59"].append(t)
        elif s < 0.65: buckets["0.59-0.65"].append(t)
        else:          buckets["0.65+"].append(t)
    out = {}
    for label, ts in buckets.items():
        c = [t for t in ts if t["result"] in ("WIN","LOSS")]
        if not c: out[label]=None; continue
        w   = [t for t in c if t["result"]=="WIN"]
        l   = [t for t in c if t["result"]=="LOSS"]
        wr  = len(w)/len(c)*100
        aw  = sum(t["pnl"] for t in w)/max(len(w),1)
        al  = sum(t["pnl"] for t in l)/max(len(l),1)
        exp = wr/100*aw + (1-wr/100)*al
        out[label] = {"n":len(c),"wr":round(wr,1),
                      "avg_rr":round(sum(t["rr"] for t in c)/len(c),2),
                      "exp":round(exp,2),"total":round(sum(t["pnl"] for t in c),2)}
    return out

