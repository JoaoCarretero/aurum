"""CITADEL paper runner — standalone, parallel to MILLENNIUM.

Runs only the CITADEL slice of signals through a dedicated paper account.
Writes to ``data/citadel_paper/<run_id>/{logs,reports,state}/``.

Usage:
    python tools/operations/citadel_paper.py \\
        --account-size 10000 --tick-sec 900 --run-hours 0 --label desk-a

Env:
    AURUM_CITADEL_PAPER_LABEL     — default label when --label is omitted
    AURUM_CITADEL_PAPER_ACCOUNT_SIZE — default account size

Kill: create ``<run_dir>/.kill`` or send SIGINT/SIGTERM.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Set engine name BEFORE importing the parametric core so its
# module-level path globals land in data/citadel_paper/.
os.environ["AURUM_ENGINE_NAME"] = "citadel"

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.operations._paper_runner import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
