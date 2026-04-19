"""
AURUM Param Search — grid search via monkey-patch (no file edits)
================================================================
Usage:
  python tools/batteries/param_search.py --engine newton \
    --param NEWTON_ZSCORE_STOP:2.0:3.5:0.5 \
    --param NEWTON_ZSCORE_ENTRY:1.5:2.5:0.5 \
    --days 90 --basket default

Params are patched at runtime via setattr(config.params, ...) and
restored after each run. config/params.py is NEVER written to disk.
"""
import sys, os, time, csv, json, logging, itertools
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config import params as _p
from core.data import fetch_all, validate
from core.risk.portfolio import detect_macro, build_corr_matrix

log = logging.getLogger("PARAM_SEARCH")
log.setLevel(logging.INFO)
if not log.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-5s  %(message)s"))
    log.addHandler(_h)

# Suppress noisy sub-loggers during grid
for _name in ("CITADEL", "DE_SHAW", "BRIDGEWATER", "JUMP", "RENAISSANCE"):
    logging.getLogger(_name).setLevel(logging.WARNING)


# ═══════════════════════════════════════════════════════════
#  PARAM GRID
# ═══════════════════════════════════════════════════════════

def parse_param_spec(spec: str) -> tuple[str, list[float]]:
    """Parse 'NAME:MIN:MAX:STEP' → (name, [values])."""
    parts = spec.split(":")
    name = parts[0]
    if len(parts) == 4:
        lo, hi, step = float(parts[1]), float(parts[2]), float(parts[3])
        vals = []
        v = lo
        while v <= hi + 1e-9:
            vals.append(round(v, 6))
            v += step
        return name, vals
    elif len(parts) >= 2:
        return name, [float(x) for x in parts[1:]]
    raise ValueError(f"Invalid param spec: {spec}")


def build_grid(param_specs: list[str]) -> tuple[list[str], list[dict]]:
    """Build cartesian product of all param specs."""
    names, value_lists = [], []
    for spec in param_specs:
        name, vals = parse_param_spec(spec)
        names.append(name)
        value_lists.append(vals)
    combos = list(itertools.product(*value_lists))
    grid = [dict(zip(names, combo)) for combo in combos]
    return names, grid


# ═══════════════════════════════════════════════════════════
#  ENGINE RUNNERS
# ═══════════════════════════════════════════════════════════

def _metrics(all_trades: list) -> dict:
    """Extract standard metrics from a trades list."""
    from analysis.stats import equity_stats, calc_ratios
    from analysis.montecarlo import monte_carlo
    from analysis.walkforward import walk_forward

    closed = [t for t in all_trades if t.get("result") in ("WIN", "LOSS")]
    if not closed:
        return {
            "n_trades": 0, "win_rate": 0, "pnl": 0, "roi": 0,
            "sharpe": None, "sortino": None, "calmar": None,
            "max_dd_pct": 0, "final_equity": _p.ACCOUNT_SIZE,
            "mc_pct_pos": 0, "wf_stable_pct": 0,
        }
    pnl_list = [t["pnl"] for t in closed]
    eq, mdd, mdd_pct, max_streak = equity_stats(pnl_list)
    ratios = calc_ratios(pnl_list, n_days=getattr(_p, "SCAN_DAYS", 90))
    wr = sum(1 for t in closed if t["result"] == "WIN") / len(closed) * 100

    mc = monte_carlo(pnl_list)
    wf = walk_forward(closed)
    wf_ok = sum(1 for w in wf if abs(w["test"]["wr"] - w["train"]["wr"]) <= 15) if wf else 0
    wf_pct = round(wf_ok / len(wf) * 100) if wf else 0

    return {
        "n_trades": len(closed),
        "win_rate": round(wr, 2),
        "pnl": round(sum(pnl_list), 2),
        "roi": round(ratios.get("ret", 0), 2),
        "sharpe": round(ratios["sharpe"], 4) if ratios.get("sharpe") else None,
        "sortino": round(ratios["sortino"], 4) if ratios.get("sortino") else None,
        "calmar": round(ratios.get("calmar", 0), 4) if ratios.get("calmar") else None,
        "max_dd_pct": round(mdd_pct, 2),
        "final_equity": round(eq[-1], 2),
        "mc_pct_pos": mc.get("pct_pos", 0) if mc else 0,
        "wf_stable_pct": wf_pct,
    }


def run_citadel(all_dfs, macro, corr) -> dict:
    from engines.citadel import scan_symbol
    all_trades = []
    symbols = [s for s in _p.SYMBOLS if s in all_dfs]
    for sym in symbols:
        trades, _ = scan_symbol(all_dfs[sym].copy(), sym, macro, corr)
        all_trades.extend(trades)
    all_trades.sort(key=lambda t: t["timestamp"])
    return _metrics(all_trades)


