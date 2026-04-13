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
from config.params import ACCOUNT_SIZE, BASKETS, INTERVAL, LEVERAGE, SCAN_DAYS, SYMBOLS
from core import build_corr_matrix, detect_macro, fetch_all, validate
from core.harmonics import scan_hermes


RUN_ID = datetime.now().strftime("%Y-%m-%d_%H%M")
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

SEP = "─" * 80


def export_json(all_trades: list[dict], ratios: dict, equity: list[float], vetos: dict[str, int], basket: str, days: int) -> Path:
    closed = [t for t in all_trades if t.get("result") in ("WIN", "LOSS")]
    win_rate = (sum(1 for t in closed if t["result"] == "WIN") / len(closed) * 100) if closed else 0.0
    max_dd_pct = equity_stats([t["pnl"] for t in closed], ACCOUNT_SIZE)[2] if closed else 0.0
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
        "win_rate": round(win_rate, 2),
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
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="RENAISSANCE harmonics standalone backtest")
    parser.add_argument("--days", type=int, default=SCAN_DAYS)
    parser.add_argument("--basket", default="default")
    args = parser.parse_args()

    symbols = list(BASKETS.get(args.basket, SYMBOLS))
    n_candles = args.days * 24 * 4

    print(f"\n{SEP}")
    print(f"  RENAISSANCE  ·  {args.days}d  ·  {len(symbols)} ativos  ·  {INTERVAL}")
    print(f"  ${ACCOUNT_SIZE:,.0f}  ·  {LEVERAGE}x")
    print(f"  {RUN_DIR}/")
    print(SEP)

    all_dfs = fetch_all(symbols, interval=INTERVAL, n_candles=n_candles, futures=True)
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
    closed = [t for t in all_trades if t.get("result") in ("WIN", "LOSS")]
    pnl_list = [float(t.get("pnl", 0.0)) for t in closed]
    equity, _, max_dd_pct, _ = equity_stats(pnl_list, ACCOUNT_SIZE)
    ratios = calc_ratios(pnl_list, ACCOUNT_SIZE, n_days=args.days) if pnl_list else {
        "sharpe": None,
        "sortino": None,
        "calmar": None,
        "ret": 0.0,
    }

    win_rate = (sum(1 for t in closed if t["result"] == "WIN") / len(closed) * 100) if closed else 0.0
    final_equity = equity[-1] if equity else ACCOUNT_SIZE
    pnl = final_equity - ACCOUNT_SIZE
    out = export_json(all_trades, ratios, equity, dict(all_vetos), args.basket, args.days)

    print(f"\n{SEP}\n  METRICAS\n{SEP}")
    print(f"  Trades    {len(closed)}")
    print(f"  WR        {win_rate:.1f}%")
    print(f"  ROI       {ratios.get('ret', 0.0):+.2f}%")
    print(f"  Sharpe    {ratios.get('sharpe') if ratios.get('sharpe') is not None else '—'}")
    print(f"  Sortino   {ratios.get('sortino') if ratios.get('sortino') is not None else '—'}")
    print(f"  MaxDD     {max_dd_pct:.1f}%")
    print(f"  Final     ${final_equity:,.2f}")
    print(f"  PnL       ${pnl:+,.2f}")
    print(f"  json      {out}")
    print(f"\n{SEP}\n  output  ·  {RUN_DIR}/\n{SEP}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
