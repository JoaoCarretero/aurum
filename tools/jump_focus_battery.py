"""
Focused JUMP battery with explicit hypotheses.

Purpose:
- Compare a small set of JUMP variants without editing config/params.py.
- Avoid broad cartesian grids that would invite fishing expedition.
- Validate whether a few plausible levers improve the current regime.
"""
import csv
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config import params as _p
from core.data import fetch_all, validate
from core.htf_filter import htf_agrees, prepare_htf_context
from core.portfolio import build_corr_matrix, detect_macro
from tools.param_search import _metrics, _patch_param

log = logging.getLogger("JUMP_FOCUS")
log.setLevel(logging.INFO)
if not log.handlers:
    _h = logging.StreamHandler(sys.stdout)
    _h.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-5s  %(message)s"))
    log.addHandler(_h)
logging.getLogger("JUMP").setLevel(logging.WARNING)


VARIANTS = [
    {"name": "baseline", "patches": {}, "htf": False},
    {"name": "score_060", "patches": {"MERCURIO_MIN_SCORE": 0.60}, "htf": False},
    {"name": "score_065", "patches": {"MERCURIO_MIN_SCORE": 0.65}, "htf": False},
    {
        "name": "vimb_tight",
        "patches": {"MERCURIO_VIMB_LONG": 0.65, "MERCURIO_VIMB_SHORT": 0.35},
        "htf": False,
    },
    {"name": "liq_tight", "patches": {"MERCURIO_LIQ_VOL_MULT": 4.0}, "htf": False},
    {"name": "size_035", "patches": {"MERCURIO_SIZE_MULT": 0.35}, "htf": False},
    {
        "name": "score_060_vimb_tight",
        "patches": {
            "MERCURIO_MIN_SCORE": 0.60,
            "MERCURIO_VIMB_LONG": 0.65,
            "MERCURIO_VIMB_SHORT": 0.35,
        },
        "htf": False,
    },
    {
        "name": "score_060_size_035",
        "patches": {"MERCURIO_MIN_SCORE": 0.60, "MERCURIO_SIZE_MULT": 0.35},
        "htf": False,
    },
    {"name": "htf_4h", "patches": {}, "htf": True},
    {"name": "htf_4h_score_060", "patches": {"MERCURIO_MIN_SCORE": 0.60}, "htf": True},
]


