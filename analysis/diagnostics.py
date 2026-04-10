"""
AURUM Finance — Diagnostico Empirico
Medir antes de cortar. Dados, nao opinioes.
"""
import json, sys, math
import numpy as np
from collections import defaultdict
from pathlib import Path


def score_calibration(trades, step=0.02):
    """Bucket fino do score -> WR, expectancy, monotonicity."""
    WR_ASSUMED = {0.53: 0.50, 0.55: 0.50, 0.57: 0.50, 0.59: 0.55,
                  0.61: 0.55, 0.63: 0.55, 0.65: 0.60, 0.67: 0.60, 0.69: 0.60}
    scores = sorted(set(round(t["score"], 4) for t in trades))
    lo = math.floor(min(scores) / step) * step
    hi = math.ceil(max(scores) / step) * step + step
    buckets = {}
    edges = []
    s = lo
    while s < hi:
        label = f"{s:.2f}-{s+step:.2f}"
        ts = [t for t in trades if s <= t["score"] < s + step]
        if ts:
            wins = [t for t in ts if t["result"] == "WIN"]
            losses = [t for t in ts if t["result"] == "LOSS"]
            wr = len(wins) / len(ts) * 100
            avg_w = sum(t["pnl"] for t in wins) / max(len(wins), 1)
            avg_l = sum(t["pnl"] for t in losses) / max(len(losses), 1)
            exp = wr / 100 * avg_w + (1 - wr / 100) * avg_l
            total = sum(t["pnl"] for t in ts)
            mid = s + step / 2
            wr_key = max(k for k in WR_ASSUMED if k <= mid) if mid >= 0.53 else 0.50
            wr_assumed = WR_ASSUMED.get(wr_key, 0.50) * 100
            wr_err = wr - wr_assumed
            buckets[label] = {
                "n": len(ts), "wr": round(wr, 1), "exp": round(exp, 2),
                "avg_w": round(avg_w, 2), "avg_l": round(avg_l, 2),
                "total": round(total, 2),
                "wr_assumed": round(wr_assumed, 1), "wr_err": round(wr_err, 1),
            }
            edges.append(wr)
        s += step
    mono = True
    violations = 0
    for i in range(1, len(edges)):
        if edges[i] < edges[i - 1] - 5:
            mono = False; violations += 1
    print("  +-- SCORE CALIBRATION --------------------------------------------+")
    print(f"  | {'Bucket':>11s}  {'N':>4s}  {'WR%':>6s}  {'Assumed':>7s}  {'D':>6s}  {'Expect':>8s}  {'Total$':>10s} |")
    print(f"  | {'---'*21} |")
    for label, d in buckets.items():
        flag = "X" if abs(d["wr_err"]) > 5 else " "
        print(f"  | {label:>11s}  {d['n']:>4d}  {d['wr']:>5.1f}%  {d['wr_assumed']:>5.1f}%  "
              f"{d['wr_err']:>+5.1f}  ${d['exp']:>+7.2f}  ${d['total']:>+9.2f} {flag}|")
    tag = "MONOTONICO" if mono else f"NAO MONOTONICO ({violations} violacoes)"
    print(f"  | {tag:>62s} |")
    print(f"  +{'---'*22}+")
    return {"buckets": buckets, "monotonic": mono, "violations": violations,
            "wr_calibration_errors": {k: v["wr_err"] for k, v in buckets.items()}}


