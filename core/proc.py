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
from datetime import datetime, timedelta

STATE_FILE = Path("data/.aurum_procs.json")

# How long finished entries stay visible in list_procs / state file before
# _cleanup prunes them. Set to 1 day so a finished engine stays introspectable
# (logs still readable, status queryable) for the rest of the current session
# but doesn't accumulate forever. Entries from previous weeks become zombies
# and pollute the UI. [Fase 0.4 / D6]
ZOMBIE_TTL = timedelta(days=1)

from config.engines import PROC_NAMES as ENGINE_NAMES

ENGINES = {
    "backtest": {"script": "engines/backtest.py"},
    "multi":    {"script": "engines/multistrategy.py"},
    "live":     {"script": "engines/live.py"},
    "arb":      {"script": "engines/arbitrage.py"},
    "newton":   {"script": "engines/newton.py"},
    "mercurio": {"script": "engines/mercurio.py"},
    "thoth":    {"script": "engines/thoth.py"},
    "renaissance": {"script": "engines/harmonics_backtest.py"},
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


# Windows API constants
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_STILL_ACTIVE = 259


def _win_get_creation_time(pid: int) -> int | None:
    """Return the Windows creation time of ``pid`` as a 100-ns FILETIME int.

    The FILETIME encodes 100-nanosecond intervals since 1601-01-01 UTC and
    is process-unique: two different processes (including a new PID that
    inherited the slot of a long-dead one) will never share the exact same
    FILETIME. That's what makes it the load-bearing field for the D5 /
    PID-recycling defense.

    Returns None if the process cannot be opened or the API call fails.
    """
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        creation = wintypes.FILETIME()
        exit_t   = wintypes.FILETIME()
        kernel_t = wintypes.FILETIME()
        user_t   = wintypes.FILETIME()
        ok = kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_t),
            ctypes.byref(kernel_t),
            ctypes.byref(user_t),
        )
        if not ok:
            return None
        return (creation.dwHighDateTime << 32) | creation.dwLowDateTime
    finally:
        kernel32.CloseHandle(handle)


def _win_get_image_name(pid: int) -> str | None:
    """Return the basename of the process image (lowercased), or None.

    Typical values for tracked engines: ``python.exe`` or ``pythonw.exe``.
    Any other value — e.g. ``chrome.exe``, ``svchost.exe`` — is a clear
    signal that the PID has been recycled and identity verification should
    fail the _is_alive check.
    """
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        ok = kernel32.QueryFullProcessImageNameW(
            handle, 0, buf, ctypes.byref(size))
        if not ok:
            return None
        return Path(buf.value).name.lower()
    finally:
        kernel32.CloseHandle(handle)