def run_newton(all_dfs, macro, corr) -> dict:
    from engines.deshaw import find_cointegrated_pairs, scan_pair
    pairs = find_cointegrated_pairs(all_dfs)
    if len(pairs) < 1:
        return _metrics([])
    all_trades = []
    for pair in pairs:
        df_a = all_dfs.get(pair["sym_a"])
        df_b = all_dfs.get(pair["sym_b"])
        if df_a is None or df_b is None:
            continue
        trades, _ = scan_pair(df_a.copy(), df_b.copy(),
                              pair["sym_a"], pair["sym_b"], pair, macro, corr)
        all_trades.extend(trades)
    all_trades.sort(key=lambda t: t["timestamp"])
    return _metrics(all_trades)


def run_thoth(all_dfs, macro, corr, sentiment_data=None) -> dict:
    from engines.bridgewater import scan_thoth
    all_trades = []
    symbols = [s for s in _p.SYMBOLS if s in all_dfs]
    for sym in symbols:
        trades, _ = scan_thoth(all_dfs[sym].copy(), sym, macro, corr,
                               sentiment_data=sentiment_data)
        all_trades.extend(trades)
    all_trades.sort(key=lambda t: t["timestamp"])
    return _metrics(all_trades)


def run_mercurio(all_dfs, macro, corr) -> dict:
    from engines.jump import scan_mercurio
    all_trades = []
    symbols = [s for s in _p.SYMBOLS if s in all_dfs]
    for sym in symbols:
        trades, _ = scan_mercurio(all_dfs[sym].copy(), sym, macro, corr)
        all_trades.extend(trades)
    all_trades.sort(key=lambda t: t["timestamp"])
    return _metrics(all_trades)


RUNNERS = {
    "citadel": run_citadel,
    "newton": run_newton,
    "thoth": run_thoth,
    "mercurio": run_mercurio,
}


# ═══════════════════════════════════════════════════════════
#  GRID RUNNER
# ═══════════════════════════════════════════════════════════

def _patch_param(name: str, val):
    """Patch a param in config.params AND in any engine module that imported it via `from config.params import *`."""
    import sys
    setattr(_p, name, val)
    # Also patch engine modules that did `from config.params import *`
    _engine_modules = [
        "engines.citadel", "engines.deshaw", "engines.bridgewater",
        "engines.jump", "engines.janestreet",
        "core.signals", "core.portfolio", "core.indicators",
    ]
    for mod_name in _engine_modules:
        mod = sys.modules.get(mod_name)
        if mod and hasattr(mod, name):
            setattr(mod, name, val)


def run_grid(engine: str, grid: list[dict], param_names: list[str],
             all_dfs: dict, macro, corr,
             sentiment_data=None) -> list[dict]:
    """Run grid search, monkey-patching params for each combo."""
    runner = RUNNERS.get(engine)
    if runner is None:
        raise ValueError(f"Unknown engine: {engine}. Available: {list(RUNNERS.keys())}")

    # Save originals
    originals = {}
    for name in param_names:
        originals[name] = getattr(_p, name)

    results = []
    total = len(grid)
    for i, combo in enumerate(grid, 1):
        # Patch — both config.params and engine modules
        for name, val in combo.items():
            _patch_param(name, val)

        label = "  ".join(f"{k}={v}" for k, v in combo.items())
        log.info(f"[{i}/{total}] {label}")

        try:
            t0 = time.time()
            if engine == "thoth":
                m = runner(all_dfs, macro, corr, sentiment_data=sentiment_data)
            else:
                m = runner(all_dfs, macro, corr)
            elapsed = round(time.time() - t0, 1)

            row = {**combo, **m, "elapsed_s": elapsed}
            results.append(row)

            sharpe_str = f"{m['sharpe']:.3f}" if m['sharpe'] else "—"
            log.info(f"    → {m['n_trades']}t  WR {m['win_rate']}%  "
                     f"Sharpe {sharpe_str}  PnL ${m['pnl']:+,.0f}  "
                     f"MaxDD {m['max_dd_pct']}%  ({elapsed}s)")
        except Exception as e:
            log.warning(f"    → FAILED: {e}")
            row = {**combo, "n_trades": 0, "error": str(e)}
            results.append(row)

        # Restore
        for name in param_names:
            _patch_param(name, originals[name])

    return results


# ═══════════════════════════════════════════════════════════
#  OUTPUT
# ═══════════════════════════════════════════════════════════

