"""
AURUM Full Battery Test — All engines, all configurations.
Runs tests sequentially, reports after each block.
"""
import sys, time, csv, json, logging
from pathlib import Path
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config import params as _p
from core.data import fetch_all, validate
from core.risk.portfolio import detect_macro, build_corr_matrix
from tools.param_search import _patch_param

log = logging.getLogger("BATTERY")
log.setLevel(logging.INFO)
if not log.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-5s  %(message)s"))
    log.addHandler(_h)

for n in ("CITADEL","DE_SHAW","BRIDGEWATER","JUMP","RENAISSANCE","HTF_FILTER","THOTH"):
    logging.getLogger(n).setLevel(logging.WARNING)

ALL_RESULTS = []
SEP = "═" * 78


def _metrics(trades, days=90):
    from analysis.stats import equity_stats, calc_ratios
    from analysis.montecarlo import monte_carlo
    closed = [t for t in trades if t.get("result") in ("WIN", "LOSS")]
    if not closed:
        return {"n_trades": 0, "win_rate": 0, "pnl": 0, "sharpe": None,
                "sortino": None, "max_dd_pct": 0, "mc_pct_pos": 0}
    pnl = [t["pnl"] for t in closed]
    eq, mdd, mdd_pct, _ = equity_stats(pnl)
    r = calc_ratios(pnl, n_days=days)
    wr = sum(1 for t in closed if t["result"] == "WIN") / len(closed) * 100
    mc = monte_carlo(pnl)
    return {
        "n_trades": len(closed), "win_rate": round(wr, 2),
        "pnl": round(sum(pnl), 2),
        "sharpe": round(r["sharpe"], 3) if r.get("sharpe") else None,
        "sortino": round(r["sortino"], 3) if r.get("sortino") else None,
        "max_dd_pct": round(mdd_pct, 2),
        "mc_pct_pos": mc.get("pct_pos", 0) if mc else 0,
    }


def _record(engine, config, tf, days, m):
    s = f"{m.get('sharpe',0) or 0:.3f}" if m.get("sharpe") else "—"
    ALL_RESULTS.append({
        "engine": engine, "config": config, "tf": tf, "days": days, **m
    })
    log.info(f"  → {m['n_trades']}t  WR {m['win_rate']}%  Sharpe {s}  "
             f"PnL ${m['pnl']:+,.0f}  MaxDD {m['max_dd_pct']}%  MC {m.get('mc_pct_pos',0):.0f}%")


def _fetch(syms, tf, days, extra_warmup=0):
    tf_mult = {"5m": 12, "15m": 4, "30m": 2, "1h": 1, "4h": 0.25}
    nc = int(days * 24 * tf_mult.get(tf, 4)) + extra_warmup
    fetch_syms = list(syms)
    if _p.MACRO_SYMBOL not in fetch_syms:
        fetch_syms.insert(0, _p.MACRO_SYMBOL)
    dfs = fetch_all(fetch_syms, tf, nc)
    for s, d in dfs.items(): validate(d, s)
    return dfs


def _setup(tf, days):
    tf_mult = {"5m": 12, "15m": 4, "30m": 2, "1h": 1, "4h": 0.25}
    _patch_param("INTERVAL", tf)
    _patch_param("SCAN_DAYS", days)
    _patch_param("N_CANDLES", int(days * 24 * tf_mult.get(tf, 4)))


def _restore():
    _patch_param("INTERVAL", "15m")
    _patch_param("SCAN_DAYS", 90)
    _patch_param("N_CANDLES", int(90 * 24 * 4))


# ═══════════════════════════════════════════════════════════
#  CITADEL TESTS
# ═══════════════════════════════════════════════════════════