def omega_component_correlation(trades):
    """Correlacao entre os 5 componentes do omega + information gain."""
    keys = ["omega_struct", "omega_flow", "omega_cascade", "omega_momentum", "omega_pullback"]
    labels = ["struct", "flow", "cascade", "momentum", "pullback"]
    trend = [t for t in trades if not t.get("chop_trade", False)]
    if len(trend) < 20:
        print("  ! Poucos trend trades para analise de componentes"); return {}
    data = np.array([[t[k] for k in keys] for t in trend])
    corr = np.corrcoef(data.T)
    info_gain = {}
    for i, label in enumerate(labels):
        col = data[:, i]; med = np.median(col)
        above = [t for t, v in zip(trend, col) if v >= med]
        below = [t for t, v in zip(trend, col) if v < med]
        wr_above = sum(1 for t in above if t["result"] == "WIN") / max(len(above), 1) * 100
        wr_below = sum(1 for t in below if t["result"] == "WIN") / max(len(below), 1) * 100
        info_gain[label] = {"wr_above": round(wr_above, 1), "wr_below": round(wr_below, 1),
                             "delta": round(wr_above - wr_below, 1),
                             "useful": abs(wr_above - wr_below) > 3}
    alerts = []
    print("\n  +-- OMEGA COMPONENT CORRELATION -----------------------------------+")
    print(f"  | {'':>10s}", end="")
    for l in labels: print(f"  {l[:6]:>6s}", end="")
    print("  |")
    for i, l1 in enumerate(labels):
        print(f"  | {l1:>10s}", end="")
        for j, l2 in enumerate(labels):
            v = corr[i, j]
            mark = "#" if abs(v) > 0.70 and i != j else "+" if abs(v) > 0.50 and i != j else " "
            print(f"  {v:>5.2f}{mark}", end="")
            if i < j and abs(v) > 0.50: alerts.append((l1, l2, v))
        print("  |")
    print(f"  |  INFORMATION GAIN:{'':>44s}|")
    for label, d in info_gain.items():
        flag = "Y" if d["useful"] else "N"
        print(f"  |  {label:>10s}  above={d['wr_above']:>5.1f}%  below={d['wr_below']:>5.1f}%  "
              f"D={d['delta']:>+5.1f}pp  {flag}{'':>11s}|")
    if alerts:
        print(f"  |  ! ALERTAS:{'':>51s}|")
        for l1, l2, v in alerts:
            sev = "ALTA" if abs(v) > 0.70 else "MOD "
            print(f"  |    {sev} {l1}x{l2} = {v:.2f}{'':>{52-len(l1)-len(l2)}s}|")
    print(f"  +{'---'*22}+")
    return {"matrix": corr.tolist(), "info_gain": info_gain, "alerts": alerts}


def ablation_test(trades):
    """Testar contribuicao de cada filtro usando metadados dos trades."""
    results = {}
    for thresh in [0.50, 0.53, 0.55, 0.58, 0.60]:
        subset = [t for t in trades if t["score"] >= thresh and not t.get("chop_trade")]
        if subset:
            wr = sum(1 for t in subset if t["result"] == "WIN") / len(subset) * 100
            exp = sum(t["pnl"] for t in subset) / len(subset)
            results[f"threshold_{thresh}"] = {"n": len(subset), "wr": round(wr, 1), "exp": round(exp, 2)}
    for regime in ["BULL", "BEAR", "CHOP"]:
        subset = [t for t in trades if t.get("macro_bias") == regime]
        if subset:
            wr = sum(1 for t in subset if t["result"] == "WIN") / len(subset) * 100
            exp = sum(t["pnl"] for t in subset) / len(subset)
            total = sum(t["pnl"] for t in subset)
            results[f"regime_{regime}"] = {"n": len(subset), "wr": round(wr, 1), "exp": round(exp, 2), "total": round(total, 2)}
    for vol in ["LOW", "NORMAL", "HIGH"]:
        subset = [t for t in trades if t.get("vol_regime") == vol]
        if subset:
            wr = sum(1 for t in subset if t["result"] == "WIN") / len(subset) * 100
            exp = sum(t["pnl"] for t in subset) / len(subset)
            results[f"vol_{vol}"] = {"n": len(subset), "wr": round(wr, 1), "exp": round(exp, 2)}
    penalized = [t for t in trades if t.get("corr_mult", 1.0) < 1.0]
    normal = [t for t in trades if t.get("corr_mult", 1.0) >= 1.0]
    if penalized:
        results["corr_penalized"] = {"n": len(penalized), "wr": round(sum(1 for t in penalized if t["result"] == "WIN") / len(penalized) * 100, 1)}
        results["corr_normal"] = {"n": len(normal), "wr": round(sum(1 for t in normal if t["result"] == "WIN") / max(len(normal), 1) * 100, 1)}
    chop = [t for t in trades if t.get("chop_trade")]
    trend = [t for t in trades if not t.get("chop_trade")]
    if chop:
        results["chop_trades"] = {"n": len(chop), "wr": round(sum(1 for t in chop if t["result"] == "WIN") / len(chop) * 100, 1),
                                   "total": round(sum(t["pnl"] for t in chop), 2)}
        results["trend_trades"] = {"n": len(trend), "wr": round(sum(1 for t in trend if t["result"] == "WIN") / max(len(trend), 1) * 100, 1),
                                    "total": round(sum(t["pnl"] for t in trend), 2)}
    for d in ["BULLISH", "BEARISH"]:
        subset = [t for t in trades if t["direction"] == d]
        if subset:
            results[f"dir_{d}"] = {"n": len(subset), "wr": round(sum(1 for t in subset if t["result"] == "WIN") / len(subset) * 100, 1),
                                    "total": round(sum(t["pnl"] for t in subset), 2)}
    # Print
    print("\n  +-- ABLATION TEST ------------------------------------------------+")
    print(f"  | {'Filter':>20s}  {'N':>4s}  {'WR%':>6s}  {'Expect':>8s}  {'Total$':>10s}     |")
    sections = [("SCORE THRESHOLD", "threshold"), ("REGIME MACRO", "regime"),
                ("VOL REGIME", "vol"), ("CORRELATION", "corr"),
                ("TRADE TYPE", "chop,trend"), ("DIRECTION", "dir")]
    for section, prefix in sections:
        keys = [k for k in results if any(k.startswith(p) for p in prefix.split(","))]
        if not keys: continue
        print(f"  |  {section}{'':>{60-len(section)}s} |")
        for k in keys:
            d = results[k]
            exp_s = f"${d.get('exp', 0):>+7.2f}" if "exp" in d else f"{'':>8s}"
            tot_s = f"${d.get('total', 0):>+9.2f}" if "total" in d else f"{'':>10s}"
            print(f"  |   {k:>19s}  {d['n']:>4d}  {d['wr']:>5.1f}%  {exp_s}  {tot_s}     |")
    print(f"  +{'---'*22}+")
    return results


