from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.params import BASKETS, ENGINE_BASKETS
from core.sentiment import (
    fetch_funding_rate,
    fetch_long_short_ratio,
    fetch_open_interest,
)


def _resolve_symbols(engine: str | None, basket: str | None, symbols_raw: str | None) -> tuple[str, list[str]]:
    if symbols_raw:
        symbols = []
        for raw in symbols_raw.split(","):
            sym = raw.strip().upper()
            if not sym:
                continue
            if not sym.endswith("USDT"):
                sym += "USDT"
            symbols.append(sym)
        return "custom", symbols

    if basket:
        return basket, list(BASKETS.get(basket, []))

    if engine:
        basket_name = ENGINE_BASKETS.get(engine.upper())
        if basket_name:
            return basket_name, list(BASKETS.get(basket_name, []))

    return "default", list(BASKETS["default"])


def _coverage(df):
    if df is None or df.empty:
        return None
    return {
        "rows": int(len(df)),
        "start": df["time"].min().isoformat(),
        "end": df["time"].max().isoformat(),
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Prewarm local sentiment caches for BRIDGEWATER-style OI/LS/funding windows."
    )
    ap.add_argument("--engine", default="BRIDGEWATER", help="Engine preset for basket default.")
    ap.add_argument("--basket", default=None, help="Basket name from config.params.BASKETS.")
    ap.add_argument("--symbols", default=None, help="Comma-separated symbols override.")
    ap.add_argument("--period", default="15m", help="OI/LS period.")
    ap.add_argument("--funding-limit", type=int, default=1000)
    ap.add_argument("--oi-limit", type=int, default=500)
    ap.add_argument("--ls-limit", type=int, default=500)
    ap.add_argument("--json", action="store_true", help="Emit machine-readable summary.")
    args = ap.parse_args()

    basket_name, symbols = _resolve_symbols(args.engine, args.basket, args.symbols)
    if not symbols:
        raise SystemExit(f"no symbols resolved for basket={basket_name!r}")

    report: dict[str, object] = {
        "engine": args.engine.upper() if args.engine else None,
        "basket": basket_name,
        "period": args.period,
        "symbols": {},
    }

    for sym in symbols:
        funding_df = fetch_funding_rate(sym, limit=args.funding_limit)
        oi_df = fetch_open_interest(sym, period=args.period, limit=args.oi_limit)
        ls_df = fetch_long_short_ratio(sym, period=args.period, limit=args.ls_limit)
        report["symbols"][sym] = {
            "funding": _coverage(funding_df),
            "open_interest": _coverage(oi_df),
            "long_short_ratio": _coverage(ls_df),
        }

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"engine={report['engine']} basket={basket_name} period={args.period}")
        for sym, payload in report["symbols"].items():
            funding = payload["funding"]
            oi = payload["open_interest"]
            ls = payload["long_short_ratio"]
            print(
                f"{sym:12s} "
                f"funding={funding['rows'] if funding else 0:>4} "
                f"oi={oi['rows'] if oi else 0:>4} "
                f"ls={ls['rows'] if ls else 0:>4}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
