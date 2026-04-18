"""
AURUM Master Battery — All engines × all configs × all timeframes.
Fetches data once per (TF, basket, days) combo, runs all applicable engines.
"""
import sys, time, csv, json, logging, traceback
from pathlib import Path
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config import params as _p
from core.data import fetch_all, validate
from core.portfolio import detect_macro, build_corr_matrix
from tools.param_search import _patch_param

log = logging.getLogger("MASTER")
log.setLevel(logging.INFO)
if not log.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-5s  %(message)s"))
    log.addHandler(_h)

for n in ("CITADEL","DE_SHAW","BRIDGEWATER","JUMP","RENAISSANCE","HTF_FILTER","THOTH"):
    logging.getLogger(n).setLevel(logging.WARNING)

ALL = []
SEP = "═" * 80


def _m(trades, days=90):
    from analysis.stats import equity_stats, calc_ratios
    from analysis.montecarlo import monte_carlo
    from analysis.walkforward import walk_forward
    closed = [t for t in trades if t.get("result") in ("WIN","LOSS")]
    if not closed:
        return {"n_trades":0,"win_rate":0,"pnl":0,"sharpe":None,"sortino":None,
                "max_dd_pct":0,"mc_pct_pos":0,"wf_pct":0}
    pnl = [t["pnl"] for t in closed]
    eq, mdd, mdd_pct, _ = equity_stats(pnl)
    r = calc_ratios(pnl, n_days=days)
    wr = sum(1 for t in closed if t["result"]=="WIN")/len(closed)*100
    mc = monte_carlo(pnl)
    wf = walk_forward(closed)
    wf_ok = sum(1 for w in wf if abs(w["test"]["wr"]-w["train"]["wr"])<=15) if wf else 0
    return {
        "n_trades":len(closed),"win_rate":round(wr,2),"pnl":round(sum(pnl),2),
        "sharpe":round(r["sharpe"],3) if r.get("sharpe") else None,
        "sortino":round(r["sortino"],3) if r.get("sortino") else None,
        "max_dd_pct":round(mdd_pct,2),
        "mc_pct_pos":mc.get("pct_pos",0) if mc else 0,
        "wf_pct":round(wf_ok/len(wf)*100) if wf else 0,
    }


def _rec(engine, config, tf, days, basket, m):
    s = f"{m.get('sharpe',0) or 0:.3f}" if m.get("sharpe") else "—"
    ALL.append({"engine":engine,"config":config,"tf":tf,"days":days,"basket":basket,**m})
    log.info(f"  {engine:<14s} {config:<22s} {tf:<4s} {days:>3d}d {basket:<10s} "
             f"{m['n_trades']:>4d}t WR {m['win_rate']:>5.1f}% Sharpe {s:>7s} "
             f"${m['pnl']:>+8,.0f} DD {m['max_dd_pct']:>5.1f}% MC {m.get('mc_pct_pos',0):>3.0f}%")


def _fetch(basket_name, tf, days, extra=0):
    tf_mult = {"5m":12,"15m":4,"30m":2,"1h":1,"2h":0.5,"4h":0.25}
    nc = int(days * 24 * tf_mult.get(tf, 4)) + extra
    syms = list(_p.BASKETS.get(basket_name, _p.SYMBOLS))
    _patch_param("SYMBOLS", syms)
    _patch_param("INTERVAL", tf)
    _patch_param("SCAN_DAYS", days)
    _patch_param("N_CANDLES", nc)
    fetch_syms = list(syms)
    if _p.MACRO_SYMBOL not in fetch_syms:
        fetch_syms.insert(0, _p.MACRO_SYMBOL)
    dfs = fetch_all(fetch_syms, tf, nc)
    for s, d in dfs.items(): validate(d, s)
    macro = detect_macro(dfs)
    corr = build_corr_matrix(dfs)
    return dfs, macro, corr


def _checkpoint(engine):
    rows = [r for r in ALL if r["engine"]==engine]
    if not rows: return
    print(f"\n  {'─'*76}")
    print(f"  {engine} — {len(rows)} tests")
    print(f"  {'─'*76}")
    print(f"  {'Config':<22s} {'TF':<4s} {'D':>3s} {'Bsk':<10s} {'Tr':>5s} {'WR':>5s} "
          f"{'Sharpe':>7s} {'PnL':>9s} {'DD':>5s} {'MC':>4s} {'WF':>4s}")
    for r in rows:
        s = f"{r.get('sharpe',0) or 0:.3f}" if r.get("sharpe") else "—"
        print(f"  {r['config']:<22s} {r['tf']:<4s} {r['days']:>3d} {r['basket']:<10s} "
              f"{r['n_trades']:>5d} {r['win_rate']:>4.1f}% {s:>7s} "
              f"${r['pnl']:>+8,.0f} {r['max_dd_pct']:>4.1f}% "
              f"{r.get('mc_pct_pos',0):>3.0f}% {r.get('wf_pct',0):>3.0f}%")