def execution_realism_test(trades):
    """Stress test de slippage progressivo + breakeven."""
    LEVERAGE, COMMISSION = 1.0, 0.0004
    scenarios = {"CURRENT": 0.0003, "MODERATE": 0.0006, "PESSIMIST": 0.0012, "ADVERSARIAL": 0.0020}
    results = {}
    for name, slip in scenarios.items():
        new_pnls = []; flipped = 0
        for t in trades:
            entry, exit_p, size, d, dur = t["entry"], t["exit_p"], t["size"], t["direction"], t["duration"]
            funding = 0.0001 * dur / 32
            if d == "BULLISH":
                pnl = size * (exit_p * (1 - COMMISSION - slip) - entry * (1 + COMMISSION + slip)) - size * entry * funding
            else:
                pnl = size * (entry * (1 - COMMISSION - slip) - exit_p * (1 + COMMISSION + slip)) + size * entry * funding
            pnl *= LEVERAGE; new_pnls.append(pnl)
            if t["result"] == "WIN" and pnl < 0: flipped += 1
        total = sum(new_pnls); wr = sum(1 for p in new_pnls if p > 0) / len(new_pnls) * 100
        results[name] = {"total": round(total, 2), "wr": round(wr, 1), "flipped": flipped, "slip_bps": round(slip * 10000, 1)}
    be_slip = None
    for test_slip in range(1, 50):
        s = test_slip * 0.0001; total = 0
        for t in trades:
            entry, exit_p, size, d, dur = t["entry"], t["exit_p"], t["size"], t["direction"], t["duration"]
            funding = 0.0001 * dur / 32
            if d == "BULLISH":
                pnl = size * (exit_p * (1 - COMMISSION - s) - entry * (1 + COMMISSION + s)) - size * entry * funding
            else:
                pnl = size * (entry * (1 - COMMISSION - s) - exit_p * (1 + COMMISSION + s)) + size * entry * funding
            total += pnl * LEVERAGE
        if total <= 0: be_slip = s; break
    print("\n  +-- EXECUTION STRESS TEST ----------------------------------------+")
    print(f"  | {'Scenario':>12s}  {'Slip':>6s}  {'WR%':>6s}  {'Flipped':>7s}  {'Total PnL':>12s}     |")
    for name, d in results.items():
        print(f"  | {name:>12s}  {d['slip_bps']:>4.1f}bp  {d['wr']:>5.1f}%  {d['flipped']:>7d}  ${d['total']:>+11.2f}     |")
    if be_slip:
        health = "ROBUSTO" if be_slip >= 0.0010 else "FRAGIL" if be_slip >= 0.0005 else "PERIGOSO"
        print(f"  |  BREAKEVEN: {be_slip*10000:.1f}bp  {health}{'':>{47-len(health)}s}|")
    else:
        print(f"  |  BREAKEVEN: >50bp (muito robusto){'':>29s}|")
    print(f"  +{'---'*22}+")
    results["breakeven_slippage"] = be_slip
    return results


