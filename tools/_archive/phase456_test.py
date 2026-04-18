"""
AURUM Phase 4-6 Tests
- Phase 4: BRIDGEWATER contrarian HTF (baseline vs generic vs contrarian)
- Phase 5: DE SHAW timeframe test (15m vs 1h vs 4h)
- Phase 6: JUMP timeframe test (5m vs 15m vs 1h)
"""
import sys, time, logging
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config import params as _p
from core.data import fetch_all, validate
from core.portfolio import detect_macro, build_corr_matrix
from core.htf_filter import prepare_htf_context, htf_agrees, htf_contrarian
from tools.param_search import _patch_param

log = logging.getLogger("PHASE456")
log.setLevel(logging.INFO)
if not log.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-5s  %(message)s"))
    log.addHandler(_h)

for _name in ("CITADEL", "DE_SHAW", "BRIDGEWATER", "JUMP", "HTF_FILTER"):
    logging.getLogger(_name).setLevel(logging.WARNING)


def _metrics(trades):
    from analysis.stats import equity_stats, calc_ratios
    from analysis.montecarlo import monte_carlo
    closed = [t for t in trades if t.get("result") in ("WIN", "LOSS")]
    if not closed:
        return {"n_trades": 0, "win_rate": 0, "pnl": 0, "sharpe": None, "max_dd_pct": 0, "mc_pct_pos": 0}
    pnl_list = [t["pnl"] for t in closed]
    eq, mdd, mdd_pct, _ = equity_stats(pnl_list)
    ratios = calc_ratios(pnl_list, n_days=_p.SCAN_DAYS)
    wr = sum(1 for t in closed if t["result"] == "WIN") / len(closed) * 100
    mc = monte_carlo(pnl_list)
    return {
        "n_trades": len(closed), "win_rate": round(wr, 2),
        "pnl": round(sum(pnl_list), 2),
        "sharpe": round(ratios["sharpe"], 3) if ratios.get("sharpe") else None,
        "max_dd_pct": round(mdd_pct, 2),
        "mc_pct_pos": mc.get("pct_pos", 0) if mc else 0,
    }


def _fmt(m):
    s = f"{m.get('sharpe', 0) or 0:.3f}" if m.get('sharpe') else "—"
    return (f"{m['n_trades']}t  WR {m['win_rate']}%  Sharpe {s}  "
            f"PnL ${m['pnl']:+,.0f}  MaxDD {m['max_dd_pct']}%  MC {m.get('mc_pct_pos',0):.0f}%")


def phase4_bridgewater():
    """BRIDGEWATER: baseline vs generic HTF vs contrarian HTF."""
    log.info("\n" + "═"*60)
    log.info("  PHASE 4: BRIDGEWATER — Contrarian HTF")
    log.info("═"*60)

    _p.SCAN_DAYS = 90
    _p.N_CANDLES = int(90 * 24 * 4)

    log.info("Fetching 15m + 4h data...")
    fetch_syms = list(_p.SYMBOLS)
    if _p.MACRO_SYMBOL not in fetch_syms:
        fetch_syms.insert(0, _p.MACRO_SYMBOL)
    all_dfs = fetch_all(fetch_syms, "15m", _p.N_CANDLES)
    for s, d in all_dfs.items(): validate(d, s)
    macro = detect_macro(all_dfs)
    corr = build_corr_matrix(all_dfs)

    htf_dfs = fetch_all(fetch_syms, "4h", int(90*24*0.25)+200)
    for s, d in htf_dfs.items(): validate(d, s)
    htf_ctx = prepare_htf_context(all_dfs, htf_dfs)

    log.info("Fetching sentiment...")
    from engines.bridgewater import collect_sentiment, scan_thoth
    sent = collect_sentiment([s for s in _p.SYMBOLS if s in all_dfs])

    syms = [s for s in _p.SYMBOLS if s in all_dfs]

    # A: Baseline
    log.info("  [A] Baseline...")
    trades_a = []
    for sym in syms:
        t, _ = scan_thoth(all_dfs[sym].copy(), sym, macro, corr, sentiment_data=sent)
        trades_a.extend(t)
    trades_a.sort(key=lambda t: t["timestamp"])
    m_a = _metrics(trades_a)

    # B: Generic HTF (trend-following filter)
    log.info("  [B] Generic HTF (trend-following)...")
    trades_b = [t for t in trades_a if htf_agrees(htf_ctx, t["symbol"],
                t.get("entry_idx", t.get("idx", 0)), t.get("direction", ""))]
    m_b = _metrics(trades_b)

    # C: Contrarian HTF
    log.info("  [C] Contrarian HTF...")
    trades_c = [t for t in trades_a if htf_contrarian(htf_ctx, t["symbol"],
                t.get("entry_idx", t.get("idx", 0)), t.get("direction", ""))]
    m_c = _metrics(trades_c)

    log.info(f"  [A] baseline:    {_fmt(m_a)}")
    log.info(f"  [B] generic HTF: {_fmt(m_b)}")
    log.info(f"  [C] contrarian:  {_fmt(m_c)}")

    # Deltas
    for label, m in [("B vs A", m_b), ("C vs A", m_c)]:
        ds = ((m.get("sharpe") or 0) - (m_a.get("sharpe") or 0))
        dp = m["pnl"] - m_a["pnl"]
        improved = ds > 0
        log.info(f"  [{label}] ΔSharpe {ds:+.3f}  ΔPnL ${dp:+,.0f}  {'✓' if improved else '✗'}")

    return m_a, m_b, m_c


