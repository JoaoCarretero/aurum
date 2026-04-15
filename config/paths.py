"""Project-rooted paths shared across the codebase."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CONFIG_DIR = ROOT / "config"

AURUM_DB_PATH = DATA_DIR / "aurum.db"
NEXUS_DB_PATH = DATA_DIR / "nexus.db"
RUN_INDEX_PATH = DATA_DIR / "index.json"
PROC_STATE_PATH = DATA_DIR / ".aurum_procs.json"
SITE_CONFIG_PATH = CONFIG_DIR / "site.json"
CONNECTIONS_STATE_PATH = CONFIG_DIR / "connections.json"
VPS_CONFIG_PATH = CONFIG_DIR / "vps.json"
PAPER_STATE_PATH = CONFIG_DIR / "paper_state.json"
ALCHEMY_PARAMS_PATH = CONFIG_DIR / "alchemy_params.json"
ALCHEMY_PARAMS_RELOAD_FLAG = CONFIG_DIR / "alchemy_params.json.reload"
