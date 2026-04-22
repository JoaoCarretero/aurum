"""RENAISSANCE shadow runner — standalone, parallel to MILLENNIUM.

Scans only RENAISSANCE signals on fresh OHLCV every TICK_SEC, writes
novel trades to ``data/renaissance_shadow/<run_id>/reports/shadow_trades.jsonl``.

Usage:
    python tools/maintenance/renaissance_shadow.py --tick-sec 900 --run-hours 24

Env:
    AURUM_RENAISSANCE_SHADOW_LABEL  — default label when --label is omitted

Nota OOS: RENAISSANCE tem claim in-sample inflado ~2×. O shadow solo
serve pra acumular evidencia OOS honesta ao vivo, comparavel contra o
slice RENAISSANCE que MILLENNIUM produz pros mesmos candles.

Kill: create ``<run_dir>/.kill`` or send SIGINT/SIGTERM.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ["AURUM_ENGINE_NAME"] = "renaissance"

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.maintenance._shadow_runner import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