# ═══════════════════════════════════════════════════════════
def run_citadel(dfs, macro, corr, days):
    from engines.citadel import scan_symbol
    trades = []
    for sym in [s for s in _p.SYMBOLS if s in dfs]:
        t, _ = scan_symbol(dfs[sym].copy(), sym, macro, corr)
        trades.extend(t)
    trades.sort(key=lambda t: t["timestamp"])
    return _m(trades, days)

def run_newton(dfs, macro, corr, days):
    from engines.deshaw import find_cointegrated_pairs, scan_pair
    pairs = find_cointegrated_pairs(dfs)
    trades = []
    for p in pairs:
        da, db = dfs.get(p["sym_a"]), dfs.get(p["sym_b"])
        if da is None or db is None: continue
        t, _ = scan_pair(da.copy(), db.copy(), p["sym_a"], p["sym_b"], p, macro, corr)
        trades.extend(t)
    trades.sort(key=lambda t: t["timestamp"])
    return _m(trades, days)

def run_thoth(dfs, macro, corr, days, sent):
    from engines.bridgewater import scan_thoth
    trades = []
    for sym in [s for s in _p.SYMBOLS if s in dfs]:
        t, _ = scan_thoth(dfs[sym].copy(), sym, macro, corr, sentiment_data=sent)
        trades.extend(t)
    trades.sort(key=lambda t: t["timestamp"])
    return _m(trades, days)

def run_mercurio(dfs, macro, corr, days):
    from engines.jump import scan_mercurio
    trades = []
    for sym in [s for s in _p.SYMBOLS if s in dfs]:
        t, _ = scan_mercurio(dfs[sym].copy(), sym, macro, corr)
        trades.extend(t)
    trades.sort(key=lambda t: t["timestamp"])
    return _m(trades, days)

def run_renaissance(dfs, macro, corr, days):
    from core.harmonics import scan_hermes
    trades = []
    for sym in [s for s in _p.SYMBOLS if s in dfs]:
        try:
            t, _ = scan_hermes(dfs[sym].copy(), sym, macro, corr)
            trades.extend(t)
        except Exception: pass
    trades.sort(key=lambda t: t["timestamp"])
    return _m(trades, days)


# ═══════════════════════════════════════════════════════════
def block1_bridgewater():
    log.info(f"\n{SEP}\n  BLOCK 1: BRIDGEWATER\n{SEP}")
    from engines.bridgewater import collect_sentiment

    for tf in ["15m", "1h", "4h"]:
        for days in [90, 180]:
            for bsk in ["default", "bluechip"]:
                try:
                    log.info(f"\n  BRIDGEWATER {tf} {days}d {bsk}")
                    dfs, macro, corr = _fetch(bsk, tf, days, extra=200)
                    log.info("    sentiment...")
                    sent = collect_sentiment([s for s in _p.SYMBOLS if s in dfs])
                    m = run_thoth(dfs, macro, corr, days, sent)
                    _rec("BRIDGEWATER", "default", tf, days, bsk, m)
                except Exception as e:
                    log.warning(f"    FAILED: {e}")
                    _rec("BRIDGEWATER", "default", tf, days, bsk,
                         {"n_trades":0,"win_rate":0,"pnl":0,"sharpe":None,
                          "max_dd_pct":0,"mc_pct_pos":0,"wf_pct":0})
    _checkpoint("BRIDGEWATER")


def block2_citadel():
    log.info(f"\n{SEP}\n  BLOCK 2: CITADEL\n{SEP}")

    configs = [
        ("baseline", {}),
        ("regime-adaptive", {"RISK_SCALE_BY_REGIME": {"BEAR":1.0,"BULL":0.30,"CHOP":0.50}}),
    ]

    for days in [90, 180]:
        for bsk in ["default", "bluechip"]:
            dfs, macro, corr = _fetch(bsk, "15m", days)
            for cfg_name, patches in configs:
                saved = {}
                for k, v in patches.items():
                    saved[k] = getattr(_p, k)
                    _patch_param(k, v)
                try:
                    log.info(f"\n  CITADEL {cfg_name} {days}d {bsk}")
                    m = run_citadel(dfs, macro, corr, days)
                    _rec("CITADEL", cfg_name, "15m", days, bsk, m)
                except Exception as e:
                    log.warning(f"    FAILED: {e}")
                for k, v in saved.items():
                    _patch_param(k, v)
    _checkpoint("CITADEL")