def phase5_deshaw():
    """DE SHAW: test on 15m, 1h, 4h."""
    log.info("\n" + "═"*60)
    log.info("  PHASE 5: DE SHAW — Timeframe Test")
    log.info("═"*60)

    from engines.deshaw import find_cointegrated_pairs, scan_pair

    results = {}
    for tf in ["15m", "1h", "4h"]:
        _p.SCAN_DAYS = 90
        tf_mult = {"15m": 4, "1h": 1, "4h": 0.25}
        n_candles = int(90 * 24 * tf_mult[tf])
        _patch_param("INTERVAL", tf)
        _patch_param("N_CANDLES", n_candles)

        # Scale half-life limits with timeframe
        hl_scale = {"15m": 1, "1h": 0.25, "4h": 0.0625}
        _patch_param("NEWTON_HALFLIFE_MAX", int(500 * hl_scale[tf]))
        _patch_param("NEWTON_MAX_HOLD", int(96 * hl_scale.get(tf, 1)))

        log.info(f"  [{tf}] Fetching data ({n_candles} candles)...")
        fetch_syms = list(_p.SYMBOLS)
        if _p.MACRO_SYMBOL not in fetch_syms:
            fetch_syms.insert(0, _p.MACRO_SYMBOL)
        all_dfs = fetch_all(fetch_syms, tf, n_candles)
        for s, d in all_dfs.items(): validate(d, s)
        macro = detect_macro(all_dfs)
        corr = build_corr_matrix(all_dfs)

        log.info(f"  [{tf}] Finding cointegrated pairs...")
        pairs = find_cointegrated_pairs(all_dfs)
        log.info(f"  [{tf}] {len(pairs)} pairs found")

        trades = []
        for pair in pairs:
            da, db = all_dfs.get(pair["sym_a"]), all_dfs.get(pair["sym_b"])
            if da is None or db is None: continue
            t, _ = scan_pair(da.copy(), db.copy(), pair["sym_a"], pair["sym_b"], pair, macro, corr)
            trades.extend(t)
        trades.sort(key=lambda t: t["timestamp"])
        m = _metrics(trades)
        results[tf] = m
        log.info(f"  [{tf}] {_fmt(m)}")

    # Restore
    _patch_param("INTERVAL", "15m")
    _patch_param("N_CANDLES", int(90 * 24 * 4))
    _patch_param("NEWTON_HALFLIFE_MAX", 500)
    _patch_param("NEWTON_MAX_HOLD", 96)

    return results


