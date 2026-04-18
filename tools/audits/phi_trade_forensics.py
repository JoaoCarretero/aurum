"""Forensic summary for PHI trade runs.

Focus:
- geometry inconsistency between direction and SL/TP stack
- tiny-win dependence
- same-bar exits / ultra-short holds
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _load(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Expected list in {path}")
    return data


def _classify_geometry(trade: dict) -> str:
    entry = float(trade["entry"])
    sl = float(trade["sl"])
    tp1 = float(trade["tp1"])
    direction = int(trade["direction"])
    long_ok = sl < entry and tp1 > entry
    short_ok = sl > entry and tp1 < entry
    if (direction == 1 and long_ok) or (direction == -1 and short_ok):
        return "coherent"
    if (direction == 1 and short_ok) or (direction == -1 and long_ok):
        return "flipped"
    return "ambiguous"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("trade_file")
    args = ap.parse_args()

    path = Path(args.trade_file)
    trades = _load(path)
    n = len(trades)
    if not trades:
        print("No trades.")
        return 0

    coherent = [t for t in trades if _classify_geometry(t) == "coherent"]
    flipped = [t for t in trades if _classify_geometry(t) == "flipped"]
    ambiguous = [t for t in trades if _classify_geometry(t) == "ambiguous"]
    tiny_wins = [t for t in trades if 0 < float(t.get("pnl", 0.0)) < 0.5]
    same_bar = [t for t in trades if int(t.get("duration_bars", 0) or 0) == 0]
    short_hold = [t for t in trades if int(t.get("duration_bars", 0) or 0) <= 2]
    partial_negative = [
        t for t in trades
        if any(float(p.get("pnl", 0.0)) < 0 for p in t.get("partials", []))
    ]

    def pnl_sum(rows: list[dict]) -> float:
        return sum(float(t.get("pnl", 0.0) or 0.0) for t in rows)

    print(f"Run: {path}")
    print(f"Trades: {n}")
    print(f"Geometry coherent : {len(coherent):4d} | pnl={pnl_sum(coherent):+8.2f}")
    print(f"Geometry flipped  : {len(flipped):4d} | pnl={pnl_sum(flipped):+8.2f}")
    print(f"Geometry ambiguous: {len(ambiguous):4d} | pnl={pnl_sum(ambiguous):+8.2f}")
    print(f"Tiny wins <0.5    : {len(tiny_wins):4d} | pnl={pnl_sum(tiny_wins):+8.2f}")
    print(f"Same-bar exits    : {len(same_bar):4d} | pnl={pnl_sum(same_bar):+8.2f}")
    print(f"Hold <=2 bars     : {len(short_hold):4d} | pnl={pnl_sum(short_hold):+8.2f}")
    print(f"Neg partials      : {len(partial_negative):4d} | pnl={pnl_sum(partial_negative):+8.2f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