def block3_renaissance():
    log.info(f"\n{SEP}\n  BLOCK 3: RENAISSANCE\n{SEP}")

    for tf in ["15m", "1h", "4h"]:
        for days in [90, 180, 360]:
            try:
                log.info(f"\n  RENAISSANCE {tf} {days}d")
                dfs, macro, corr = _fetch("default", tf, days, extra=200)
                m = run_renaissance(dfs, macro, corr, days)
                _rec("RENAISSANCE", "default", tf, days, "default", m)
            except Exception as e:
                log.warning(f"    FAILED: {e}")
    _checkpoint("RENAISSANCE")


def block4_deshaw():
    log.info(f"\n{SEP}\n  BLOCK 4: DE SHAW\n{SEP}")

    for tf in ["1h", "4h"]:
        hl_scale = {"1h": 0.25, "4h": 0.0625}
        _patch_param("NEWTON_HALFLIFE_MAX", int(500 * hl_scale.get(tf, 1)))
        _patch_param("NEWTON_MAX_HOLD", max(6, int(96 * hl_scale.get(tf, 1))))

        for days in [90, 180]:
            for bsk in ["default", "bluechip"]:
                try:
                    log.info(f"\n  DE SHAW {tf} {days}d {bsk}")
                    dfs, macro, corr = _fetch(bsk, tf, days, extra=200)
                    m = run_newton(dfs, macro, corr, days)
                    _rec("DE SHAW", "default", tf, days, bsk, m)
                except Exception as e:
                    log.warning(f"    FAILED: {e}")

    _patch_param("NEWTON_HALFLIFE_MAX", 500)
    _patch_param("NEWTON_MAX_HOLD", 96)
    _checkpoint("DE SHAW")


def block5_jump():
    log.info(f"\n{SEP}\n  BLOCK 5: JUMP\n{SEP}")

    for tf in ["15m", "1h"]:
        for days in [90, 180]:
            for bsk in ["default", "majors"]:
                try:
                    log.info(f"\n  JUMP {tf} {days}d {bsk}")
                    dfs, macro, corr = _fetch(bsk, tf, days)
                    m = run_mercurio(dfs, macro, corr, days)
                    _rec("JUMP", "default", tf, days, bsk, m)
                except Exception as e:
                    log.warning(f"    FAILED: {e}")
    _checkpoint("JUMP")


def block6_millennium():
    log.info(f"\n{SEP}\n  BLOCK 6: MILLENNIUM — Status Check\n{SEP}")
    try:
        from engines.millennium import ensemble_reweight
        log.info("  ✓ ensemble_reweight importable")
        # Check if it can consume engine outputs
        import inspect
        sig = inspect.signature(ensemble_reweight)
        log.info(f"  Signature: {sig}")
        _rec("MILLENNIUM", "status-check", "—", 0, "—",
             {"n_trades":0,"win_rate":0,"pnl":0,"sharpe":None,
              "max_dd_pct":0,"mc_pct_pos":0,"wf_pct":0,
              "note": "importable, needs engine outputs"})
    except Exception as e:
        log.warning(f"  ✗ Import failed: {e}")
        _rec("MILLENNIUM", "import-fail", "—", 0, "—",
             {"n_trades":0,"win_rate":0,"pnl":0,"sharpe":None,
              "max_dd_pct":0,"mc_pct_pos":0,"wf_pct":0})
    _checkpoint("MILLENNIUM")


def block7_twosigma():
    log.info(f"\n{SEP}\n  BLOCK 7: TWO SIGMA — Status Check\n{SEP}")
    try:
        import engines.twosigma as prom
        log.info(f"  ✓ prometeu module importable")
        # Check for key functions
        funcs = [f for f in dir(prom) if not f.startswith("_") and callable(getattr(prom, f, None))]
        log.info(f"  Functions: {funcs[:10]}")
        has_scan = any("scan" in f.lower() or "train" in f.lower() or "predict" in f.lower() for f in funcs)
        log.info(f"  Has scan/train/predict: {has_scan}")
        _rec("TWO SIGMA", "status-check", "—", 0, "—",
             {"n_trades":0,"win_rate":0,"pnl":0,"sharpe":None,
              "max_dd_pct":0,"mc_pct_pos":0,"wf_pct":0})
    except Exception as e:
        log.warning(f"  ✗ Import failed: {e}")
        _rec("TWO SIGMA", "import-fail", "—", 0, "—",
             {"n_trades":0,"win_rate":0,"pnl":0,"sharpe":None,
              "max_dd_pct":0,"mc_pct_pos":0,"wf_pct":0})
    _checkpoint("TWO SIGMA")