def _jump_metrics(all_dfs: dict, macro: str, corr, htf_ctx=None) -> tuple[dict, list[dict]]:
    from engines.jump import scan_mercurio

    logging.getLogger("JUMP").setLevel(logging.WARNING)
    all_trades = []
    for sym in [s for s in _p.SYMBOLS if s in all_dfs]:
        trades, _ = scan_mercurio(all_dfs[sym].copy(), sym, macro, corr)
        if htf_ctx:
            trades = [
                t for t in trades
                if htf_agrees(htf_ctx, sym, t.get("entry_idx", t.get("idx", 0)), t.get("direction", ""))
            ]
        all_trades.extend(trades)
    all_trades.sort(key=lambda t: t["timestamp"])

    metrics = _metrics(all_trades)
    closed = [t for t in all_trades if t.get("result") in ("WIN", "LOSS")]
    metrics["long_trades"] = sum(1 for t in closed if t.get("direction") == "LONG")
    metrics["short_trades"] = sum(1 for t in closed if t.get("direction") == "SHORT")
    return metrics, closed


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

    ap = argparse.ArgumentParser(description="Focused JUMP battery")
    ap.add_argument("--days", type=int, default=180)
    ap.add_argument("--basket", type=str, default="bluechip_active")
    ap.add_argument("--interval", type=str, default="1h")
    ap.add_argument(
        "--variants",
        type=str,
        default="",
        help="Comma-separated variant names to run. Default: all.",
    )
    args = ap.parse_args()
    selected_names = {name.strip() for name in args.variants.split(",") if name.strip()}
    variants = [v for v in VARIANTS if not selected_names or v["name"] in selected_names]
    if not variants:
        raise SystemExit("No variants selected.")

    originals = {
        "SCAN_DAYS": _p.SCAN_DAYS,
        "INTERVAL": _p.INTERVAL,
        "N_CANDLES": _p.N_CANDLES,
        "SYMBOLS": list(_p.SYMBOLS),
    }
    jump_originals = {
        "MERCURIO_MIN_SCORE": _p.MERCURIO_MIN_SCORE,
        "MERCURIO_VIMB_LONG": _p.MERCURIO_VIMB_LONG,
        "MERCURIO_VIMB_SHORT": _p.MERCURIO_VIMB_SHORT,
        "MERCURIO_LIQ_VOL_MULT": _p.MERCURIO_LIQ_VOL_MULT,
        "MERCURIO_SIZE_MULT": _p.MERCURIO_SIZE_MULT,
    }

    try:
        _p.SCAN_DAYS = args.days
        _p.INTERVAL = args.interval
        _p.ENGINE_INTERVALS["JUMP"] = args.interval
        tf_mult = {"1m": 60, "3m": 20, "5m": 12, "15m": 4, "30m": 2, "1h": 1, "2h": 0.5, "4h": 0.25}
        _p.N_CANDLES = int(args.days * 24 * tf_mult.get(args.interval, 1))
        _patch_param("INTERVAL", _p.INTERVAL)
        _patch_param("N_CANDLES", _p.N_CANDLES)
        if args.basket in _p.BASKETS:
            _p.SYMBOLS = _p.BASKETS[args.basket]

        fetch_syms = list(_p.SYMBOLS)
        if _p.MACRO_SYMBOL not in fetch_syms:
            fetch_syms.insert(0, _p.MACRO_SYMBOL)

        log.info("Fetching LTF data...")
        all_dfs = fetch_all(fetch_syms, _p.INTERVAL, _p.N_CANDLES)
        for sym, df in all_dfs.items():
            validate(df, sym)

        macro = detect_macro(all_dfs)
        corr = build_corr_matrix(all_dfs)

        need_htf = any(v["htf"] for v in variants)
        htf_ctx = None
        if need_htf:
            log.info("Fetching 4h HTF data...")
            htf_n_candles = int(args.days * 24 * 0.25) + 200
            htf_dfs = fetch_all(fetch_syms, "4h", htf_n_candles)
            for sym, df in htf_dfs.items():
                validate(df, sym)
            htf_ctx = prepare_htf_context(all_dfs, htf_dfs)

        rows = []
        for variant in variants:
            for name, value in variant["patches"].items():
                _patch_param(name, value)

            t0 = time.time()
            metrics, _closed = _jump_metrics(all_dfs, macro, corr, htf_ctx=htf_ctx if variant["htf"] else None)
            elapsed = round(time.time() - t0, 1)
            row = {
                "variant": variant["name"],
                "basket": args.basket,
                "days": args.days,
                "interval": args.interval,
                "htf": variant["htf"],
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

            for name, value in jump_originals.items():
                _patch_param(name, value)

        date_str = datetime.now().strftime("%Y-%m-%d")
        out_path = ROOT / "data" / "param_search" / date_str / "jump_focus_battery.csv"
        _save_csv(rows, out_path)
        log.info(f"CSV -> {out_path}")

    finally:
        _p.SCAN_DAYS = originals["SCAN_DAYS"]
        _p.INTERVAL = originals["INTERVAL"]
        _p.N_CANDLES = originals["N_CANDLES"]
        _p.SYMBOLS = originals["SYMBOLS"]
        _patch_param("INTERVAL", _p.INTERVAL)
        _patch_param("N_CANDLES", _p.N_CANDLES)
        for name, value in jump_originals.items():
            _patch_param(name, value)


if __name__ == "__main__":
    main()
