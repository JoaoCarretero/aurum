"""Run analysis.overfit_audit on PHI trade files after schema normalization."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from analysis.overfit_audit import print_audit_box, run_audit


def _normalize_phi_trade(trade: dict) -> dict:
    pnl = float(trade.get("pnl", 0.0) or 0.0)
    if pnl > 0:
        result = "WIN"
    elif pnl < 0:
        result = "LOSS"
    else:
        result = "FLAT"

    direction = trade.get("direction")
    if direction in (1, "1", "LONG", "long", "BULLISH", "bull"):
        norm_direction = "LONG"
    else:
        norm_direction = "SHORT"

    return {
        "symbol": trade.get("symbol"),
        "timestamp": trade.get("exit_time") or trade.get("entry_time"),
        "entry_price": trade.get("entry"),
        "exit_price": trade.get("exit_price"),
        "entry": trade.get("entry"),
        "exit_p": trade.get("exit_price"),
        "size": trade.get("size", 0.0),
        "direction": norm_direction,
        "duration": max(1, int(trade.get("duration_bars", 1) or 1)),
        "pnl": pnl,
        "result": result,
        "score": float(trade.get("omega_phi", 0.0) or 0.0),
        "phi_score": float(trade.get("phi_score", 0.0) or 0.0),
        "omega_phi": float(trade.get("omega_phi", 0.0) or 0.0),
        "macro_bias": trade.get("macro_bias"),
    }


def _load_and_normalize(path: Path) -> list[dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"Expected list of trades in {path}")
    return [_normalize_phi_trade(trade) for trade in raw]


def _summarize(results: dict) -> str:
    parts = [f"{results.get('passed', 0)}/6 PASS"]
    if results.get("warnings", 0):
        parts.append(f"{results['warnings']} WARN")
    if results.get("failed", 0):
        parts.append(f"{results['failed']} FAIL")
    if results.get("skipped", 0):
        parts.append(f"{results['skipped']} SKIP")
    return " | ".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("trade_files", nargs="+", help="One or more PHI trades.json files")
    ap.add_argument("--json-out", default="", help="Optional path to save normalized audit payload")
    args = ap.parse_args()

    payload: dict[str, dict] = {}
    for trade_file in args.trade_files:
        path = Path(trade_file)
        trades = _load_and_normalize(path)
        results = run_audit(trades)
        payload[str(path)] = results
        print(f"\n=== {path} ===")
        print_audit_box(results)
        print(f"Summary: {_summarize(results)}")

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        print(f"\nSaved: {out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