def block8_aqr():
    log.info(f"\n{SEP}\n  BLOCK 8: AQR/DARWIN — Status Check\n{SEP}")
    try:
        import engines.aqr as dar
        log.info(f"  ✓ darwin module importable")
        funcs = [f for f in dir(dar) if not f.startswith("_") and callable(getattr(dar, f, None))]
        log.info(f"  Functions: {funcs[:10]}")
        _rec("AQR", "status-check", "—", 0, "—",
             {"n_trades":0,"win_rate":0,"pnl":0,"sharpe":None,
              "max_dd_pct":0,"mc_pct_pos":0,"wf_pct":0})
    except Exception as e:
        log.warning(f"  ✗ Import failed: {e}")
        _rec("AQR", "import-fail", "—", 0, "—",
             {"n_trades":0,"win_rate":0,"pnl":0,"sharpe":None,
              "max_dd_pct":0,"mc_pct_pos":0,"wf_pct":0})
    _checkpoint("AQR")


def final_report():
    print(f"\n{SEP}")
    print(f"  MASTER BATTERY — FULL RANKING BY SHARPE")
    print(f"{SEP}")
    valid = [r for r in ALL if r.get("sharpe") is not None and r["n_trades"]>0]
    valid.sort(key=lambda r: r["sharpe"], reverse=True)
    print(f"  {'#':>2s} {'Engine':<14s} {'Config':<22s} {'TF':<4s} {'D':>3s} {'Bsk':<10s} "
          f"{'Tr':>5s} {'WR':>5s} {'Sharpe':>7s} {'PnL':>9s} {'DD':>5s} {'MC':>4s} {'WF':>4s}")
    print(f"  {'─'*2} {'─'*14} {'─'*22} {'─'*4} {'─'*3} {'─'*10} "
          f"{'─'*5} {'─'*5} {'─'*7} {'─'*9} {'─'*5} {'─'*4} {'─'*4}")
    for i, r in enumerate(valid, 1):
        s = f"{r['sharpe']:.3f}"
        flag = ""
        if r["n_trades"]>=50 and r.get("mc_pct_pos",0)>=50 and r["sharpe"]>0: flag=" ✓"
        elif r["n_trades"]<30: flag=" ⛔"
        print(f"  {i:>2d} {r['engine']:<14s} {r['config']:<22s} {r['tf']:<4s} "
              f"{r['days']:>3d} {r['basket']:<10s} {r['n_trades']:>5d} "
              f"{r['win_rate']:>4.1f}% {s:>7s} ${r['pnl']:>+8,.0f} "
              f"{r['max_dd_pct']:>4.1f}% {r.get('mc_pct_pos',0):>3.0f}% "
              f"{r.get('wf_pct',0):>3.0f}%{flag}")
    print(f"{SEP}")

    # Non-strategy engines
    meta = [r for r in ALL if r["n_trades"]==0]
    if meta:
        print(f"\n  META/ORCHESTRATION STATUS")
        for r in meta:
            print(f"  {r['engine']:<14s} {r['config']:<22s} — {r.get('note','status check')}")

    out = Path(f"data/param_search/{datetime.now().strftime('%Y-%m-%d')}/master_battery.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    if ALL:
        keys = [k for k in ALL[0].keys() if k != "note"]
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            w.writeheader()
            w.writerows(ALL)
    log.info(f"CSV → {out}")


def main():
    t0 = time.time()
    try: block1_bridgewater()
    except Exception as e: log.error(f"BLOCK 1 FAILED: {e}\n{traceback.format_exc()}")
    try: block2_citadel()
    except Exception as e: log.error(f"BLOCK 2 FAILED: {e}\n{traceback.format_exc()}")
    try: block3_renaissance()
    except Exception as e: log.error(f"BLOCK 3 FAILED: {e}\n{traceback.format_exc()}")
    try: block4_deshaw()
    except Exception as e: log.error(f"BLOCK 4 FAILED: {e}\n{traceback.format_exc()}")
    try: block5_jump()
    except Exception as e: log.error(f"BLOCK 5 FAILED: {e}\n{traceback.format_exc()}")
    try: block6_millennium()
    except Exception as e: log.error(f"BLOCK 6 FAILED: {e}\n{traceback.format_exc()}")
    try: block7_twosigma()
    except Exception as e: log.error(f"BLOCK 7 FAILED: {e}\n{traceback.format_exc()}")
    try: block8_aqr()
    except Exception as e: log.error(f"BLOCK 8 FAILED: {e}\n{traceback.format_exc()}")

    # Restore defaults
    _patch_param("INTERVAL", "15m")
    _patch_param("SCAN_DAYS", 90)
    _patch_param("N_CANDLES", int(90*24*4))
    _patch_param("SYMBOLS", _p.BASKETS["default"])

    final_report()
    log.info(f"Total time: {time.time()-t0:.0f}s ({(time.time()-t0)/60:.1f} min)")


if __name__ == "__main__":
    main()
