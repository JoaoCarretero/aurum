"""Standalone backtest entrypoint for the RENAISSANCE harmonics engine."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from analysis.stats import calc_ratios, equity_stats
from config.params import ACCOUNT_SIZE, BASKETS, ENGINE_BASKETS, ENGINE_INTERVALS, INTERVAL, LEVERAGE, MACRO_SYMBOL, SCAN_DAYS, SYMBOLS
# Calibrated TF (longrun battery 2026-04-14: 15m bluechip = 6/6 overfit PASS)
INTERVAL = ENGINE_INTERVALS.get("RENAISSANCE", INTERVAL)
from core import build_corr_matrix, detect_macro, fetch_all, validate
from core.harmonics import scan_hermes
from core.run_manager import append_to_index, save_run_artifacts, snapshot_config
from core.fs import atomic_write


RUN_ID = datetime.now().strftime("%Y-%m-%d_%H%M%S")
RUN_DIR = ROOT / "data" / "renaissance" / RUN_ID
(RUN_DIR / "reports").mkdir(parents=True, exist_ok=True)
(RUN_DIR / "logs").mkdir(parents=True, exist_ok=True)

log = logging.getLogger("RENAISSANCE")
log.setLevel(logging.INFO)
log.handlers.clear()
_fmt = logging.Formatter("%(asctime)s  %(levelname)-5s  %(message)s")
_sh = logging.StreamHandler(sys.stdout)
_sh.setFormatter(_fmt)
_fh = logging.FileHandler(RUN_DIR / "logs" / "renaissance.log", encoding="utf-8")
_fh.setFormatter(_fmt)
log.addHandler(_sh)
log.addHandler(_fh)

SEP = "-" * 80


def closed_trade_stats(all_trades: list[dict]) -> tuple[list[dict], int, int, int, float]:
    closed = [t for t in all_trades if t.get("result") in ("WIN", "LOSS")]
    win_count = sum(1 for t in closed if t.get("result") == "WIN")
    loss_count = sum(1 for t in closed if t.get("result") == "LOSS")
    flat_count = len(closed) - win_count - loss_count
    win_rate = (win_count / len(closed) * 100.0) if closed else 0.0
    return closed, win_count, loss_count, flat_count, win_rate


def export_json(
    all_trades: list[dict],
    ratios: dict,
    equity: list[float],
    vetos: dict[str, int],
    basket: str,
    days: int,
    summary: dict,
    config: dict,
    audit_results: dict | None = None,
) -> Path:
    closed, win_count, loss_count, flat_count, win_rate = closed_trade_stats(all_trades)
    max_dd_pct = equity_stats([t["pnl"] for t in closed], ACCOUNT_SIZE)[2] if closed else 0.0
    positive_pnl_count = sum(1 for t in closed if float(t.get("pnl", 0.0) or 0.0) > 0.0)
    non_positive_win_count = sum(
        1 for t in closed
        if t.get("result") == "WIN" and float(t.get("pnl", 0.0) or 0.0) <= 0.0
    )
    payload = {
        "engine": "RENAISSANCE",
        "version": "1.0",
        "run_id": RUN_ID,
        "timestamp": datetime.now().isoformat(),
        "interval": INTERVAL,
        "basket": basket,
        "period_days": days,
        "n_symbols": len({t.get("symbol") for t in all_trades}),
        "account_size": ACCOUNT_SIZE,
        "leverage": LEVERAGE,
        "n_trades": len(closed),
        "win_count": win_count,
        "loss_count": loss_count,
        "flat_count": flat_count,
        "win_rate": round(win_rate, 2),
        "positive_pnl_count": positive_pnl_count,
        "non_positive_win_count": non_positive_win_count,
        "roi": round(ratios.get("ret", 0.0), 2),
        "sharpe": ratios.get("sharpe"),
        "sortino": ratios.get("sortino"),
        "final_equity": round(equity[-1], 2) if equity else ACCOUNT_SIZE,
        "max_dd_pct": max_dd_pct,
        "vetos": vetos,
        "trades": [
            {
                k: (v.isoformat() if hasattr(v, "isoformat") else float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v)
                for k, v in trade.items()
            }
            for trade in closed
        ],
    }
    out = RUN_DIR / "reports" / f"renaissance_{INTERVAL}_v1.json"
    atomic_write(out, json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    save_run_artifacts(RUN_DIR, config, all_trades, equity, summary, overfit_results=audit_results)
    append_to_index(RUN_DIR, summary, config, audit_results)
    return out


def main() -> int:
    global LEVERAGE
    parser = argparse.ArgumentParser(description="RENAISSANCE harmonics standalone backtest")
    parser.add_argument("--days", type=int, default=SCAN_DAYS)
    parser.add_argument("--basket", default=None)
    parser.add_argument("--leverage", type=float, default=LEVERAGE)
    parser.add_argument("--no-menu", action="store_true")
    parser.add_argument("--end", type=str, default=None,
                        help="End date YYYY-MM-DD for backtest window (pre-calibration OOS).")
    args, _ = parser.parse_known_args()
    LEVERAGE = float(args.leverage)
    end_time_ms = None
    if args.end:
        import pandas as _pd_tmp
        end_time_ms = int(_pd_tmp.Timestamp(args.end).timestamp() * 1000)

    args.basket = args.basket or ENGINE_BASKETS.get("RENAISSANCE", "default")
    symbols = list(BASKETS.get(args.basket, SYMBOLS))
    _tf_mult = {"1m":60,"3m":20,"5m":12,"15m":4,"30m":2,"1h":1,"2h":0.5,"4h":0.25}
    n_candles = int(args.days * 24 * _tf_mult.get(INTERVAL, 4))

    print(f"\n{SEP}")
    print(f"  RENAISSANCE  |  {args.days}d  |  {len(symbols)} ativos  |  {INTERVAL}")
    print(f"  ${ACCOUNT_SIZE:,.0f}  |  {LEVERAGE}x")
    print(f"  {RUN_DIR}/")
    print(SEP)

    _fetch_syms = list(symbols)
    if MACRO_SYMBOL not in _fetch_syms:
        _fetch_syms.insert(0, MACRO_SYMBOL)
    all_dfs = fetch_all(_fetch_syms, interval=INTERVAL, n_candles=n_candles, futures=True, end_time_ms=end_time_ms)
    for sym, df in all_dfs.items():
        validate(df, sym)
    if not all_dfs:
        print("  sem dados")
        return 1

    macro_bias = detect_macro(all_dfs)
    corr = build_corr_matrix(all_dfs)

    all_trades: list[dict] = []
    all_vetos: defaultdict[str, int] = defaultdict(int)

    print(f"\n{SEP}\n  SCAN HARMONICS\n{SEP}")
    for sym, df in all_dfs.items():
        trades, vetos = scan_hermes(df.copy(), sym, macro_bias, corr, None, log=log)
        all_trades.extend(trades)
        for key, value in vetos.items():
            all_vetos[key] += value

    all_trades.sort(key=lambda t: t.get("timestamp"))
    closed, win_count, loss_count, flat_count, win_rate = closed_trade_stats(all_trades)
    pnl_list = [float(t.get("pnl", 0.0)) for t in closed]
    equity, _, max_dd_pct, _ = equity_stats(pnl_list, ACCOUNT_SIZE)
    ratios = calc_ratios(pnl_list, ACCOUNT_SIZE, n_days=args.days) if pnl_list else {
        "sharpe": None,
        "sortino": None,
        "calmar": None,
        "ret": 0.0,
    }

    final_equity = equity[-1] if equity else ACCOUNT_SIZE
    pnl = final_equity - ACCOUNT_SIZE
    non_positive_win_count = sum(
        1 for t in closed
        if t.get("result") == "WIN" and float(t.get("pnl", 0.0) or 0.0) <= 0.0
    )
    config = snapshot_config()
    config.update({
        "ENGINE": "RENAISSANCE",
        "RUN_ID": RUN_ID,
        "RUN_DIR": str(RUN_DIR),
        "BASKET_EFFECTIVE": args.basket,
        "SELECTED_SYMBOLS": symbols,
        "SCAN_DAYS_EFFECTIVE": args.days,
        "N_CANDLES_EFFECTIVE": n_candles,
    })
    summary = {
        "engine": "RENAISSANCE",
        "run_id": RUN_ID,
        "interval": INTERVAL,
        "period_days": args.days,
        "basket": args.basket,
        "n_symbols": len(symbols),
        "n_candles": n_candles,
        "account_size": ACCOUNT_SIZE,
        "leverage": LEVERAGE,
        "n_trades": len(closed),
        "win_rate": round(win_rate, 2),
        "pnl": round(pnl, 2),
        "total_pnl": round(pnl, 2),
        "roi_pct": round(ratios.get("ret", 0.0), 2),
        "roi": round(ratios.get("ret", 0.0), 2),
        "sharpe": ratios.get("sharpe"),
        "sortino": ratios.get("sortino"),
        "max_dd_pct": round(max_dd_pct, 2),
        "max_dd": round(max_dd_pct, 2),
        "final_equity": round(final_equity, 2),
        "non_positive_win_count": non_positive_win_count,
    }
    try:
        from analysis.overfit_audit import run_audit, print_audit_box
        audit_results = run_audit(all_trades)
        print_audit_box(audit_results)
    except Exception as _e:
        log.warning(f"overfit audit failed: {_e}")
        audit_results = None

    out = export_json(all_trades, ratios, equity, dict(all_vetos), args.basket, args.days, summary, config, audit_results=audit_results)

    print(f"\n{SEP}\n  METRICAS\n{SEP}")
    print(f"  Trades    {len(closed)}")
    print(f"  W/L/F     {win_count}/{loss_count}/{flat_count}")
    print(f"  WR        {win_rate:.1f}%")
    print(f"  ROI       {ratios.get('ret', 0.0):+.2f}%")
    print(f"  Sharpe    {ratios.get('sharpe') if ratios.get('sharpe') is not None else '-'}")
    print(f"  Sortino   {ratios.get('sortino') if ratios.get('sortino') is not None else '-'}")
    print(f"  MaxDD     {max_dd_pct:.1f}%")
    print(f"  Final     ${final_equity:,.2f}")
    print(f"  PnL       ${pnl:+,.2f}")
    print(f"  json      {out}")

    # Compute MC + WF on-demand for HTML report (RENAISSANCE doesn't
    # carry these in the trade scan, only computes ratios)
    from analysis.montecarlo import monte_carlo
    from analysis.walkforward import walk_forward
    mc_obj = monte_carlo(pnl_list) if pnl_list else None
    wf_obj = walk_forward(closed) if closed else None

    # ── HTML Report ──
    try:
        from analysis.report_html import generate_report
        cond = {}
        wf_regime = {}
        from collections import defaultdict as _dd
        by_sym = _dd(list)
        for t in all_trades:
            by_sym[t.get("symbol", "?")].append(t)
        generate_report(
            all_trades, equity, mc_obj, cond, ratios, max_dd_pct,
            wf_obj, wf_regime,
            by_sym, dict(all_vetos), str(RUN_DIR), config_dict=config,
            engine_name="RENAISSANCE",
        )
        print(f"  HTML      {RUN_DIR / 'report.html'}")
    except Exception as _e:
        log.warning(f"HTML report failed: {_e}")

    print(f"\n{SEP}\n  output  |  {RUN_DIR}/\n{SEP}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
