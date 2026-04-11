"""Regression tests for core/proc.py — Fase 1 / D5 identity verification.

These tests do NOT use pytest (the aurum repo doesn't ship with it as a
hard dependency — smoke_test.py is the primary regression harness). They
run as a standalone Python script:

    python tests/test_proc_identity.py

Exit code 0 on success, 1 on any failure. Output matches the smoke test
style so the CI line can stay simple.
"""
from __future__ import annotations

import os
import sys
import time
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.proc import (
    _is_alive,
    _win_get_creation_time,
    _win_get_image_name,
    PidRecycledError,
    stop_proc,
)


# ── Assertion helpers ─────────────────────────────────────────────────

_passes = 0
_fails: list[tuple[str, str]] = []


def _check(label: str, cond: bool, detail: str = "") -> None:
    global _passes
    if cond:
        _passes += 1
        print(f"  OK    {label}")
    else:
        _fails.append((label, detail))
        print(f"  FAIL  {label}    {detail}")


def _spawn_sleeper(seconds: float = 5.0) -> subprocess.Popen:
    """Spawn a detached python subprocess that sleeps for N seconds.

    Used as a controlled target: we know its creation_time, we know its
    image_name (python.exe on Windows), and we can kill it deterministically.
    """
    cmd = [sys.executable, "-c", f"import time; time.sleep({seconds})"]
    return subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP
                       if sys.platform == "win32" else 0),
    )


# ── Tests ─────────────────────────────────────────────────────────────

def test_windows_identity_helpers():
    if sys.platform != "win32":
        print("  SKIP  windows helpers (non-win32)")
        return
    proc = _spawn_sleeper(3.0)
    try:
        time.sleep(0.2)  # give Windows a moment to populate kernel structs
        ct = _win_get_creation_time(proc.pid)
        img = _win_get_image_name(proc.pid)
        _check("creation_time is int", isinstance(ct, int) and ct > 0,
               f"got {type(ct).__name__}={ct}")
        _check("creation_time is large", ct is not None and ct > 10**17,
               f"ct={ct} — FILETIME should be ≳ 10^17")
        _check("image_name is python*", img in ("python.exe", "pythonw.exe"),
               f"got image_name={img!r}")
    finally:
        proc.terminate()
        try: proc.wait(timeout=2)
        except subprocess.TimeoutExpired: proc.kill()


def test_is_alive_liveness():
    proc = _spawn_sleeper(3.0)
    try:
        time.sleep(0.2)
        _check("liveness-only True for running proc",
               _is_alive(proc.pid) is True)
        entry = _build_entry(proc.pid)
        _check("identity-aware True for running proc",
               _is_alive(proc.pid, expected=entry) is True)
    finally:
        proc.terminate()
        try: proc.wait(timeout=2)
        except subprocess.TimeoutExpired: proc.kill()

    # After termination, both forms must return False
    time.sleep(0.5)
    _check("liveness-only False after terminate",
           _is_alive(proc.pid) is False)
    _check("identity-aware False after terminate",
           _is_alive(proc.pid, expected=_build_entry(proc.pid, stale=True)) is False)


def test_identity_detects_mismatch():
    """Simulate PID recycling by mutating the expected creation_time.

    We don't have to wait for Windows to actually recycle a PID — we can
    prove the check rejects a mismatch by lying about the expected value.
    """
    if sys.platform != "win32":
        print("  SKIP  identity mismatch (non-win32)")
        return
    proc = _spawn_sleeper(3.0)
    try:
        time.sleep(0.2)
        real_ct = _win_get_creation_time(proc.pid)
        assert real_ct is not None
        # Correct identity: should pass
        good = {"creation_time": real_ct, "image_name": "python.exe"}
        _check("good identity passes", _is_alive(proc.pid, expected=good))
        # Wrong creation_time: should fail even though liveness is True
        bad_ct = {"creation_time": real_ct + 1, "image_name": "python.exe"}
        _check("wrong creation_time fails",
               _is_alive(proc.pid, expected=bad_ct) is False,
               f"bad_ct={bad_ct['creation_time']}")
        # Wrong image_name: should fail
        bad_img = {"creation_time": real_ct, "image_name": "chrome.exe"}
        _check("wrong image_name fails",
               _is_alive(proc.pid, expected=bad_img) is False,
               "expected image_name check to reject chrome.exe")
    finally:
        proc.terminate()
        try: proc.wait(timeout=2)
        except subprocess.TimeoutExpired: proc.kill()


