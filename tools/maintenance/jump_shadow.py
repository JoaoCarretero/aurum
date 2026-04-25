"""JUMP shadow runner — standalone, parallel to MILLENNIUM.

Scans only JUMP signals on fresh OHLCV every TICK_SEC, writes novel
trades to ``data/jump_shadow/<run_id>/reports/shadow_trades.jsonl``.

Usage:
    python tools/maintenance/jump_shadow.py --tick-sec 900 --run-hours 24

Env:
    AURUM_JUMP_SHADOW_LABEL  — default label when --label is omitted

Kill: create ``<run_dir>/.kill`` or send SIGINT/SIGTERM.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ["AURUM_ENGINE_NAME"] = "jump"

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.maintenance._shadow_runner import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
