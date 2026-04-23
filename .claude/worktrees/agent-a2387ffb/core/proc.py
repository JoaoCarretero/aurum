"""
AURUM Finance — Process manager for background engine execution.
Tracks running engines as subprocesses, stores PIDs, routes output to logs.
"""
import os
import sys
import json
import signal
import subprocess
import time
from pathlib import Path
from datetime import datetime

STATE_FILE = Path("data/.aurum_procs.json")

from config.engines import PROC_NAMES as ENGINE_NAMES

ENGINES = {
    "backtest": {"script": "engines/backtest.py"},
    "multi":    {"script": "engines/multistrategy.py"},
    "live":     {"script": "engines/live.py"},
    "arb":      {"script": "engines/arbitrage.py"},
    "newton":   {"script": "engines/newton.py"},
    "mercurio": {"script": "engines/mercurio.py"},
    "thoth":    {"script": "engines/thoth.py"},
    "prometeu": {"script": "engines/prometeu.py"},
    "darwin":   {"script": "engines/darwin.py"},
    "chronos":  {"script": "core/chronos.py"},
}


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"procs": {}}


def _save_state(state: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")


def _is_alive(pid: int) -> bool:
    try:
        if sys.platform == "win32":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, pid)
            if handle:
                exit_code = ctypes.c_ulong()
                kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
                kernel32.CloseHandle(handle)
                return exit_code.value == 259
            return False
        else:
            os.kill(pid, 0)
            return True
    except (OSError, PermissionError):
        return False


def spawn(engine: str, stdin_lines: list[str] | None = None) -> dict | None:
    cfg = ENGINES.get(engine)
    if not cfg:
        return None

    _cleanup()

    state = _load_state()
    for pid_str, info in state["procs"].items():
        if info["engine"] == engine and _is_alive(int(pid_str)):
            return None  # already running

    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    log_dir = Path("data/.proc_logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{engine}_{ts}.log"

    cmd = [sys.executable, "-u", cfg["script"]]

    stdin_data = None
    stdin_pipe = None
    if stdin_lines:
        stdin_data = "\n".join(stdin_lines) + "\n"
        stdin_pipe = subprocess.PIPE

    log_fh = open(log_file, "w", encoding="utf-8")

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONPATH"] = str(Path.cwd())

    try:
        proc = subprocess.Popen(
            cmd, stdin=stdin_pipe, stdout=log_fh, stderr=subprocess.STDOUT,
            cwd=str(Path.cwd()), env=env,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
        )
        if stdin_data:
            try:
                proc.stdin.write(stdin_data.encode("utf-8"))
                proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass
    except Exception:
        log_fh.close()
        return None

    info = {
        "engine": engine,
        "pid": proc.pid,
        "started": datetime.now().isoformat(),
        "log_file": str(log_file),
        "status": "running",
    }
    state["procs"][str(proc.pid)] = info
    _save_state(state)
    return info


def list_procs() -> list[dict]:
    _cleanup()
    state = _load_state()
    result = []
    for pid_str, info in state["procs"].items():
        pid = int(pid_str)
        alive = _is_alive(pid)
        info["alive"] = alive
        if not alive and info.get("status") == "running":
            info["status"] = "finished"
        result.append(info)
    return sorted(result, key=lambda x: x.get("started", ""), reverse=True)


def stop_proc(pid: int) -> bool:
    if not _is_alive(pid):
        return False
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                           capture_output=True, timeout=5)
        else:
            os.kill(pid, signal.SIGTERM)
            time.sleep(1)
            if _is_alive(pid):
                os.kill(pid, signal.SIGKILL)
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False


def delete_proc(pid: int) -> bool:
    """Remove a process entry from state and delete its log file."""
    state = _load_state()
    pid_str = str(pid)
    info = state["procs"].get(pid_str)
    if not info:
        return False
    if _is_alive(pid):
        stop_proc(pid)
    log_file = info.get("log_file")
    if log_file:
        try:
            Path(log_file).unlink(missing_ok=True)
        except OSError:
            pass
    del state["procs"][pid_str]
    _save_state(state)
    return True


def get_log_path(pid: int) -> Path | None:
    state = _load_state()
    info = state["procs"].get(str(pid))
    if not info:
        return None
    p = Path(info.get("log_file", ""))
    return p if p.exists() else None


def _cleanup():
    state = _load_state()
    for pid_str, info in state["procs"].items():
        pid = int(pid_str)
        if not _is_alive(pid) and info.get("status") == "running":
            info["status"] = "finished"
            info["finished"] = datetime.now().isoformat()
    _save_state(state)