def test_citadel():
    from engines.citadel import scan_symbol

    def _run_citadel(dfs, macro, corr, days):
        trades = []
        for sym in [s for s in _p.SYMBOLS if s in dfs]:
            t, _ = scan_symbol(dfs[sym].copy(), sym, macro, corr)
            trades.extend(t)
        trades.sort(key=lambda t: t["timestamp"])
        return _metrics(trades, days)

    log.info(f"\n{SEP}\n  CITADEL TESTS\n{SEP}")

    # A. Regime-adaptive sizing 180d
    log.info("\n  [1] Regime-adaptive sizing 180d")
    _setup("15m", 180)
    saved_scale = dict(_p.RISK_SCALE_BY_REGIME)
    _patch_param("RISK_SCALE_BY_REGIME", {"BEAR": 1.0, "BULL": 0.30, "CHOP": 0.50})
    dfs = _fetch(_p.SYMBOLS, "15m", 180)
    macro = detect_macro(dfs); corr = build_corr_matrix(dfs)
    m = _run_citadel(dfs, macro, corr, 180)
    _record("CITADEL", "regime-adaptive", "15m", 180, m)
    _patch_param("RISK_SCALE_BY_REGIME", saved_scale)

    # B. Basket bluechip 90d
    log.info("\n  [2] Basket bluechip 90d")
    _setup("15m", 90)
    saved_syms = list(_p.SYMBOLS)
    _patch_param("SYMBOLS", _p.BASKETS["bluechip"])
    dfs = _fetch(_p.SYMBOLS, "15m", 90)
    macro = detect_macro(dfs); corr = build_corr_matrix(dfs)
    m = _run_citadel(dfs, macro, corr, 90)
    _record("CITADEL", "bluechip", "15m", 90, m)

    # B2. Basket bluechip 180d
    log.info("\n  [3] Basket bluechip 180d")
    _setup("15m", 180)
    dfs = _fetch(_p.SYMBOLS, "15m", 180)
    macro = detect_macro(dfs); corr = build_corr_matrix(dfs)
    m = _run_citadel(dfs, macro, corr, 180)
    _record("CITADEL", "bluechip", "15m", 180, m)
    _patch_param("SYMBOLS", saved_syms)

    # C. Omega 3D with threshold 0.48
    log.info("\n  [4] Omega 3D + threshold 0.48 (90d)")
    _setup("15m", 90)
    saved_weights = dict(_p.OMEGA_WEIGHTS)
    saved_thresh = _p.SCORE_THRESHOLD
    saved_stop = _p.STOP_ATR_M
    saved_regime = dict(_p.SCORE_BY_REGIME)
    _patch_param("OMEGA_WEIGHTS", {"struct": 0.40, "flow": 0.00, "cascade": 0.30, "momentum": 0.30, "pullback": 0.00})
    _patch_param("SCORE_THRESHOLD", 0.48)
    _patch_param("STOP_ATR_M", 2.1)
    _patch_param("SCORE_BY_REGIME", {"BEAR": 0.48, "BULL": 0.50, "CHOP": 0.56})
    # Also patch penalty to active-only
    import core.signals as _sig
    _orig_penalty_line = None  # We'll work around this by patching OMEGA_WEIGHTS
    dfs = _fetch(_p.SYMBOLS, "15m", 90)
    macro = detect_macro(dfs); corr = build_corr_matrix(dfs)
    m = _run_citadel(dfs, macro, corr, 90)
    _record("CITADEL", "omega3D-0.48", "15m", 90, m)

    # C2. Omega 3D 180d
    log.info("\n  [5] Omega 3D + threshold 0.48 (180d)")
    _setup("15m", 180)
    dfs = _fetch(_p.SYMBOLS, "15m", 180)
    macro = detect_macro(dfs); corr = build_corr_matrix(dfs)
    m = _run_citadel(dfs, macro, corr, 180)
    _record("CITADEL", "omega3D-0.48", "15m", 180, m)

    _patch_param("OMEGA_WEIGHTS", saved_weights)
    _patch_param("SCORE_THRESHOLD", saved_thresh)
    _patch_param("STOP_ATR_M", saved_stop)
    _patch_param("SCORE_BY_REGIME", saved_regime)
    _restore()

    _checkpoint("CITADEL")


# ═══════════════════════════════════════════════════════════
#  DE SHAW TESTS
# ═══════════════════════════════════════════════════════════

