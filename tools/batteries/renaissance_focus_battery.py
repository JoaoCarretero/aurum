"""
Focused RENAISSANCE battery with explicit hypotheses.

Goal:
- Re-run a few disciplined variants on clean data.
- Avoid broad pattern fishing.
- Compare robustness levers around score / RR / stop geometry / capital weight.
"""
import csv
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config import params as _p
from core.data import fetch_all, validate
from core.risk.portfolio import build_corr_matrix, detect_macro

log = logging.getLogger("REN_FOCUS")
log.setLevel(logging.INFO)
if not log.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-5s  %(message)s"))
    log.addHandler(_h)
logging.getLogger("RENAISSANCE").setLevel(logging.WARNING)

VARIANTS = [
    {"name": "baseline", "patches": {}, "capital_weight": 0.35},
    {"name": "score_008", "patches": {"H_MIN_SCORE": 0.08}, "capital_weight": 0.35},
    {"name": "score_012", "patches": {"H_MIN_SCORE": 0.12}, "capital_weight": 0.35},
    {"name": "rr_120", "patches": {"H_MIN_RR": 1.20}, "capital_weight": 0.35},
    {"name": "stop_015", "patches": {"H_STOP_BUFFER": 0.015}, "capital_weight": 0.35},
    {"name": "target_0786", "patches": {"H_TARGET_FIB": 0.786}, "capital_weight": 0.35},
    {"name": "weight_025", "patches": {}, "capital_weight": 0.25},
    {"name": "weight_020", "patches": {}, "capital_weight": 0.20},
    {
        "name": "score_008_weight_025",
        "patches": {"H_MIN_SCORE": 0.08},
        "capital_weight": 0.25,
    },
]


def _metrics(all_trades: list[dict]) -> dict:
    from analysis.stats import equity_stats, calc_ratios
    from analysis.montecarlo import monte_carlo
    from analysis.walkforward import walk_forward

    closed = [t for t in all_trades if t.get("result") in ("WIN", "LOSS")]
    if not closed:
        return {
            "n_trades": 0,
            "win_rate": 0,
            "pnl": 0,
            "roi": 0,
            "sharpe": None,
            "sortino": None,
            "calmar": None,
            "max_dd_pct": 0,
            "final_equity": _p.ACCOUNT_SIZE,
            "mc_pct_pos": 0,
            "wf_stable_pct": 0,
        }
    pnl_list = [t["pnl"] for t in closed]
    eq, _mdd, mdd_pct, _ = equity_stats(pnl_list, _p.ACCOUNT_SIZE)
    ratios = calc_ratios(pnl_list, _p.ACCOUNT_SIZE, n_days=getattr(_p, "SCAN_DAYS", 180))
    wr = sum(1 for t in closed if t["result"] == "WIN") / len(closed) * 100
    mc = monte_carlo(pnl_list)
    wf = walk_forward(closed)
    wf_ok = sum(1 for w in wf if abs(w["test"]["wr"] - w["train"]["wr"]) <= 15) if wf else 0
    return {
        "n_trades": len(closed),
        "win_rate": round(wr, 2),
        "pnl": round(sum(pnl_list), 2),
        "roi": round(ratios.get("ret", 0), 2),
        "sharpe": round(ratios["sharpe"], 4) if ratios.get("sharpe") is not None else None,
        "sortino": round(ratios["sortino"], 4) if ratios.get("sortino") is not None else None,
        "calmar": round(ratios.get("calmar", 0), 4) if ratios.get("calmar") is not None else None,
        "max_dd_pct": round(mdd_pct, 2),
        "final_equity": round(eq[-1], 2),
        "mc_pct_pos": mc.get("pct_pos", 0) if mc else 0,
        "wf_stable_pct": round(wf_ok / len(wf) * 100) if wf else 0,
    }