def _is_alive(pid: int, expected: dict | None = None) -> bool:
    """Return True iff ``pid`` is alive AND matches the expected identity.

    Two-layer check:

    1. **Liveness** — OpenProcess + GetExitCodeProcess (Windows) or
       os.kill(pid, 0) (POSIX). Matches the pre-D5 behavior.

    2. **Identity** — when ``expected`` is a tracked proc dict, the
       Windows FILETIME creation_time and image_name of the current PID
       must match the values captured by ``spawn()`` when the tracked
       process first started. Any mismatch means the PID has been
       recycled (Windows does this aggressively) and the function returns
       False even though the OS says something with that PID is running.

       This is the D5 / PID-recycling defense. Without it, a zombie proc
       entry can silently "come back to life" as soon as Windows gives
       its PID to an unrelated process (browser, svchost, …), and a
       subsequent stop_proc call would taskkill that unrelated process.

    ``expected`` is optional — legacy callers that still pass only ``pid``
    get the old liveness-only behavior. New callers and all stop_proc /
    delete_proc paths MUST pass the tracked entry.
    """
    # Step 1: plain liveness
    try:
        if sys.platform == "win32":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(
                _PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                return False
            try:
                exit_code = ctypes.c_ulong()
                kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
                if exit_code.value != _STILL_ACTIVE:
                    return False
            finally:
                kernel32.CloseHandle(handle)
        else:
            os.kill(pid, 0)
    except (OSError, PermissionError):
        return False

    if expected is None:
        return True

    # Step 2: identity. Windows only for now — POSIX falls back to liveness.
    if sys.platform != "win32":
        return True

    exp_ct = expected.get("creation_time")
    if exp_ct is not None:
        current_ct = _win_get_creation_time(pid)
        if current_ct != exp_ct:
            return False

    exp_img = expected.get("image_name")
    if exp_img is not None:
        current_img = _win_get_image_name(pid)
        if current_img != exp_img:
            return False

    return True


def spawn(engine: str, stdin_lines: list[str] | None = None,
          cli_args: list[str] | None = None) -> dict | None:
    cfg = ENGINES.get(engine)
    if not cfg:
        return None

    _cleanup()

    state = _load_state()
    for pid_str, info in state["procs"].items():
        if info["engine"] == engine and _is_alive(int(pid_str), expected=info):
            return None  # already running (identity-verified)

    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    log_dir = Path("data/.proc_logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{engine}_{ts}.log"

    cmd = [sys.executable, "-u", cfg["script"]]
    if cli_args:
        cmd.extend(cli_args)

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
    # [Fase 1 / D5] Capture process identity fingerprints the instant the
    # child process exists. creation_time is a 100ns FILETIME that is
    # process-unique — any future PID that inherits proc.pid will have a
    # different creation_time and fail _is_alive's identity check.
    if sys.platform == "win32":
        ct = _win_get_creation_time(proc.pid)
        if ct is not None:
            info["creation_time"] = ct
        img = _win_get_image_name(proc.pid)
        if img is not None:
            info["image_name"] = img
    state["procs"][str(proc.pid)] = info
    _save_state(state)
    return info


def list_procs() -> list[dict]:
    _cleanup()
    state = _load_state()
    result = []
    for pid_str, info in state["procs"].items():
        pid = int(pid_str)
        # Identity-aware liveness — a recycled PID reads as False even if
        # the OS has something running with that number.
        alive = _is_alive(pid, expected=info)
        info["alive"] = alive
        if not alive and info.get("status") == "running":
            info["status"] = "finished"
            info.setdefault("finished", datetime.now().isoformat())
        result.append(info)
    return sorted(result, key=lambda x: x.get("started", ""), reverse=True)


class PidRecycledError(RuntimeError):
    """Raised when stop_proc detects a PID that has been reused by an
    unrelated process. This is the D5 safety net — refuse to taskkill
    something we didn't spawn."""


def stop_proc(pid: int, expected: dict | None = None) -> bool:
    """Stop a tracked process, verifying identity to defend against
    Windows PID recycling.

    Safety contract:
    - If ``expected`` is None, auto-fetch the tracked entry from the
      state file. This means UI code that still calls ``stop_proc(pid)``
      gets identity verification automatically, as long as the PID is
      in the state file (which it is for every engine spawned through
      this module).
    - If the pid is NOT in the state file and ``expected`` is still
      None, falls back to the old liveness-only check. This preserves
      the pre-D5 behavior for the narrow case where a caller holds a
      pid from outside this module.
    - If ``expected`` IS provided and identity verification fails, we
      raise PidRecycledError rather than silently taskkilling the wrong
      process. The caller is forced to notice.

    Returns True iff the process was running AND was successfully killed.
    Returns False if it was already dead.
    """
    if expected is None:
        state = _load_state()
        expected = state["procs"].get(str(pid))

    # Liveness-only when we have no identity fingerprint to compare against.
    if expected is None:
        if not _is_alive(pid):
            return False
    else:
        # Separate the two checks so we can tell "already dead" (benign)
        # apart from "PID was reused by someone else" (CRITICAL).
        if not _is_alive(pid):  # liveness-only first
            return False
        if not _is_alive(pid, expected=expected):
            raise PidRecycledError(
                f"pid {pid} no longer matches the tracked identity "
                f"(engine={expected.get('engine')}, "
                f"expected creation_time={expected.get('creation_time')}, "
                f"expected image_name={expected.get('image_name')}). "
                f"Refusing to taskkill an unrelated process."
            )

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
    """Remove a process entry from state and delete its log file.

    If the tracked process is still alive under its original identity,
    it is stopped first (identity-verified). If the PID has been
    recycled, stop_proc raises PidRecycledError and we propagate — the
    caller decides whether to force-delete the stale entry without
    touching the OS process.
    """
    state = _load_state()
    pid_str = str(pid)
    info = state["procs"].get(pid_str)
    if not info:
        return False
    if _is_alive(pid, expected=info):
        stop_proc(pid, expected=info)
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
    """Reconcile the state file with observable process state.

    Two passes:

    1. For every tracked entry with status == "running", check liveness;
       if dead, flip status to "finished" and timestamp.
    2. For every tracked entry with status == "finished", check the
       finished timestamp against ZOMBIE_TTL; if older than the TTL,
       remove the entry entirely (it's a zombie from a past session).

    The TTL-based prune is what keeps `.aurum_procs.json` from accumulating
    entries from weeks-old engine runs. Previously _cleanup only changed
    status from running → finished and never deleted rows, leaving the
    Terminal > Processes screen permanently populated with dead entries
    that PID recycling could even flip back to alive=True.
    """
    state = _load_state()
    now = datetime.now()
    dead_keys: list[str] = []

    for pid_str, info in state["procs"].items():
        pid = int(pid_str)
        # Identity-aware check — a recycled PID reads as dead here too.
        if not _is_alive(pid, expected=info) and info.get("status") == "running":
            info["status"] = "finished"
            info["finished"] = now.isoformat()

        if info.get("status") == "finished":
            fin = info.get("finished")
            try:
                fin_dt = datetime.fromisoformat(fin) if fin else now
            except (TypeError, ValueError):
                fin_dt = now
            if now - fin_dt > ZOMBIE_TTL:
                dead_keys.append(pid_str)

    for k in dead_keys:
        del state["procs"][k]

    _save_state(state)


def purge_finished() -> int:
    """Force-remove every finished entry regardless of TTL.

    Intended for manual zombie cleanup and for the UI's "clear finished"
    button. Returns the number of entries removed.
    """
    state = _load_state()
    keys = [k for k, v in state["procs"].items() if v.get("status") != "running"]
    for k in keys:
        del state["procs"][k]
    _save_state(state)
    return len(keys)
