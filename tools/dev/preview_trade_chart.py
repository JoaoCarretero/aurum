"""Dev tool — open TradeChartPopup directly with a fixture trade record.

Use when there are no non-primed trades yet in paper/shadow runs and you
still want to validate the chart popup visually (candles from Binance,
entry/stop/tp/exit markers, header/footer).

Usage:
    python tools/dev/preview_trade_chart.py
    python tools/dev/preview_trade_chart.py --live    # fake a LIVE trade
    python tools/dev/preview_trade_chart.py --run <run_dir>  # use real trade from run

Bypasses the cockpit API + primed filter entirely — loads the trade
record from shadow_trades.jsonl (or uses a hardcoded fixture if no run
is provided) and opens the popup.
"""
from __future__ import annotations

import argparse
import json
import sys
import tkinter as tk
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from launcher_support.trade_chart_popup import TradeChartPopup  # noqa: E402


_PALETTE = {
    "BG": "#0a0a0a",
    "PANEL": "#1a1a1a",
    "BG2": "#202020",
    "BG3": "#2a2a2a",
    "AMBER": "#FFB000",
    "AMBER_B": "#FFC940",
    "AMBER_D": "#C08000",
    "GREEN": "#44FF88",
    "RED": "#FF4444",
    "WHITE": "#FFFFFF",
    "DIM": "#888888",
    "DIM2": "#555555",
    "BORDER": "#333333",
}


def _fixture_closed_trade() -> dict:
    """Hand-crafted closed trade record (JUMP SANDUSDT, realistic)."""
    return {
        "symbol": "SANDUSDT",
        "timestamp": "2026-04-21T23:00:00+00:00",
        "entry_idx": 8639,
        "strategy": "JUMP",
        "direction": "BEARISH",
        "trade_type": "ORDER-FLOW",
        "entry": 0.07757672,
        "stop": 0.0787,
        "target": 0.0742,
        "exit_p": 0.0742,
        "rr": 3.0,
        "duration": 9,
        "result": "WIN",
        "exit_reason": "target",
        "pnl": 24.30,
        "size": 16784.609,
        "r_multiple": 1.80,
        "score": 0.801,
    }


def _fixture_live_trade() -> dict:
    """Hand-crafted LIVE trade record."""
    t = _fixture_closed_trade()
    t.update({
        "result": "LIVE",
        "exit_reason": "live",
        "duration": 0,
        "r_multiple": 0.0,
        "pnl": 8.20,
        "exit_p": 0.0778,  # mark price, distinct from entry
    })
    return t


def _load_real_trade(run_dir: Path) -> dict | None:
    for name in ("shadow_trades.jsonl", "trades.jsonl"):
        path = run_dir / "reports" / name
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--live", action="store_true",
                    help="Use a LIVE fixture trade (activates 5s refresh)")
    ap.add_argument("--run", type=Path, default=None,
                    help="Path to a run dir to pull first trade from its "
                         "reports/shadow_trades.jsonl or trades.jsonl")
    ap.add_argument("--json", type=Path, default=None,
                    help="Path to a JSON file containing a single trade "
                         "record (dict). Useful when the trade lives on a "
                         "remote run (fetched via cockpit client).")
    args = ap.parse_args()

    if args.json is not None:
        trade = json.loads(args.json.read_text(encoding="utf-8"))
        if not isinstance(trade, dict):
            print("--json must be a dict (single trade), got "
                  f"{type(trade).__name__}", file=sys.stderr)
            return 1
        source = f"json={args.json.name}"
    elif args.run is not None:
        trade = _load_real_trade(args.run)
        if trade is None:
            print(f"no trade record found in {args.run}/reports/", file=sys.stderr)
            return 1
        source = f"run={args.run.name}"
    elif args.live:
        trade = _fixture_live_trade()
        source = "fixture (LIVE)"
    else:
        trade = _fixture_closed_trade()
        source = "fixture (closed, WIN)"

    print(f"opening popup: {trade.get('symbol')} "
          f"{trade.get('strategy')} {trade.get('direction')} ({source})")

    root = tk.Tk()
    root.title("AURUM · trade chart preview")
    root.configure(bg=_PALETTE["BG"])
    # Put something in root so it's visible if popup takes a moment
    tk.Label(
        root, text=f"previewing {trade.get('symbol')} · ESC to close",
        fg=_PALETTE["AMBER"], bg=_PALETTE["BG"],
        font=("Consolas", 10), padx=40, pady=20,
    ).pack()

    popup = TradeChartPopup(
        root, trade, run_id="preview",
        colors=_PALETTE, font_name="Consolas",
    )

    def _exit_on_popup_close(*_a):
        try:
            root.destroy()
        except Exception:
            pass

    # Closing the popup ends the preview session.
    popup.top.protocol("WM_DELETE_WINDOW",
                       lambda: (popup.destroy(), _exit_on_popup_close()))
    popup.top.bind("<Escape>",
                   lambda _e: (popup.destroy(), _exit_on_popup_close()))

    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