def test_deshaw():
    from engines.deshaw import find_cointegrated_pairs, scan_pair

    def _run_newton(dfs, macro, corr, days):
        pairs = find_cointegrated_pairs(dfs)
        log.info(f"    {len(pairs)} pairs found")
        trades = []
        for p in pairs:
            da, db = dfs.get(p["sym_a"]), dfs.get(p["sym_b"])
            if da is None or db is None: continue
            t, _ = scan_pair(da.copy(), db.copy(), p["sym_a"], p["sym_b"], p, macro, corr)
            trades.extend(t)
        trades.sort(key=lambda t: t["timestamp"])
        return _metrics(trades, days)

    log.info(f"\n{SEP}\n  DE SHAW TESTS\n{SEP}")

    # A. 4h grid stop calibration
    log.info("\n  [6] 4h stop/entry grid (12 combos)")
    _setup("4h", 90)
    hl_4h = int(500 * 0.0625)
    _patch_param("NEWTON_HALFLIFE_MAX", hl_4h)
    _patch_param("NEWTON_MAX_HOLD", int(96 * 0.0625))
    dfs = _fetch(_p.SYMBOLS, "4h", 90, extra_warmup=200)
    macro = detect_macro(dfs); corr = build_corr_matrix(dfs)

    best_sharpe = -999
    best_config = ""
    for stop in [2.0, 2.5, 3.0, 3.5]:
        for entry in [1.5, 2.0, 2.5]:
            _patch_param("NEWTON_ZSCORE_STOP", stop)
            _patch_param("NEWTON_ZSCORE_ENTRY", entry)
            m = _run_newton(dfs, macro, corr, 90)
            cfg = f"stop={stop} entry={entry}"
            _record("DE SHAW", cfg, "4h", 90, m)
            s = m.get("sharpe") or -999
            if s > best_sharpe:
                best_sharpe = s
                best_config = cfg
    log.info(f"  Best 4h config: {best_config} → Sharpe {best_sharpe:.3f}")
    _patch_param("NEWTON_ZSCORE_STOP", 3.5)
    _patch_param("NEWTON_ZSCORE_ENTRY", 2.0)

    # B. Basket bluechip 4h
    log.info("\n  [7] Basket bluechip 4h")
    saved_syms = list(_p.SYMBOLS)
    _patch_param("SYMBOLS", _p.BASKETS["bluechip"])
    dfs = _fetch(_p.SYMBOLS, "4h", 90, extra_warmup=200)
    macro = detect_macro(dfs); corr = build_corr_matrix(dfs)
    m = _run_newton(dfs, macro, corr, 90)
    _record("DE SHAW", "bluechip", "4h", 90, m)
    _patch_param("SYMBOLS", saved_syms)

    _patch_param("NEWTON_HALFLIFE_MAX", 500)
    _patch_param("NEWTON_MAX_HOLD", 96)
    _restore()

    _checkpoint("DE SHAW")


# ═══════════════════════════════════════════════════════════
#  BRIDGEWATER TESTS
# ═══════════════════════════════════════════════════════════

def test_bridgewater():
    from engines.bridgewater import collect_sentiment, scan_thoth

    def _run_thoth(dfs, macro, corr, days, sent):
        trades = []
        for sym in [s for s in _p.SYMBOLS if s in dfs]:
            t, _ = scan_thoth(dfs[sym].copy(), sym, macro, corr, sentiment_data=sent)
            trades.extend(t)
        trades.sort(key=lambda t: t["timestamp"])
        return _metrics(trades, days)

    log.info(f"\n{SEP}\n  BRIDGEWATER TESTS\n{SEP}")

    # A. Timeframe 1h
    log.info("\n  [8] Timeframe 1h")
    _setup("1h", 90)
    dfs = _fetch(_p.SYMBOLS, "1h", 90)
    macro = detect_macro(dfs); corr = build_corr_matrix(dfs)
    log.info("    Fetching sentiment...")
    sent = collect_sentiment([s for s in _p.SYMBOLS if s in dfs])
    m = _run_thoth(dfs, macro, corr, 90, sent)
    _record("BRIDGEWATER", "default", "1h", 90, m)

    # A2. Timeframe 4h
    log.info("\n  [9] Timeframe 4h")
    _setup("4h", 90)
    dfs = _fetch(_p.SYMBOLS, "4h", 90, extra_warmup=200)
    macro = detect_macro(dfs); corr = build_corr_matrix(dfs)
    m = _run_thoth(dfs, macro, corr, 90, sent)  # reuse sentiment
    _record("BRIDGEWATER", "default", "4h", 90, m)

    # B. Macro veto contrarian
    log.info("\n  [10] Macro veto contrarian (15m)")
    _setup("15m", 90)
    dfs = _fetch(_p.SYMBOLS, "15m", 90)
    macro = detect_macro(dfs); corr = build_corr_matrix(dfs)
    # Run baseline then filter: only allow contrarian direction vs macro
    trades_all = []
    for sym in [s for s in _p.SYMBOLS if s in dfs]:
        t, _ = scan_thoth(dfs[sym].copy(), sym, macro, corr, sentiment_data=sent)
        trades_all.extend(t)
    # Filter: BEAR -> only BULLISH, BULL -> only BEARISH, CHOP -> pass
    trades_contra = []
    for t in trades_all:
        mb = t.get("macro_bias", "CHOP")
        d = t.get("direction", "")
        if mb == "BEAR" and d == "BULLISH": trades_contra.append(t)
        elif mb == "BULL" and d == "BEARISH": trades_contra.append(t)
        elif mb == "CHOP": trades_contra.append(t)
    trades_contra.sort(key=lambda t: t["timestamp"])
    m = _metrics(trades_contra, 90)
    _record("BRIDGEWATER", "macro-contrarian", "15m", 90, m)

    _restore()
    _checkpoint("BRIDGEWATER")


