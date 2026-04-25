"""RENAISSANCE paper runner — standalone, parallel to MILLENNIUM.

Runs only the RENAISSANCE slice of signals through a dedicated paper
account. Writes to ``data/renaissance_paper/<run_id>/{logs,reports,state}/``.

Usage:
    python tools/operations/renaissance_paper.py \\
        --account-size 10000 --tick-sec 900 --run-hours 0 --label desk-a

Env:
    AURUM_RENAISSANCE_PAPER_LABEL     — default label when --label is omitted
    AURUM_RENAISSANCE_PAPER_ACCOUNT_SIZE — default account size

Kill: create ``<run_dir>/.kill`` or send SIGINT/SIGTERM.

Nota OOS: RENAISSANCE tem claim in-sample inflado ~2×. O runner solo
serve pra coletar OOS honesto sobre candles ao vivo — compare os
signals com o slice RENAISSANCE que MILLENNIUM executa pra calibrar o
DSR haircut com evidencia real-time.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ["AURUM_ENGINE_NAME"] = "renaissance"

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.operations._paper_runner import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