def save_csv(results: list[dict], path: Path):
    if not results:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = list(results[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(results)
    log.info(f"CSV → {path}")


def print_top(results: list[dict], n: int = 10, sort_by: str = "sharpe"):
    valid = [r for r in results if r.get(sort_by) is not None and r.get("n_trades", 0) > 0]
    valid.sort(key=lambda r: r[sort_by] or -999, reverse=True)
    top = valid[:n]

    if not top:
        print("\n  No valid results.")
        return

    print(f"\n  {'─'*72}")
    print(f"  TOP {len(top)} by {sort_by}")
    print(f"  {'─'*72}")
    for i, r in enumerate(top, 1):
        params = {k: v for k, v in r.items()
                  if k not in ("n_trades", "win_rate", "pnl", "roi", "sharpe",
                               "sortino", "calmar", "max_dd_pct", "final_equity",
                               "mc_pct_pos", "wf_stable_pct", "elapsed_s", "error")}
        param_str = "  ".join(f"{k}={v}" for k, v in params.items())
        sharpe = f"{r['sharpe']:.3f}" if r.get('sharpe') else "—"
        sortino = f"{r.get('sortino', 0):.3f}" if r.get('sortino') else "—"
        print(f"  {i:>2d}. {param_str}")
        print(f"      {r['n_trades']}t  WR {r['win_rate']}%  "
              f"Sharpe {sharpe}  Sortino {sortino}  "
              f"PnL ${r['pnl']:+,.0f}  MaxDD {r['max_dd_pct']}%  "
              f"MC {r.get('mc_pct_pos', 0):.0f}%  WF {r.get('wf_stable_pct', 0)}%")


# ═══════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════

def main():
    import argparse
    ap = argparse.ArgumentParser(description="AURUM Param Grid Search")
    ap.add_argument("--engine", required=True, choices=list(RUNNERS.keys()))
    ap.add_argument("--param", action="append", required=True,
                    help="PARAM_NAME:MIN:MAX:STEP or PARAM_NAME:V1:V2:V3")
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--basket", type=str, default="default")
    ap.add_argument("--interval", type=str, default=None,
                    help="TF override (e.g. 1h, 4h). Default: engine's ENGINE_INTERVALS entry.")
    ap.add_argument("--top", type=int, default=10)
    args = ap.parse_args()

    # Setup
    _p.SCAN_DAYS = args.days
    # Resolve engine TF: CLI override > ENGINE_INTERVALS > INTERVAL default
    _engine_key_map = {"citadel": "CITADEL", "newton": "DESHAW",
                       "thoth": "BRIDGEWATER", "mercurio": "JUMP"}
    _ekey = _engine_key_map.get(args.engine)
    if args.interval:
        _p.INTERVAL = args.interval
        if _ekey:
            _p.ENGINE_INTERVALS[_ekey] = args.interval
    elif _ekey:
        _p.INTERVAL = _p.ENGINE_INTERVALS.get(_ekey, _p.INTERVAL)
    _tf_mult = {"1m": 60, "3m": 20, "5m": 12, "15m": 4, "30m": 2,
                "1h": 1, "2h": 0.5, "4h": 0.25}
    _p.N_CANDLES = int(args.days * 24 * _tf_mult.get(_p.INTERVAL, 4))
    # Patch INTERVAL + N_CANDLES em engine modules já importados (import-time freeze)
    _patch_param("INTERVAL", _p.INTERVAL)
    _patch_param("N_CANDLES", _p.N_CANDLES)

    if args.basket and args.basket in _p.BASKETS:
        _p.SYMBOLS = _p.BASKETS[args.basket]

    param_names, grid = build_grid(args.param)
    log.info(f"Engine: {args.engine}  TF: {_p.INTERVAL}  Days: {args.days}  Basket: {args.basket}")
    log.info(f"Grid: {len(grid)} combos  Params: {param_names}")

    # Fetch data once
    log.info("Fetching data...")
    fetch_syms = list(_p.SYMBOLS)
    if _p.MACRO_SYMBOL not in fetch_syms:
        fetch_syms.insert(0, _p.MACRO_SYMBOL)
    all_dfs = fetch_all(fetch_syms, _p.INTERVAL, _p.N_CANDLES)
    for sym, df in all_dfs.items():
        validate(df, sym)

    macro = detect_macro(all_dfs)
    corr = build_corr_matrix(all_dfs)

    # Sentiment (Thoth only)
    sentiment_data = None
    if args.engine == "thoth":
        log.info("Fetching sentiment data...")
        from engines.bridgewater import collect_sentiment
        sentiment_data = collect_sentiment(list(all_dfs.keys()))

    # Run grid
    log.info(f"Starting grid search ({len(grid)} combos)...")
    t0 = time.time()
    results = run_grid(args.engine, grid, param_names, all_dfs, macro, corr,
                       sentiment_data=sentiment_data)
    elapsed = time.time() - t0

    # Save
    date_str = datetime.now().strftime("%Y-%m-%d")
    out_dir = Path(f"data/param_search/{date_str}")
    csv_path = out_dir / f"{args.engine}_grid.csv"
    save_csv(results, csv_path)

    # Print top
    print_top(results, n=args.top)

    log.info(f"Done. {len(grid)} combos in {elapsed:.0f}s. Results → {csv_path}")


if __name__ == "__main__":
    main()