def test_stop_proc_raises_on_pid_mismatch():
    """stop_proc must refuse to taskkill a PID whose identity doesn't
    match the expected entry. We force a mismatch by passing a fabricated
    expected dict — the live process has one creation_time, the expected
    dict has another, and stop_proc should raise PidRecycledError before
    reaching taskkill."""
    if sys.platform != "win32":
        print("  SKIP  stop_proc mismatch (non-win32)")
        return
    proc = _spawn_sleeper(5.0)
    try:
        time.sleep(0.2)
        fake_expected = {
            "engine": "newton",
            "pid": proc.pid,
            "creation_time": 1,  # nonsense value — guaranteed mismatch
            "image_name": "python.exe",
        }
        raised = False
        try:
            stop_proc(proc.pid, expected=fake_expected)
        except PidRecycledError:
            raised = True
        _check("stop_proc raises PidRecycledError on mismatch", raised,
               "expected a refusal, got a silent taskkill or False return")
        # The target process must still be alive — we refused to kill it
        time.sleep(0.2)
        _check("target process untouched after refusal",
               _is_alive(proc.pid) is True,
               "stop_proc should not have touched the target")
    finally:
        proc.terminate()
        try: proc.wait(timeout=2)
        except subprocess.TimeoutExpired: proc.kill()


def test_stop_proc_kills_legit_target():
    """Sanity: when identity matches, stop_proc actually kills."""
    proc = _spawn_sleeper(30.0)  # long enough that it won't exit on its own
    try:
        time.sleep(0.2)
        entry = _build_entry(proc.pid)
        result = stop_proc(proc.pid, expected=entry)
        _check("stop_proc returns True on legit kill", result is True)
        time.sleep(0.3)
        _check("target dead after stop_proc",
               _is_alive(proc.pid) is False)
    finally:
        # Cleanup in case stop_proc didn't actually work
        if proc.poll() is None:
            proc.terminate()
            try: proc.wait(timeout=2)
            except subprocess.TimeoutExpired: proc.kill()


# ── Helper: build an entry dict matching a live PID ───────────────────

def _build_entry(pid: int, stale: bool = False) -> dict:
    """Snapshot the current identity of ``pid`` into an entry dict.

    ``stale=True`` means we won't re-read the identity — the caller knows
    the proc is already dead and just needs a placeholder with arbitrary
    fingerprint values.
    """
    if stale:
        return {"creation_time": 1, "image_name": "python.exe"}
    if sys.platform == "win32":
        return {
            "creation_time": _win_get_creation_time(pid),
            "image_name":    _win_get_image_name(pid),
        }
    return {}


# ── Runner ────────────────────────────────────────────────────────────

def main() -> int:
    print()
    print("[ windows identity helpers ]")
    test_windows_identity_helpers()

    print()
    print("[ _is_alive liveness ]")
    test_is_alive_liveness()

    print()
    print("[ identity mismatch detection ]")
    test_identity_detects_mismatch()

    print()
    print("[ stop_proc refuses pid recycling ]")
    test_stop_proc_raises_on_pid_mismatch()

    print()
    print("[ stop_proc kills legit targets ]")
    test_stop_proc_kills_legit_target()

    print()
    print("=" * 60)
    total = _passes + len(_fails)
    print(f"  {_passes}/{total} passed  ({len(_fails)} failures)")
    print("=" * 60)
    if _fails:
        print()
        print("FAILURES:")
        for label, detail in _fails:
            print(f"  - {label}    {detail}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