def _save_csv(rows: list[dict], path: Path) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = []
    seen = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                keys.append(key)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def main():
    import argparse
    import core.harmonics as harms

    ap = argparse.ArgumentParser(description="Focused RENAISSANCE battery")
    ap.add_argument("--days", type=int, default=180)
    ap.add_argument("--basket", type=str, default="bluechip_active")
    ap.add_argument("--interval", type=str, default="15m")
    ap.add_argument("--variants", type=str, default="", help="Comma-separated variant names to run")
    args = ap.parse_args()

    selected = {name.strip() for name in args.variants.split(",") if name.strip()}
    variants = [v for v in VARIANTS if not selected or v["name"] in selected]
    if not variants:
        raise SystemExit("No variants selected.")

    originals = {
        "SCAN_DAYS": _p.SCAN_DAYS,
        "INTERVAL": _p.INTERVAL,
        "N_CANDLES": _p.N_CANDLES,
        "SYMBOLS": list(_p.SYMBOLS),
        "ENGINE_INTERVAL_REN": _p.ENGINE_INTERVALS.get("RENAISSANCE"),
    }
    harmonic_originals = {
        "H_MIN_SCORE": harms.H_MIN_SCORE,
        "H_MIN_RR": harms.H_MIN_RR,
        "H_STOP_BUFFER": harms.H_STOP_BUFFER,
        "H_TARGET_FIB": harms.H_TARGET_FIB,
    }

    try:
        _p.SCAN_DAYS = args.days
        _p.INTERVAL = args.interval
        _p.ENGINE_INTERVALS["RENAISSANCE"] = args.interval
        tf_mult = {"1m": 60, "3m": 20, "5m": 12, "15m": 4, "30m": 2, "1h": 1, "2h": 0.5, "4h": 0.25}
        _p.N_CANDLES = int(args.days * 24 * tf_mult.get(args.interval, 4))
        harms.INTERVAL = args.interval
        if args.basket in _p.BASKETS:
            _p.SYMBOLS = _p.BASKETS[args.basket]

        fetch_syms = list(_p.SYMBOLS)
        if _p.MACRO_SYMBOL not in fetch_syms:
            fetch_syms.insert(0, _p.MACRO_SYMBOL)

        log.info("Fetching data...")
        all_dfs = fetch_all(fetch_syms, interval=args.interval, n_candles=_p.N_CANDLES, futures=True)
        for sym, df in all_dfs.items():
            validate(df, sym)

        macro = detect_macro(all_dfs)
        corr = build_corr_matrix(all_dfs)

        rows = []
        for variant in variants:
            for key, value in harmonic_originals.items():
                setattr(harms, key, value)
            for key, value in variant["patches"].items():
                setattr(harms, key, value)

            all_trades = []
            t0 = time.time()
            for sym in [s for s in _p.SYMBOLS if s in all_dfs]:
                trades, _ = harms.scan_hermes(
                    all_dfs[sym].copy(),
                    sym,
                    macro,
                    corr,
                    None,
                    capital_weight=variant["capital_weight"],
                    log=logging.getLogger("RENAISSANCE"),
                )
                all_trades.extend(trades)
            all_trades.sort(key=lambda t: t["timestamp"])
            metrics = _metrics(all_trades)
            elapsed = round(time.time() - t0, 1)

            row = {
                "variant": variant["name"],
                "basket": args.basket,
                "days": args.days,
                "interval": args.interval,
                "capital_weight": variant["capital_weight"],
                **variant["patches"],
                **metrics,
                "elapsed_s": elapsed,
            }
            rows.append(row)

            sharpe = metrics["sharpe"] if metrics["sharpe"] is not None else 0.0
            log.info(
                f"{variant['name']:<22} "
                f"{metrics['n_trades']:>4}t  WR {metrics['win_rate']:>5.2f}%  "
                f"Sharpe {sharpe:>6.3f}  PnL ${metrics['pnl']:+,.0f}  "
                f"MaxDD {metrics['max_dd_pct']:>5.2f}%"
            )

        date_str = datetime.now().strftime("%Y-%m-%d")
        out_path = ROOT / "data" / "param_search" / date_str / "renaissance_focus_battery.csv"
        _save_csv(rows, out_path)
        log.info(f"CSV -> {out_path}")

    finally:
        _p.SCAN_DAYS = originals["SCAN_DAYS"]
        _p.INTERVAL = originals["INTERVAL"]
        _p.N_CANDLES = originals["N_CANDLES"]
        _p.SYMBOLS = originals["SYMBOLS"]
        _p.ENGINE_INTERVALS["RENAISSANCE"] = originals["ENGINE_INTERVAL_REN"]
        harms.INTERVAL = originals["INTERVAL"]
        for key, value in harmonic_originals.items():
            setattr(harms, key, value)


if __name__ == "__main__":
    main()
