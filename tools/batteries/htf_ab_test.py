"""
AURUM HTF A/B Test — Compare all engines with and without HTF filter.

Runs each engine twice:
  A) Without HTF filter (baseline)
  B) With 4h HTF alignment filter

Reports side-by-side comparison.
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
from core.htf_filter import prepare_htf_context, htf_agrees

log = logging.getLogger("HTF_AB_TEST")
log.setLevel(logging.INFO)
if not log.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-5s  %(message)s"))
    log.addHandler(_h)

# Suppress noisy sub-loggers
for _name in ("CITADEL", "DE_SHAW", "BRIDGEWATER", "JUMP", "RENAISSANCE", "HTF_FILTER"):
    logging.getLogger(_name).setLevel(logging.WARNING)


def _metrics(all_trades: list) -> dict:
    from analysis.stats import equity_stats, calc_ratios
    from analysis.montecarlo import monte_carlo
    from analysis.walkforward import walk_forward

    closed = [t for t in all_trades if t.get("result") in ("WIN", "LOSS")]
    if not closed:
        return {"n_trades": 0, "win_rate": 0, "pnl": 0, "sharpe": None,
                "sortino": None, "max_dd_pct": 0, "mc_pct_pos": 0, "wf_stable_pct": 0}
    pnl_list = [t["pnl"] for t in closed]
    eq, mdd, mdd_pct, _ = equity_stats(pnl_list)
    ratios = calc_ratios(pnl_list, n_days=_p.SCAN_DAYS)
    wr = sum(1 for t in closed if t["result"] == "WIN") / len(closed) * 100
    mc = monte_carlo(pnl_list)
    wf = walk_forward(closed)
    wf_ok = sum(1 for w in wf if abs(w["test"]["wr"] - w["train"]["wr"]) <= 15) if wf else 0
    return {
        "n_trades": len(closed), "win_rate": round(wr, 2),
        "pnl": round(sum(pnl_list), 2),
        "sharpe": round(ratios["sharpe"], 4) if ratios.get("sharpe") else None,
        "sortino": round(ratios["sortino"], 4) if ratios.get("sortino") else None,
        "max_dd_pct": round(mdd_pct, 2),
        "mc_pct_pos": mc.get("pct_pos", 0) if mc else 0,
        "wf_stable_pct": round(wf_ok / len(wf) * 100) if wf else 0,
    }


# ═══════════════════════════════════════════════════════════
#  ENGINE RUNNERS (with optional HTF filter)
# ═══════════════════════════════════════════════════════════

def run_citadel(all_dfs, macro, corr, htf_ctx=None):
    from engines.citadel import scan_symbol
    all_trades = []
    for sym in [s for s in _p.SYMBOLS if s in all_dfs]:
        trades, _ = scan_symbol(all_dfs[sym].copy(), sym, macro, corr)
        if htf_ctx:
            trades = [t for t in trades if htf_agrees(htf_ctx, sym, t.get("entry_idx", 0), t.get("direction", ""))]
        all_trades.extend(trades)
    all_trades.sort(key=lambda t: t["timestamp"])
    return _metrics(all_trades)


def run_newton(all_dfs, macro, corr, htf_ctx=None):
    from engines.deshaw import find_cointegrated_pairs, scan_pair
    pairs = find_cointegrated_pairs(all_dfs)
    if len(pairs) < 1:
        return _metrics([])
    all_trades = []
    for pair in pairs:
        df_a, df_b = all_dfs.get(pair["sym_a"]), all_dfs.get(pair["sym_b"])
        if df_a is None or df_b is None:
            continue
        trades, _ = scan_pair(df_a.copy(), df_b.copy(),
                              pair["sym_a"], pair["sym_b"], pair, macro, corr)
        if htf_ctx:
            # For pairs: check HTF on the first leg (sym_a)
            trades = [t for t in trades if htf_agrees(htf_ctx, pair["sym_a"],
                      t.get("entry_idx", 0), t.get("direction", ""))]
        all_trades.extend(trades)
    all_trades.sort(key=lambda t: t["timestamp"])
    return _metrics(all_trades)


def run_thoth(all_dfs, macro, corr, htf_ctx=None, sentiment_data=None):
    from engines.bridgewater import scan_thoth
    all_trades = []
    for sym in [s for s in _p.SYMBOLS if s in all_dfs]:
        trades, _ = scan_thoth(all_dfs[sym].copy(), sym, macro, corr,
                               sentiment_data=sentiment_data)
        if htf_ctx:
            trades = [t for t in trades if htf_agrees(htf_ctx, sym,
                      t.get("entry_idx", t.get("idx", 0)), t.get("direction", ""))]
        all_trades.extend(trades)
    all_trades.sort(key=lambda t: t["timestamp"])
    return _metrics(all_trades)


def run_mercurio(all_dfs, macro, corr, htf_ctx=None):
    from engines.jump import scan_mercurio
    all_trades = []
    for sym in [s for s in _p.SYMBOLS if s in all_dfs]:
        trades, _ = scan_mercurio(all_dfs[sym].copy(), sym, macro, corr)
        if htf_ctx:
            trades = [t for t in trades if htf_agrees(htf_ctx, sym,
                      t.get("entry_idx", t.get("idx", 0)), t.get("direction", ""))]
        all_trades.extend(trades)
    all_trades.sort(key=lambda t: t["timestamp"])
    return _metrics(all_trades)


ENGINES = {
    "citadel": run_citadel,
    "newton": run_newton,
    "thoth": run_thoth,
    "mercurio": run_mercurio,
}


def main():
    import argparse
    ap = argparse.ArgumentParser(description="HTF A/B Test — all engines")
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--basket", type=str, default="default")
    ap.add_argument("--engines", type=str, default="citadel,newton,thoth,mercurio",
                    help="Comma-separated engine names")
    args = ap.parse_args()

    engines = [e.strip() for e in args.engines.split(",")]

    # Setup params
    _p.SCAN_DAYS = args.days
    _tf_mult = {"15m": 4, "1h": 1, "4h": 0.25}
    _p.N_CANDLES = int(args.days * 24 * _tf_mult.get(_p.INTERVAL, 4))
    if args.basket and args.basket in _p.BASKETS:
        _p.SYMBOLS = _p.BASKETS[args.basket]

    # ── Fetch LTF data ──
    log.info(f"Fetching {_p.INTERVAL} data ({args.days}d, basket={args.basket})...")
    fetch_syms = list(_p.SYMBOLS)
    if _p.MACRO_SYMBOL not in fetch_syms:
        fetch_syms.insert(0, _p.MACRO_SYMBOL)
    all_dfs = fetch_all(fetch_syms, _p.INTERVAL, _p.N_CANDLES)
    for sym, df in all_dfs.items():
        validate(df, sym)

    macro = detect_macro(all_dfs)
    corr = build_corr_matrix(all_dfs)

    # ── Fetch HTF data (4h) ──
    log.info("Fetching 4h HTF data...")
    htf_n_candles = int(args.days * 24 * 0.25) + 200  # extra for warmup
    htf_dfs = fetch_all(fetch_syms, "4h", htf_n_candles)
    for sym, df in htf_dfs.items():
        validate(df, sym)

    log.info("Preparing HTF context...")
    htf_ctx = prepare_htf_context(all_dfs, htf_dfs)
    htf_ready = sum(1 for v in htf_ctx.values() if v is not None)
    log.info(f"HTF context ready: {htf_ready}/{len(htf_ctx)} symbols")

    # ── Fetch sentiment (for Thoth) ──
    sentiment_data = None
    if "thoth" in engines:
        log.info("Fetching sentiment data...")
        from engines.bridgewater import collect_sentiment
        sentiment_data = collect_sentiment([s for s in _p.SYMBOLS if s in all_dfs])

    # ── Run A/B for each engine ──
    results = []
    SEP = "─" * 72

    for engine in engines:
        runner = ENGINES.get(engine)
        if not runner:
            log.warning(f"Unknown engine: {engine}")
            continue

        log.info(f"\n{SEP}\n  {engine.upper()} — A/B Test\n{SEP}")

        # A: Without HTF
        log.info(f"  [A] {engine} — no HTF filter...")
        t0 = time.time()
        if engine == "thoth":
            m_a = runner(all_dfs, macro, corr, htf_ctx=None, sentiment_data=sentiment_data)
        else:
            m_a = runner(all_dfs, macro, corr, htf_ctx=None)
        t_a = round(time.time() - t0, 1)

        # B: With HTF
        log.info(f"  [B] {engine} — with 4h HTF filter...")
        t0 = time.time()
        if engine == "thoth":
            m_b = runner(all_dfs, macro, corr, htf_ctx=htf_ctx, sentiment_data=sentiment_data)
        else:
            m_b = runner(all_dfs, macro, corr, htf_ctx=htf_ctx)
        t_b = round(time.time() - t0, 1)

        # Compare
        results.append({"engine": engine, "mode": "baseline", **m_a, "elapsed_s": t_a})
        results.append({"engine": engine, "mode": "htf_4h", **m_b, "elapsed_s": t_b})

        def _fmt(m):
            s = f"{m.get('sharpe', 0) or 0:.3f}" if m.get("sharpe") else "—"
            return (f"{m['n_trades']}t  WR {m['win_rate']}%  Sharpe {s}  "
                    f"PnL ${m['pnl']:+,.0f}  MaxDD {m['max_dd_pct']}%  "
                    f"MC {m.get('mc_pct_pos', 0):.0f}%")

        log.info(f"  [A] baseline:  {_fmt(m_a)}")
        log.info(f"  [B] htf_4h:    {_fmt(m_b)}")

        # Delta
        d_trades = m_b["n_trades"] - m_a["n_trades"]
        d_sharpe = ((m_b.get("sharpe") or 0) - (m_a.get("sharpe") or 0))
        d_pnl = m_b["pnl"] - m_a["pnl"]
        d_dd = m_b["max_dd_pct"] - m_a["max_dd_pct"]
        improved = d_sharpe > 0
        log.info(f"  [Δ] trades {d_trades:+d}  Sharpe {d_sharpe:+.3f}  "
                 f"PnL ${d_pnl:+,.0f}  MaxDD {d_dd:+.1f}pp  "
                 f"{'✓ IMPROVED' if improved else '✗ WORSE'}")

    # ── Save CSV ──
    date_str = datetime.now().strftime("%Y-%m-%d")
    out_dir = Path(f"data/param_search/{date_str}")
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "htf_ab_test.csv"
    if results:
        keys = list(results[0].keys())
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(results)
        log.info(f"\nCSV → {csv_path}")

    # ── Summary Table ──
    print(f"\n{'═'*72}")
    print(f"  HTF A/B TEST SUMMARY — {args.days}d {_p.INTERVAL} + 4h filter")
    print(f"{'═'*72}")
    print(f"  {'Engine':<12s} {'Mode':<10s} {'Trades':>6s} {'WR':>6s} {'Sharpe':>8s} "
          f"{'PnL':>10s} {'MaxDD':>7s} {'MC%':>5s}")
    print(f"  {'─'*12} {'─'*10} {'─'*6} {'─'*6} {'─'*8} {'─'*10} {'─'*7} {'─'*5}")
    for r in results:
        s = f"{r.get('sharpe', 0) or 0:.3f}" if r.get("sharpe") else "—"
        print(f"  {r['engine']:<12s} {r['mode']:<10s} {r['n_trades']:>6d} "
              f"{r['win_rate']:>5.1f}% {s:>8s} ${r['pnl']:>+9,.0f} "
              f"{r['max_dd_pct']:>6.1f}% {r.get('mc_pct_pos', 0):>4.0f}%")
    print(f"{'═'*72}")

    log.info("Done.")


if __name__ == "__main__":
    main()
