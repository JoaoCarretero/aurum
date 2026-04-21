from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.params import BASKETS, ENGINE_BASKETS, MAX_HOLD, _TF_MINUTES
from core.sentiment import _load_cached_frame


def _parse_symbols(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    symbols: list[str] = []
    for token in raw.split(","):
        sym = token.strip().upper()
        if not sym:
            continue
        if not sym.endswith("USDT"):
            sym += "USDT"
        symbols.append(sym)
    return symbols or None


def _resolve_symbols(engine: str | None, basket: str | None, symbols_raw: str | None) -> tuple[str, list[str]]:
    symbols = _parse_symbols(symbols_raw)
    if symbols:
        return "custom", symbols
    if basket:
        return basket, list(BASKETS.get(basket, []))
    if engine:
        basket_name = ENGINE_BASKETS.get(engine.upper())
        if basket_name:
            return basket_name, list(BASKETS.get(basket_name, []))
    return "default", list(BASKETS["default"])


def earliest_contiguous_ts(kind: str, symbol: str, period: str) -> pd.Timestamp | None:
    cols = {
        "open_interest": ["time", "oi", "oi_value"],
        "long_short_ratio": ["time", "ls_ratio", "long_pct", "short_pct"],
    }[kind]
    df = _load_cached_frame(kind, symbol, period, cols)
    if df is None or df.empty:
        return None
    df = df.sort_values("time").reset_index(drop=True)
    df["gap"] = df["time"].diff()
    df["block"] = (df["gap"] > pd.Timedelta("1h")).cumsum()
    last_block = df[df["block"] == df["block"].max()]
    return pd.Timestamp(last_block["time"].min())


def joint_contiguous_start(
    symbol: str,
    period: str,
    *,
    disable_oi: bool = False,
) -> tuple[pd.Timestamp | None, dict[str, str | None]]:
    oi = earliest_contiguous_ts("open_interest", symbol, period)
    ls = earliest_contiguous_ts("long_short_ratio", symbol, period)
    starts = [ts for ts in (() if disable_oi else (oi,)) if ts is not None]
    if ls is not None:
        starts.append(ls)
    joint = max(starts) if starts else None
    return joint, {
        "open_interest": oi.isoformat() if oi is not None else None,
        "long_short_ratio": ls.isoformat() if ls is not None else None,
    }


def available_scan_candles(
    joint_start: pd.Timestamp | None,
    end: pd.Timestamp,
    interval: str,
) -> int:
    if joint_start is None:
        return 0
    tf_minutes = max(1, int(_TF_MINUTES.get(interval, 60)))
    delta = end - pd.Timestamp(joint_start)
    candles = math.floor(delta.total_seconds() / (tf_minutes * 60.0))
    return max(0, candles)


def max_eligible_days(
    available_candles: int,
    interval: str,
    *,
    min_fraction: float,
    max_hold: int,
) -> float:
    if available_candles <= max_hold + 2:
        return 0.0
    max_scan_candles = math.floor(available_candles / float(min_fraction))
    tf_minutes = max(1, int(_TF_MINUTES.get(interval, 60)))
    return round((max_scan_candles * tf_minutes) / (60.0 * 24.0), 2)


def audit_symbol(
    symbol: str,
    *,
    period: str,
    interval: str,
    end: pd.Timestamp,
    min_fraction: float,
    max_hold: int,
    disable_oi: bool = False,
) -> dict[str, object]:
    joint_start, channel_starts = joint_contiguous_start(symbol, period, disable_oi=disable_oi)
    available = available_scan_candles(joint_start, end, interval)
    return {
        "symbol": symbol,
        "joint_start": joint_start.isoformat() if joint_start is not None else None,
        "channel_starts": channel_starts,
        "available_scan_candles": available,
        "max_eligible_days": max_eligible_days(
            available,
            interval,
            min_fraction=min_fraction,
            max_hold=max_hold,
        ),
    }


def build_report(args: argparse.Namespace) -> dict[str, object]:
    basket_name, symbols = _resolve_symbols(args.engine, args.basket, args.symbols)
    end = pd.Timestamp(args.end) if args.end else pd.Timestamp.utcnow().tz_localize(None)
    disable_oi = bool(getattr(args, "disable_oi", False))
    rows = [
        audit_symbol(
            sym,
            period=args.period,
            interval=args.interval,
            end=end,
            min_fraction=args.min_fraction,
            max_hold=args.max_hold,
            disable_oi=disable_oi,
        )
        for sym in symbols
    ]
    eligible_days = [row["max_eligible_days"] for row in rows if row["max_eligible_days"] > 0]
    basket_cap = min(eligible_days) if eligible_days else 0.0
    blocker = None
    if eligible_days:
        blocker = min(
            (row for row in rows if row["max_eligible_days"] > 0),
            key=lambda row: row["max_eligible_days"],
        )["symbol"]
    stable_symbols = [
        row["symbol"]
        for row in rows
        if row["max_eligible_days"] >= 30.0
    ]
    stable_cap = min(
        (row["max_eligible_days"] for row in rows if row["symbol"] in stable_symbols),
        default=0.0,
    )
    return {
        "engine": args.engine.upper() if args.engine else None,
        "basket": basket_name,
        "interval": args.interval,
        "period": args.period,
        "end": end.isoformat(),
        "disable_oi": disable_oi,
        "min_fraction": args.min_fraction,
        "max_hold": args.max_hold,
        "basket_max_eligible_days": basket_cap,
        "basket_blocker": blocker,
        "stable_symbols_30d": stable_symbols,
        "stable_symbols_30d_count": len(stable_symbols),
        "stable_symbols_30d_cap": stable_cap,
        "symbols": rows,
    }


def _print_text(report: dict[str, object]) -> None:
    print(
        f"engine={report['engine']} basket={report['basket']} interval={report['interval']} "
        f"period={report['period']} end={report['end']} disable_oi={report['disable_oi']}"
    )
    print(
        f"basket_max_eligible_days={report['basket_max_eligible_days']} "
        f"basket_blocker={report['basket_blocker']}"
    )
    print(
        f"stable_symbols_30d_count={report['stable_symbols_30d_count']} "
        f"stable_symbols_30d_cap={report['stable_symbols_30d_cap']}"
    )
    for row in report["symbols"]:
        print(
            f"{row['symbol']:12s} joint_start={row['joint_start'] or '-':19s} "
            f"scan_candles={row['available_scan_candles']:>4} "
            f"max_days={row['max_eligible_days']:>6}"
        )


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Audit how much Bridgewater scan history is actually valid given cached OI/LS continuity."
    )
    ap.add_argument("--engine", default="BRIDGEWATER")
    ap.add_argument("--basket", default=None)
    ap.add_argument("--symbols", default=None)
    ap.add_argument("--interval", default="1h")
    ap.add_argument("--period", default="15m")
    ap.add_argument("--end", default=None)
    ap.add_argument("--disable-oi", action="store_true")
    ap.add_argument("--min-fraction", type=float, default=0.70)
    ap.add_argument("--max-hold", type=int, default=MAX_HOLD)
    ap.add_argument("--json", action="store_true")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    report = build_report(args)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_text(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
