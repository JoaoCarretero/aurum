from __future__ import annotations

import ipaddress
import json
import re
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path

from config.engines import ENGINE_NAMES
from config.paths import VPS_CONFIG_PATH
from core.ops.health import runtime_health


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
_HOSTNAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?$")
_SSH_USER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9._-]*$")

_TICKER_DATA: dict[str, dict[str, float]] = {}
_TICKER_LOCK = threading.Lock()
_VPS_CFG_CACHE: dict[str, object] = {"mtime": None, "value": None}


def _normalize_vps_host_user(host: str, user: str) -> tuple[str, str]:
    clean_host = str(host or "").strip()
    clean_user = str(user or "root").strip() or "root"
    if "@" in clean_host:
        embedded_user, embedded_host = clean_host.split("@", 1)
        if embedded_host.strip():
            clean_host = embedded_host.strip()
        if embedded_user.strip():
            clean_user = embedded_user.strip()
    return clean_host, clean_user


def _validate_vps_host(host: str) -> str:
    clean_host = str(host or "").strip()
    if not clean_host:
        raise ValueError("VPS host is not configured in config/vps.json")
    try:
        ipaddress.ip_address(clean_host)
        return clean_host
    except ValueError:
        pass
    if _HOSTNAME_RE.fullmatch(clean_host):
        return clean_host
    raise ValueError("VPS host contains invalid characters")


def _validate_vps_user(user: str) -> str:
    clean_user = str(user or "").strip()
    if not clean_user:
        raise ValueError("VPS user is not configured in config/vps.json")
    if not _SSH_USER_RE.fullmatch(clean_user):
        raise ValueError("VPS user contains invalid characters")
    return clean_user


def _validate_vps_port(port: str) -> str:
    clean_port = str(port or "").strip()
    if not clean_port.isdigit():
        raise ValueError("VPS SSH port must be numeric")
    value = int(clean_port)
    if value < 1 or value > 65535:
        raise ValueError("VPS SSH port is outside the valid range")
    return str(value)


def _validate_key_path(key_path: str) -> str:
    clean_key_path = str(key_path or "").strip()
    if not clean_key_path:
        return ""
    path = Path(clean_key_path).expanduser()
    if not path.is_file():
        raise ValueError(f"SSH key path does not exist: {path}")
    return str(path)


def _validate_remote_shell_command(cmd: str) -> str:
    clean_cmd = str(cmd or "")
    if not clean_cmd.strip():
        raise ValueError("Remote command must not be empty")
    if "\x00" in clean_cmd or "\n" in clean_cmd or "\r" in clean_cmd:
        raise ValueError("Remote command contains unsupported characters")
    return clean_cmd


def _quote_remote_path(path: str) -> str:
    clean_path = str(path or "").strip()
    if clean_path.startswith("~/"):
        clean_path = "$HOME/" + clean_path[2:]
    elif clean_path == "~":
        clean_path = "$HOME"
    return shlex.quote(clean_path)


def _require_vps_host(cfg: dict[str, str]) -> dict[str, str]:
    if str(cfg.get("host") or "").strip():
        return cfg
    raise ValueError("VPS host is not configured in config/vps.json")


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

    host, user = _normalize_vps_host_user(
        str(data.get("host") or "").strip(),
        str(data.get("user") or "root").strip() or "root",
    )
    if host:
        host = _validate_vps_host(host)
    user = _validate_vps_user(user)
    port = _validate_vps_port(str(data.get("port") or "22").strip() or "22")
    remote_dir = str(data.get("remote_dir") or VPS_PROJECT).strip() or VPS_PROJECT
    key_path = _validate_key_path(str(data.get("key_path") or "").strip())
    value = {
        "host": host,
        "user": user,
        "port": port,
        "key_path": key_path,
        "remote_dir": remote_dir,
        "host_display": f"{user}@{host}" if host else "UNCONFIGURED",
    }
    _VPS_CFG_CACHE["mtime"] = mtime
    _VPS_CFG_CACHE["value"] = dict(value)
    return value


def current_vps_host() -> str:
    return load_vps_config()["host_display"]


def current_vps_project() -> str:
    return load_vps_config()["remote_dir"]


def build_vps_ssh_command(cmd: str) -> list[str]:
    cfg = _require_vps_host(load_vps_config())
    remote_cmd = _validate_remote_shell_command(cmd)
    argv = [
        "ssh",
        "-o", "StrictHostKeyChecking=yes",
        "-o", "PasswordAuthentication=no",
        "-o", "IdentitiesOnly=yes",
        "-o", "ConnectTimeout=5",
        "-o", "BatchMode=yes",
        "-p", cfg["port"],
    ]
    if cfg["key_path"]:
        argv += ["-i", cfg["key_path"]]
    argv += [cfg["host_display"], "bash", "-lc", remote_cmd]
    return argv


def build_vps_log_tail_command(project: str) -> str:
    project_q = _quote_remote_path(project)
    return (
        f"tail -f {project_q}/data/live/*/logs/live.log "
        f"{project_q}/data/millennium_live/bootstrap.latest.log 2>/dev/null"
    )


def build_vps_stop_command() -> str:
    return (
        r"screen -S aurum -X stuff $'\003' 2>/dev/null || true; "
        r"screen -S aurum_mln -X stuff $'\003' 2>/dev/null || true"
    )


def build_millennium_bootstrap_launch_command(project: str, mode: str = "diag") -> str:
    clean_mode = str(mode or "diag").strip().lower() or "diag"
    project_q = _quote_remote_path(project)
    mode_q = shlex.quote(clean_mode)
    screen_q = shlex.quote(VPS_MILLENNIUM_SCREEN)
    inner_cmd = (
        f"cd {project_q} && python3 -m engines.millennium_live {mode_q} "
        "2>&1 | tee data/millennium_live/bootstrap.latest.log"
    )
    return (
        f"mkdir -p {project_q}/data/millennium_live && "
        f"screen -dmS {screen_q} bash -lc "
        f"{shlex.quote(inner_cmd)}"
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
    except (ValueError, subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def fetch_ticker_loop() -> None:
    # Import lazily so the launcher shell can appear before the heavy data
    # transport stack (pandas and friends) is loaded.
    from core.data.transport import RequestSpec, TransportClient

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
