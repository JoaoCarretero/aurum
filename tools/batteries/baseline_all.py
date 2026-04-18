"""
AURUM Baseline — Run all engines once and collect metrics.
"""
import sys, time, csv, logging
from pathlib import Path
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config import params as _p
from core.data import fetch_all, validate
from core.portfolio import detect_macro, build_corr_matrix

log = logging.getLogger("BASELINE")
log.setLevel(logging.INFO)
if not log.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-5s  %(message)s"))
    log.addHandler(_h)

for _name in ("CITADEL", "DE_SHAW", "BRIDGEWATER", "JUMP", "RENAISSANCE", "HTF_FILTER"):
    logging.getLogger(_name).setLevel(logging.WARNING)


def _metrics(all_trades):
    from analysis.stats import equity_stats, calc_ratios
    from analysis.montecarlo import monte_carlo
    from analysis.walkforward import walk_forward
    closed = [t for t in all_trades if t.get("result") in ("WIN", "LOSS")]
    if not closed:
        return {"n_trades": 0, "win_rate": 0, "pnl": 0, "sharpe": None,
                "sortino": None, "max_dd_pct": 0, "mc_pct_pos": 0}
    pnl_list = [t["pnl"] for t in closed]
    eq, mdd, mdd_pct, _ = equity_stats(pnl_list)
    ratios = calc_ratios(pnl_list, n_days=_p.SCAN_DAYS)
    wr = sum(1 for t in closed if t["result"] == "WIN") / len(closed) * 100
    mc = monte_carlo(pnl_list)
    return {
        "n_trades": len(closed), "win_rate": round(wr, 2),
        "pnl": round(sum(pnl_list), 2),
        "sharpe": round(ratios["sharpe"], 3) if ratios.get("sharpe") else None,
        "sortino": round(ratios["sortino"], 3) if ratios.get("sortino") else None,
        "max_dd_pct": round(mdd_pct, 2),
        "mc_pct_pos": mc.get("pct_pos", 0) if mc else 0,
    }


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--basket", type=str, default="default")
    args = ap.parse_args()

    _p.SCAN_DAYS = args.days
    _p.N_CANDLES = int(args.days * 24 * 4)
    if args.basket in _p.BASKETS:
        _p.SYMBOLS = _p.BASKETS[args.basket]

    log.info(f"Fetching {_p.INTERVAL} data ({args.days}d)...")
    fetch_syms = list(_p.SYMBOLS)
    if _p.MACRO_SYMBOL not in fetch_syms:
        fetch_syms.insert(0, _p.MACRO_SYMBOL)
    all_dfs = fetch_all(fetch_syms, _p.INTERVAL, _p.N_CANDLES)
    for sym, df in all_dfs.items(): validate(df, sym)
    macro = detect_macro(all_dfs)
    corr = build_corr_matrix(all_dfs)

    btc_status = "BULL/BEAR" if _p.MACRO_SYMBOL in all_dfs else "CHOP (missing)"
    log.info(f"BTC macro: {btc_status}")

    results = []

    # CITADEL
    log.info("Running CITADEL...")
    from engines.citadel import scan_symbol
    trades = []
    for sym in [s for s in _p.SYMBOLS if s in all_dfs]:
        t, _ = scan_symbol(all_dfs[sym].copy(), sym, macro, corr)
        trades.extend(t)
    trades.sort(key=lambda t: t["timestamp"])
    m = _metrics(trades)
    results.append({"engine": "CITADEL", "btc_macro": btc_status, **m})
    log.info(f"  CITADEL: {m['n_trades']}t Sharpe {m.get('sharpe','—')}")

    # NEWTON
    log.info("Running DE SHAW...")
    from engines.deshaw import find_cointegrated_pairs, scan_pair
    pairs = find_cointegrated_pairs(all_dfs)
    trades = []
    for pair in pairs:
        da, db = all_dfs.get(pair["sym_a"]), all_dfs.get(pair["sym_b"])
        if da is None or db is None: continue
        t, _ = scan_pair(da.copy(), db.copy(), pair["sym_a"], pair["sym_b"], pair, macro, corr)
        trades.extend(t)
    trades.sort(key=lambda t: t["timestamp"])
    m = _metrics(trades)
    results.append({"engine": "DE SHAW", "btc_macro": btc_status, **m})
    log.info(f"  DE SHAW: {m['n_trades']}t Sharpe {m.get('sharpe','—')}")

    # THOTH
    log.info("Running BRIDGEWATER...")
    from engines.bridgewater import collect_sentiment, scan_thoth
    sent = collect_sentiment([s for s in _p.SYMBOLS if s in all_dfs])
    trades = []
    for sym in [s for s in _p.SYMBOLS if s in all_dfs]:
        t, _ = scan_thoth(all_dfs[sym].copy(), sym, macro, corr, sentiment_data=sent)
        trades.extend(t)
    trades.sort(key=lambda t: t["timestamp"])
    m = _metrics(trades)
    results.append({"engine": "BRIDGEWATER", "btc_macro": btc_status, **m})
    log.info(f"  BRIDGEWATER: {m['n_trades']}t Sharpe {m.get('sharpe','—')}")

    # MERCURIO
    log.info("Running JUMP...")
    from engines.jump import scan_mercurio
    trades = []
    for sym in [s for s in _p.SYMBOLS if s in all_dfs]:
        t, _ = scan_mercurio(all_dfs[sym].copy(), sym, macro, corr)
        trades.extend(t)
    trades.sort(key=lambda t: t["timestamp"])
    m = _metrics(trades)
    results.append({"engine": "JUMP", "btc_macro": btc_status, **m})
    log.info(f"  JUMP: {m['n_trades']}t Sharpe {m.get('sharpe','—')}")

    # RENAISSANCE
    log.info("Running RENAISSANCE...")
    try:
        from core.harmonics import scan_hermes
        trades = []
        for sym in [s for s in _p.SYMBOLS if s in all_dfs]:
            t, _ = scan_hermes(all_dfs[sym].copy(), sym, macro, corr)
            trades.extend(t)
        trades.sort(key=lambda t: t["timestamp"])
        m = _metrics(trades)
        results.append({"engine": "RENAISSANCE", "btc_macro": btc_status, **m})
        log.info(f"  RENAISSANCE: {m['n_trades']}t Sharpe {m.get('sharpe','—')}")
    except Exception as e:
        log.warning(f"  RENAISSANCE failed: {e}")
        results.append({"engine": "RENAISSANCE", "btc_macro": btc_status,
                         "n_trades": 0, "error": str(e)})

    # Output
    print(f"\n{'═'*78}")
    print(f"  ALL-ENGINE BASELINE — {args.days}d {_p.INTERVAL} — BTC macro: {btc_status}")
    print(f"{'═'*78}")
    print(f"  {'Engine':<14s} {'BTC':<8s} {'Trades':>6s} {'WR':>6s} {'Sharpe':>8s} "
          f"{'PnL':>10s} {'MaxDD':>7s} {'MC%':>5s}")
    print(f"  {'─'*14} {'─'*8} {'─'*6} {'─'*6} {'─'*8} {'─'*10} {'─'*7} {'─'*5}")
    for r in results:
        s = f"{r.get('sharpe',0) or 0:.3f}" if r.get("sharpe") else "—"
        print(f"  {r['engine']:<14s} {r.get('btc_macro','?'):<8s} "
              f"{r.get('n_trades',0):>6d} {r.get('win_rate',0):>5.1f}% {s:>8s} "
              f"${r.get('pnl',0):>+9,.0f} {r.get('max_dd_pct',0):>6.1f}% "
              f"{r.get('mc_pct_pos',0):>4.0f}%")
    print(f"{'═'*78}")

    # CSV
    out = Path(f"data/param_search/{datetime.now().strftime('%Y-%m-%d')}/baseline_all.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    if results:
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
            w.writeheader()
            w.writerows(results)
    log.info(f"CSV → {out}")


if __name__ == "__main__":
    main()