def time_analysis(trades):
    """Analise de padroes temporais."""
    # Hour of day (4h blocks)
    by_hour = defaultdict(list)
    for t in trades:
        try:
            hour = int(t.get("time", "").split()[1].replace("h", ""))
            block = (hour // 4) * 4
            by_hour[f"{block:02d}-{block+4:02d}h"].append(t)
        except Exception:
            pass
    hour_results = {}
    for block in sorted(by_hour.keys()):
        ts = by_hour[block]
        hour_results[block] = {"n": len(ts), "wr": round(sum(1 for t in ts if t["result"] == "WIN") / len(ts) * 100, 1)}
    # Duration buckets
    dur_results = {}
    for label, lo, hi in [("<=6", 0, 6), ("7-20", 7, 20), (">20", 21, 9999)]:
        subset = [t for t in trades if lo <= t["duration"] <= hi]
        if subset:
            wr = sum(1 for t in subset if t["result"] == "WIN") / len(subset) * 100
            exp = sum(t["pnl"] for t in subset) / len(subset)
            dur_results[label] = {"n": len(subset), "wr": round(wr, 1), "exp": round(exp, 2)}
    print("\n  +-- TIME ANALYSIS ------------------------------------------------+")
    for block, d in hour_results.items():
        bar = "#" * int(d["wr"] / 5)
        print(f"  |    {block:>8s}  n={d['n']:>3d}  WR={d['wr']:>5.1f}%  {bar:<20s}|")
    print(f"  |  DURACAO:{'':>54s}|")
    for label, d in dur_results.items():
        print(f"  |    {label:>6s}  n={d['n']:>3d}  WR={d['wr']:>5.1f}%  exp=${d['exp']:>+7.2f}{'':>22s}|")
    print(f"  +{'---'*22}+")
    return {"hours": hour_results, "duration": dur_results}


def run_full_diagnostic(trades):
    closed = [t for t in trades if t["result"] in ("WIN", "LOSS")]
    if not closed:
        print("  Sem trades fechados para diagnostico."); return {}
    wins = sum(1 for t in closed if t["result"] == "WIN")
    total_pnl = sum(t["pnl"] for t in closed)
    print(f"\n{'='*68}")
    print(f"  DIAGNOSTICO EMPIRICO -- {len(closed)} trades  WR={wins/len(closed)*100:.1f}%  PnL=${total_pnl:+,.2f}")
    print(f"{'='*68}")
    cal = score_calibration(closed)
    corr = omega_component_correlation(closed)
    abl = ablation_test(closed)
    exe = execution_realism_test(closed)
    time_a = time_analysis(closed)
    # Veredicto
    print(f"\n{'='*68}")
    print(f"  VEREDICTO")
    print(f"{'='*68}")
    issues, goods = [], []
    if not cal["monotonic"]:
        issues.append(f"Score NAO monotonico ({cal['violations']} violacoes)")
    else: goods.append("Score monotonico")
    if any(abs(v) > 10 for v in cal.get("wr_calibration_errors", {}).values()):
        issues.append("Kelly WR diverge >10pp -- sizing descalibrado")
    high_corr = [a for a in corr.get("alerts", []) if abs(a[2]) > 0.70]
    if high_corr: issues.append(f"Componentes corr >0.70: {', '.join(f'{a[0]}x{a[1]}' for a in high_corr)}")
    useless = [k for k, v in corr.get("info_gain", {}).items() if not v.get("useful")]
    if useless: issues.append(f"Componentes sem info gain: {', '.join(useless)}")
    else: goods.append("Todos os 5 componentes adicionam informacao")
    be = exe.get("breakeven_slippage")
    if be and be < 0.0005: issues.append(f"Breakeven {be*10000:.0f}bp -- PERIGOSO")
    elif be and be < 0.0010: issues.append(f"Breakeven {be*10000:.0f}bp -- fragil")
    else: goods.append(f"Breakeven {be*10000:.0f}bp -- robusto" if be else "Edge >50bp -- muito robusto")
    for g in goods: print(f"  + {g}")
    for i in issues: print(f"  - {i}")
    return {"calibration": cal, "correlation": corr, "ablation": abl, "execution": exe, "time": time_a}


if __name__ == "__main__":
    if len(sys.argv) < 2: print("Usage: python diagnostics.py <report.json>"); sys.exit(1)
    with open(Path(sys.argv[1])) as f: data = json.load(f)
    trades = data.get("trades", data if isinstance(data, list) else [])
    run_full_diagnostic(trades)
