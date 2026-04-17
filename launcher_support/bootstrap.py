from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

from config.engines import ENGINE_NAMES
from config.paths import VPS_CONFIG_PATH
from core.health import runtime_health
from core.transport import RequestSpec, TransportClient


LEGACY_ENGINE_ALIASES = {
    "backtest": "citadel",
    "citadel": "citadel",
    "thoth": "bridgewater",
    "bridgewater": "bridgewater",
    "mercurio": "jump",
    "jump": "jump",
    "newton": "deshaw",
    "deshaw": "deshaw",
    "de_shaw": "deshaw",
    "prometeu": "twosigma",
    "twosigma": "twosigma",
    "two_sigma": "twosigma",
    "darwin": "aqr",
    "aqr": "aqr",
    "multistrategy": "millennium",
    "millennium": "millennium",
    "harmonics": "renaissance",
    "harmonics_backtest": "renaissance",
    "renaissance": "renaissance",
    "arbitrage": "janestreet",
    "jane_street": "janestreet",
    "janestreet": "janestreet",
}

ENGINE_PREFIX_ALIASES = (
    "citadel_", "thoth_", "bridgewater_", "newton_", "deshaw_",
    "mercurio_", "jump_", "multistrategy_", "millennium_",
    "prometeu_", "twosigma_", "renaissance_", "harmonics_",
)

VPS_HOST = "root@37.60.254.151"
VPS_PROJECT = "~/aurum.finance"
VPS_LIVE_SCREEN = "aurum"
VPS_MILLENNIUM_SCREEN = "aurum_mln"
NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

_TICKER_DATA: dict[str, dict[str, float]] = {}
_TICKER_LOCK = threading.Lock()
_VPS_CFG_CACHE: dict[str, object] = {"mtime": None, "value": None}


def canonical_engine_key(name) -> str:
    raw = str(name or "").strip().lower().replace(" ", "_")
    return LEGACY_ENGINE_ALIASES.get(raw, raw)


def engine_display_name(name) -> str:
    key = canonical_engine_key(name)
    return ENGINE_NAMES.get(key, key.replace("_", " ").upper())


def load_vps_config() -> dict[str, str]:
    """Load config/vps.json with a small mtime cache."""
    path = Path(VPS_CONFIG_PATH)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = None
    if _VPS_CFG_CACHE["value"] is not None and _VPS_CFG_CACHE["mtime"] == mtime:
        return dict(_VPS_CFG_CACHE["value"])  # type: ignore[arg-type]

    data: dict[str, object] = {}
    if mtime is not None:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data = raw
        except (OSError, json.JSONDecodeError):
            data = {}

    host = str(data.get("host") or "").strip()
    user = str(data.get("user") or "root").strip() or "root"
    port = str(data.get("port") or "22").strip() or "22"
    remote_dir = str(data.get("remote_dir") or VPS_PROJECT).strip() or VPS_PROJECT
    key_path = str(data.get("key_path") or "").strip()
    value = {
        "host": host,
        "user": user,
        "port": port,
        "key_path": key_path,
        "remote_dir": remote_dir,
        "host_display": f"{user}@{host}" if host else VPS_HOST,
    }
    _VPS_CFG_CACHE["mtime"] = mtime
    _VPS_CFG_CACHE["value"] = dict(value)
    return value


def current_vps_host() -> str:
    return load_vps_config()["host_display"]


def current_vps_project() -> str:
    return load_vps_config()["remote_dir"]


def build_vps_ssh_command(cmd: str) -> list[str]:
    cfg = load_vps_config()
    argv = [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=5",
        "-o", "BatchMode=yes",
        "-p", cfg["port"],
    ]
    if cfg["key_path"]:
        argv += ["-i", cfg["key_path"]]
    argv += [cfg["host_display"], cmd]
    return argv


def build_vps_log_tail_command(project: str) -> str:
    return (
        f"tail -f {project}/data/live/*/logs/live.log "
        f"{project}/data/millennium_live/bootstrap.latest.log 2>/dev/null"
    )


def build_vps_stop_command() -> str:
    return (
        r"screen -S aurum -X stuff $'\003' 2>/dev/null || true; "
        r"screen -S aurum_mln -X stuff $'\003' 2>/dev/null || true"
    )


def build_millennium_bootstrap_launch_command(project: str, mode: str = "diag") -> str:
    clean_mode = str(mode or "diag").strip().lower() or "diag"
    return (
        f"mkdir -p {project}/data/millennium_live && "
        f"screen -dmS {VPS_MILLENNIUM_SCREEN} bash -lc "
        f"'cd {project} && python3 -m engines.millennium_live {clean_mode} "
        f"2>&1 | tee data/millennium_live/bootstrap.latest.log'"
    )


def run_vps_cmd(cmd: str, timeout: int = 10) -> str | None:
    """Run a command on the VPS over SSH from a worker thread."""
    try:
        r = subprocess.run(
            build_vps_ssh_command(cmd),
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=NO_WINDOW,
        )
        if r.returncode == 0:
            return r.stdout
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def fetch_ticker_loop() -> None:
    client = TransportClient()
    while True:
        try:
            r = client.request(RequestSpec(
                method="GET",
                url="https://fapi.binance.com/fapi/v1/ticker/24hr",
                timeout=8,
            ))
            if r.status_code == 200:
                payload = {t["symbol"]: t for t in r.json()}
                with _TICKER_LOCK:
                    for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]:
                        if sym in payload:
                            _TICKER_DATA[sym] = {
                                "p": float(payload[sym]["lastPrice"]),
                                "c": float(payload[sym]["priceChangePercent"]),
                            }
        except Exception:
            runtime_health.record("launcher.ticker_fetch_failure")
        time.sleep(12)


def ticker_str() -> str:
    with _TICKER_LOCK:
        if not _TICKER_DATA:
            return "connecting..."
        return "   ".join(
            f"{sym.replace('USDT', '')} {_TICKER_DATA[sym]['p']:,.2f} "
            f"{'+' if _TICKER_DATA[sym]['c'] >= 0 else ''}{_TICKER_DATA[sym]['c']:.1f}%"
            for sym in ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
            if sym in _TICKER_DATA
        )