# ═══════════════════════════════════════════════════════════
#  RENAISSANCE TESTS
# ═══════════════════════════════════════════════════════════

def test_renaissance():
    log.info(f"\n{SEP}\n  RENAISSANCE TESTS\n{SEP}")

    try:
        from core.harmonics import scan_hermes
    except Exception as e:
        log.warning(f"  RENAISSANCE import failed: {e}")
        _record("RENAISSANCE", "import-fail", "15m", 0,
                {"n_trades": 0, "win_rate": 0, "pnl": 0, "sharpe": None,
                 "max_dd_pct": 0, "mc_pct_pos": 0})
        return

    def _run_ren(dfs, macro, corr, days):
        trades = []
        for sym in [s for s in _p.SYMBOLS if s in dfs]:
            try:
                t, _ = scan_hermes(dfs[sym].copy(), sym, macro, corr)
                trades.extend(t)
            except Exception:
                pass
        trades.sort(key=lambda t: t["timestamp"])
        return _metrics(trades, days)

    # A. 180d
    log.info("\n  [11] 180d")
    _setup("15m", 180)
    dfs = _fetch(_p.SYMBOLS, "15m", 180)
    macro = detect_macro(dfs); corr = build_corr_matrix(dfs)
    m = _run_ren(dfs, macro, corr, 180)
    _record("RENAISSANCE", "default", "15m", 180, m)

    # B. 1h
    log.info("\n  [12] 1h 90d")
    _setup("1h", 90)
    dfs = _fetch(_p.SYMBOLS, "1h", 90)
    macro = detect_macro(dfs); corr = build_corr_matrix(dfs)
    m = _run_ren(dfs, macro, corr, 90)
    _record("RENAISSANCE", "default", "1h", 90, m)

    # C. 4h
    log.info("\n  [13] 4h 90d")
    _setup("4h", 90)
    dfs = _fetch(_p.SYMBOLS, "4h", 90, extra_warmup=200)
    macro = detect_macro(dfs); corr = build_corr_matrix(dfs)
    m = _run_ren(dfs, macro, corr, 90)
    _record("RENAISSANCE", "default", "4h", 90, m)

    _restore()
    _checkpoint("RENAISSANCE")


# ═══════════════════════════════════════════════════════════
#  JUMP TESTS
# ═══════════════════════════════════════════════════════════

