"""
AURUM Finance — EngineRuntime
=============================
Shared runtime setup (RUN_DIR, logging, report saving) for all engines.
Eliminates ~30-50 lines of boilerplate per engine.
"""
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from config.paths import DATA_DIR
from core.persistence import atomic_write_json


class EngineRuntime:
    """Initialise RUN_DIR, logging, and report saving for any engine."""

    def __init__(self, engine_name: str, subdirs=("logs", "reports", "charts")):
        self.name = engine_name
        self.run_date = datetime.now().strftime("%Y-%m-%d")
        self.run_time = datetime.now().strftime("%H%M")
        self.run_id = f"{self.run_date}_{self.run_time}"
        self.run_dir = DATA_DIR / engine_name / self.run_id
        for d in subdirs:
            (self.run_dir / d).mkdir(parents=True, exist_ok=True)
        self.log = self._setup_logging()
        self.trade_log = self._setup_trade_log()

    def _setup_logging(self) -> logging.Logger:
        log = logging.getLogger(self.name.upper())
        if not logging.root.handlers:
            logging.basicConfig(
                level=logging.INFO,
                format="%(asctime)s  %(levelname)s  %(message)s",
                handlers=[
                    logging.FileHandler(
                        self.run_dir / "logs" / "run.log", encoding="utf-8"
                    ),
                    logging.StreamHandler(sys.stdout),
                ],
            )
        return log

    def _setup_trade_log(self) -> logging.Logger:
        tl = logging.getLogger(f"{self.name.upper()}.trades")
        th = logging.FileHandler(
            self.run_dir / "logs" / "trades.log", encoding="utf-8"
        )
        th.setFormatter(logging.Formatter("%(message)s"))
        tl.addHandler(th)
        tl.setLevel(logging.DEBUG)
        tl.propagate = False
        return tl

    def save_report(self, payload: dict, filename: str):
        path = self.run_dir / "reports" / filename
        atomic_write_json(path, payload)
        self.log.info(f"Report -> {path}")
        return path