def phase6_jump():
    """JUMP: test on 5m, 15m, 1h."""
    log.info("\n" + "═"*60)
    log.info("  PHASE 6: JUMP — Timeframe Test")
    log.info("═"*60)

    from engines.jump import scan_mercurio

    results = {}
    for tf in ["5m", "15m", "1h"]:
        _p.SCAN_DAYS = 90
        tf_mult = {"5m": 12, "15m": 4, "1h": 1}
        n_candles = int(90 * 24 * tf_mult[tf])
        # Cap at 25920 (Binance limit for 5m)
        if n_candles > 25000:
            n_candles = 25000
        _patch_param("INTERVAL", tf)
        _patch_param("N_CANDLES", n_candles)

        log.info(f"  [{tf}] Fetching data ({n_candles} candles)...")
        fetch_syms = list(_p.SYMBOLS)
        if _p.MACRO_SYMBOL not in fetch_syms:
            fetch_syms.insert(0, _p.MACRO_SYMBOL)
        all_dfs = fetch_all(fetch_syms, tf, n_candles)
        for s, d in all_dfs.items(): validate(d, s)
        macro = detect_macro(all_dfs)
        corr = build_corr_matrix(all_dfs)

        trades = []
        for sym in [s for s in _p.SYMBOLS if s in all_dfs]:
            t, _ = scan_mercurio(all_dfs[sym].copy(), sym, macro, corr)
            trades.extend(t)
        trades.sort(key=lambda t: t["timestamp"])
        m = _metrics(trades)
        results[tf] = m
        log.info(f"  [{tf}] {_fmt(m)}")

    # Restore
    _patch_param("INTERVAL", "15m")
    _patch_param("N_CANDLES", int(90 * 24 * 4))

    return results


def main():
    t0 = time.time()

    r4 = phase4_bridgewater()
    r5 = phase5_deshaw()
    r6 = phase6_jump()

    # Final summary
    print(f"\n{'═'*72}")
    print(f"  PHASE 4-6 SUMMARY")
    print(f"{'═'*72}")

    print(f"\n  PHASE 4: BRIDGEWATER HTF variants")
    print(f"  {'Mode':<20s} {'Trades':>6s} {'WR':>6s} {'Sharpe':>8s} {'PnL':>10s} {'MaxDD':>7s}")
    for label, m in [("baseline", r4[0]), ("generic HTF", r4[1]), ("contrarian HTF", r4[2])]:
        s = f"{m.get('sharpe',0) or 0:.3f}" if m.get("sharpe") else "—"
        print(f"  {label:<20s} {m['n_trades']:>6d} {m['win_rate']:>5.1f}% {s:>8s} "
              f"${m['pnl']:>+9,.0f} {m['max_dd_pct']:>6.1f}%")

    print(f"\n  PHASE 5: DE SHAW timeframes")
    print(f"  {'TF':<6s} {'Trades':>6s} {'WR':>6s} {'Sharpe':>8s} {'PnL':>10s} {'MaxDD':>7s}")
    for tf, m in r5.items():
        s = f"{m.get('sharpe',0) or 0:.3f}" if m.get("sharpe") else "—"
        print(f"  {tf:<6s} {m['n_trades']:>6d} {m['win_rate']:>5.1f}% {s:>8s} "
              f"${m['pnl']:>+9,.0f} {m['max_dd_pct']:>6.1f}%")

    print(f"\n  PHASE 6: JUMP timeframes")
    print(f"  {'TF':<6s} {'Trades':>6s} {'WR':>6s} {'Sharpe':>8s} {'PnL':>10s} {'MaxDD':>7s}")
    for tf, m in r6.items():
        s = f"{m.get('sharpe',0) or 0:.3f}" if m.get("sharpe") else "—"
        print(f"  {tf:<6s} {m['n_trades']:>6d} {m['win_rate']:>5.1f}% {s:>8s} "
              f"${m['pnl']:>+9,.0f} {m['max_dd_pct']:>6.1f}%")

    print(f"\n{'═'*72}")
    log.info(f"Total time: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