def test_jump():
    from engines.jump import scan_mercurio

    def _run_jump(dfs, macro, corr, days):
        trades = []
        for sym in [s for s in _p.SYMBOLS if s in dfs]:
            t, _ = scan_mercurio(dfs[sym].copy(), sym, macro, corr)
            trades.extend(t)
        trades.sort(key=lambda t: t["timestamp"])
        return _metrics(trades, days)

    log.info(f"\n{SEP}\n  JUMP TESTS\n{SEP}")

    # A. 1h with bluechip basket
    log.info("\n  [14] 1h bluechip")
    _setup("1h", 90)
    saved_syms = list(_p.SYMBOLS)
    _patch_param("SYMBOLS", _p.BASKETS.get("majors", _p.BASKETS.get("bluechip", saved_syms)))
    dfs = _fetch(_p.SYMBOLS, "1h", 90)
    macro = detect_macro(dfs); corr = build_corr_matrix(dfs)
    m = _run_jump(dfs, macro, corr, 90)
    _record("JUMP", "majors", "1h", 90, m)
    _patch_param("SYMBOLS", saved_syms)

    # B. 15m with majors
    log.info("\n  [15] 15m majors")
    _setup("15m", 90)
    _patch_param("SYMBOLS", _p.BASKETS.get("majors", saved_syms))
    dfs = _fetch(_p.SYMBOLS, "15m", 90)
    macro = detect_macro(dfs); corr = build_corr_matrix(dfs)
    m = _run_jump(dfs, macro, corr, 90)
    _record("JUMP", "majors", "15m", 90, m)
    _patch_param("SYMBOLS", saved_syms)

    _restore()
    _checkpoint("JUMP")


# ═══════════════════════════════════════════════════════════
#  CHECKPOINT & SUMMARY
# ═══════════════════════════════════════════════════════════

def _checkpoint(engine):
    eng_results = [r for r in ALL_RESULTS if r["engine"] == engine]
    if not eng_results: return
    print(f"\n  {'─'*72}")
    print(f"  {engine} checkpoint ({len(eng_results)} tests)")
    print(f"  {'─'*72}")
    print(f"  {'Config':<22s} {'TF':<5s} {'Days':>4s} {'Trades':>6s} {'WR':>6s} "
          f"{'Sharpe':>8s} {'PnL':>10s} {'MaxDD':>7s} {'MC%':>5s}")
    for r in eng_results:
        s = f"{r.get('sharpe',0) or 0:.3f}" if r.get("sharpe") else "—"
        print(f"  {r['config']:<22s} {r['tf']:<5s} {r['days']:>4d} "
              f"{r['n_trades']:>6d} {r['win_rate']:>5.1f}% {s:>8s} "
              f"${r['pnl']:>+9,.0f} {r['max_dd_pct']:>6.1f}% "
              f"{r.get('mc_pct_pos',0):>4.0f}%")


def final_summary():
    print(f"\n{SEP}")
    print(f"  FULL BATTERY RESULTS — RANKED BY SHARPE")
    print(f"{SEP}")
    valid = [r for r in ALL_RESULTS if r.get("sharpe") is not None and r["n_trades"] > 0]
    valid.sort(key=lambda r: r["sharpe"], reverse=True)
    print(f"  {'#':>3s} {'Engine':<14s} {'Config':<22s} {'TF':<5s} {'Days':>4s} "
          f"{'Trades':>6s} {'WR':>6s} {'Sharpe':>8s} {'PnL':>10s} {'MaxDD':>7s} {'MC%':>5s}")
    print(f"  {'─'*3} {'─'*14} {'─'*22} {'─'*5} {'─'*4} {'─'*6} {'─'*6} {'─'*8} {'─'*10} {'─'*7} {'─'*5}")
    for i, r in enumerate(valid, 1):
        s = f"{r['sharpe']:.3f}"
        flag = ""
        if r["n_trades"] >= 50 and r.get("mc_pct_pos", 0) >= 50 and r["sharpe"] > 0:
            flag = " ✓"
        elif r["n_trades"] < 30:
            flag = " ⛔"
        print(f"  {i:>3d} {r['engine']:<14s} {r['config']:<22s} {r['tf']:<5s} {r['days']:>4d} "
              f"{r['n_trades']:>6d} {r['win_rate']:>5.1f}% {s:>8s} "
              f"${r['pnl']:>+9,.0f} {r['max_dd_pct']:>6.1f}% "
              f"{r.get('mc_pct_pos',0):>4.0f}%{flag}")
    print(f"{SEP}")

    # Save CSV
    date_str = datetime.now().strftime("%Y-%m-%d")
    out = Path(f"data/param_search/{date_str}/battery_full.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    if ALL_RESULTS:
        keys = list(ALL_RESULTS[0].keys())
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(ALL_RESULTS)
    log.info(f"CSV → {out}")


def main():
    t0 = time.time()
    test_citadel()
    test_deshaw()
    test_bridgewater()
    test_renaissance()
    test_jump()
    final_summary()
    log.info(f"Total time: {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
