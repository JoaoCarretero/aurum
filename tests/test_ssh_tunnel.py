"""Tests for launcher_support.ssh_tunnel.TunnelManager."""
from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from launcher_support.ssh_tunnel import (
    TunnelConfig,
    TunnelManager,
    TunnelStatus,
    _classify_stderr,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_fake_proc(
    poll_values: list,
    stderr: bytes = b"",
    stdout: bytes = b"",
) -> MagicMock:
    """Fake Popen-like object. poll_values is consumed in order; last repeats."""
    # Don't spec on subprocess.Popen — tests patch it, which would break spec.
    proc = MagicMock()
    seq = list(poll_values)

    def _poll() -> object:
        if len(seq) > 1:
            return seq.pop(0)
        return seq[0] if seq else None

    proc.poll.side_effect = _poll
    proc.returncode = None if poll_values and poll_values[-1] is None else poll_values[-1] if poll_values else None

    # stderr / stdout streams that behave like binary file objects
    stderr_mock = MagicMock()
    stderr_mock.read.return_value = stderr
    proc.stderr = stderr_mock

    stdout_mock = MagicMock()
    stdout_mock.read.return_value = stdout
    proc.stdout = stdout_mock

    proc.terminate = MagicMock()
    proc.kill = MagicMock()
    proc.wait = MagicMock(return_value=poll_values[-1] if poll_values else 0)
    return proc


def _wait_for_status(
    manager: TunnelManager,
    target: TunnelStatus | set,
    timeout: float = 2.0,
) -> bool:
    """Poll until manager.status matches target or timeout expires."""
    targets = target if isinstance(target, set) else {target}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if manager.status in targets:
            return True
        time.sleep(0.02)
    return False


def _default_cfg() -> TunnelConfig:
    return TunnelConfig(
        host="37.60.254.151",
        user="root",
        ssh_port=22,
        local_port=8787,
        remote_host="localhost",
        remote_port=8787,
    )


# ---------------------------------------------------------------------------
# 1. DISABLED path
# ---------------------------------------------------------------------------
def test_none_config_stays_disabled(tmp_path: Path) -> None:
    manager = TunnelManager(None, log_dir=tmp_path)
    assert manager.status is TunnelStatus.DISABLED
    manager.start()  # no-op
    assert manager.status is TunnelStatus.DISABLED
    manager.stop()  # no-op
    assert manager.status is TunnelStatus.DISABLED


# ---------------------------------------------------------------------------
# 2. Start → UP → stop
# ---------------------------------------------------------------------------
def test_start_sets_status_up(tmp_path: Path) -> None:
    fake_proc = _make_fake_proc([None])  # stays alive
    with patch("launcher_support.ssh_tunnel.subprocess.Popen", return_value=fake_proc):
        manager = TunnelManager(
            _default_cfg(),
            log_dir=tmp_path,
            watchdog_interval_sec=0.02,
            reconnect_backoff_sec=0.05,
        )
        # Reduce the internal alive threshold via monkeypatching is messy;
        # instead use a small enough watchdog interval and wait.
        manager.start()
        # Wait for watchdog to detect alive + promote to UP (needs >=2s of
        # alive time per default threshold). To keep test fast, monkeypatch
        # the module-level threshold.
        import launcher_support.ssh_tunnel as mod
        mod._ALIVE_THRESHOLD_SEC = 0.0  # type: ignore[attr-defined]
        try:
            assert _wait_for_status(manager, TunnelStatus.UP, timeout=3.0), (
                f"expected UP, got {manager.status}"
            )
            manager.stop()
            # After stop, we should no longer be UP; final state is STOPPING or IDLE-like.
            # We accept anything except UP / RECONNECTING after stop.
            assert manager.status is not TunnelStatus.UP
        finally:
            mod._ALIVE_THRESHOLD_SEC = 2.0  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# 3. Command shape
# ---------------------------------------------------------------------------
def test_ssh_command_shape(tmp_path: Path) -> None:
    cfg = _default_cfg()
    manager = TunnelManager(cfg, log_dir=tmp_path)
    cmd = manager._build_cmd()
    assert cmd[0] == "ssh"
    assert "-N" in cmd
    # Required -o flags
    opts = [cmd[i + 1] for i, tok in enumerate(cmd) if tok == "-o"]
    assert "BatchMode=yes" in opts
    assert "ExitOnForwardFailure=yes" in opts
    assert "ServerAliveInterval=30" in opts
    assert "ServerAliveCountMax=3" in opts
    assert "StrictHostKeyChecking=accept-new" in opts
    assert "ConnectTimeout=10" in opts
    # -L forwarding spec
    assert "-L" in cmd
    lidx = cmd.index("-L")
    assert cmd[lidx + 1] == "8787:localhost:8787"
    # user@host at the tail
    assert cmd[-1] == "root@37.60.254.151"
    # No -i when key_path is None
    assert "-i" not in cmd

    cfg_with_key = TunnelConfig(host="h", key_path="/tmp/id_ed25519")
    m2 = TunnelManager(cfg_with_key, log_dir=tmp_path)
    cmd2 = m2._build_cmd()
    assert "-i" in cmd2
    assert cmd2[cmd2.index("-i") + 1] == "/tmp/id_ed25519"


# ---------------------------------------------------------------------------
# 4. Fast-death (rc=255) → RECONNECTING
# ---------------------------------------------------------------------------
def test_spawn_failure_transitions_to_reconnecting(tmp_path: Path) -> None:
    # Always-dead subprocess: poll returns 255 immediately
    dead = _make_fake_proc([255], stderr=b"Permission denied (publickey).\n")
    with patch("launcher_support.ssh_tunnel.subprocess.Popen", return_value=dead):
        manager = TunnelManager(
            _default_cfg(),
            log_dir=tmp_path,
            watchdog_interval_sec=0.02,
            reconnect_backoff_sec=1.0,  # long enough to observe RECONNECTING state
            offline_after_failures=5,
        )
        manager.start()
        assert _wait_for_status(manager, TunnelStatus.RECONNECTING, timeout=2.0), (
            f"expected RECONNECTING, got {manager.status}"
        )
        assert manager.last_error is not None
        assert "auth" in manager.last_error.lower()
        manager.stop()


# ---------------------------------------------------------------------------
# 5. Stderr classification
# ---------------------------------------------------------------------------
def test_stderr_error_classification() -> None:
    # auth
    msg = _classify_stderr("ssh: Permission denied (publickey).")
    assert msg is not None and "auth" in msg.lower()
    msg2 = _classify_stderr("authentication failed")
    assert msg2 is not None and "auth" in msg2.lower()
    # dns
    msg3 = _classify_stderr("ssh: Could not resolve hostname vmi3200601: Name or service not known")
    assert msg3 is not None and "resolv" in msg3.lower()
    # refused
    msg4 = _classify_stderr("ssh: connect to host x port 22: Connection refused")
    assert msg4 is not None and "refused" in msg4.lower()
    # timeout
    msg5 = _classify_stderr("ssh: connect to host x port 22: Connection timed out")
    assert msg5 is not None and "timeout" in msg5.lower()
    # empty
    assert _classify_stderr("") is None
    assert _classify_stderr(None) is None  # type: ignore[arg-type]
    # fallback — unknown message, last nonempty line truncated
    msg6 = _classify_stderr("random\nweird line here\n")
    assert msg6 == "weird line here"
    # truncation
    long_line = "x" * 500
    msg7 = _classify_stderr(long_line)
    assert msg7 is not None and len(msg7) <= 120


# ---------------------------------------------------------------------------
# 6. Stop idempotency
# ---------------------------------------------------------------------------
def test_stop_is_idempotent(tmp_path: Path) -> None:
    # DISABLED path
    m1 = TunnelManager(None, log_dir=tmp_path)
    m1.stop()
    m1.stop()  # twice

    # Never-started configured manager
    m2 = TunnelManager(_default_cfg(), log_dir=tmp_path)
    m2.stop()
    m2.stop()

    # Started, then stopped multiple times
    fake_proc = _make_fake_proc([None])
    with patch("launcher_support.ssh_tunnel.subprocess.Popen", return_value=fake_proc):
        m3 = TunnelManager(
            _default_cfg(),
            log_dir=tmp_path,
            watchdog_interval_sec=0.02,
            reconnect_backoff_sec=0.05,
        )
        m3.start()
        m3.stop()
        m3.stop()
        m3.stop()  # triply idempotent


# ---------------------------------------------------------------------------
# 7. Watchdog respawns after death
# ---------------------------------------------------------------------------
def test_watchdog_respawns_dead_subprocess(tmp_path: Path) -> None:
    # First call: instantly-dead proc (rc=1). Second call: alive proc.
    dead = _make_fake_proc([1], stderr=b"ssh: something went wrong\n")
    alive = _make_fake_proc([None])

    call_count = {"n": 0}

    def fake_popen(*args, **kwargs):
        call_count["n"] += 1
        return dead if call_count["n"] == 1 else alive

    import launcher_support.ssh_tunnel as mod
    original_threshold = mod._ALIVE_THRESHOLD_SEC
    mod._ALIVE_THRESHOLD_SEC = 0.0  # type: ignore[attr-defined]
    try:
        with patch(
            "launcher_support.ssh_tunnel.subprocess.Popen", side_effect=fake_popen
        ):
            manager = TunnelManager(
                _default_cfg(),
                log_dir=tmp_path,
                watchdog_interval_sec=0.02,
                reconnect_backoff_sec=0.05,
                offline_after_failures=5,
            )
            manager.start()
            # Should go through RECONNECTING then UP
            assert _wait_for_status(manager, TunnelStatus.UP, timeout=3.0), (
                f"expected UP, got {manager.status}; call_count={call_count['n']}"
            )
            assert call_count["n"] >= 2
            manager.stop()
    finally:
        mod._ALIVE_THRESHOLD_SEC = original_threshold  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# 8. OFFLINE after repeated failures
# ---------------------------------------------------------------------------
def test_offline_after_repeated_failures(tmp_path: Path) -> None:
    # Always-dead proc; offline_after_failures=2 → second death triggers OFFLINE
    def fresh_dead(*args, **kwargs):
        return _make_fake_proc([255], stderr=b"Permission denied\n")

    with patch(
        "launcher_support.ssh_tunnel.subprocess.Popen", side_effect=fresh_dead
    ):
        manager = TunnelManager(
            _default_cfg(),
            log_dir=tmp_path,
            watchdog_interval_sec=0.02,
            reconnect_backoff_sec=0.05,
            offline_after_failures=2,
            offline_backoff_sec=0.05,
        )
        manager.start()
        assert _wait_for_status(manager, TunnelStatus.OFFLINE, timeout=3.0), (
            f"expected OFFLINE, got {manager.status}"
        )
        # Watchdog should still keep running (alive)
        assert manager._watchdog_thread is not None
        assert manager._watchdog_thread.is_alive()
        manager.stop()


# ---------------------------------------------------------------------------
# 9. Log file creation
# ---------------------------------------------------------------------------
def test_log_file_is_created(tmp_path: Path) -> None:
    fake_proc = _make_fake_proc([None])
    with patch("launcher_support.ssh_tunnel.subprocess.Popen", return_value=fake_proc):
        manager = TunnelManager(
            _default_cfg(),
            log_dir=tmp_path,
            watchdog_interval_sec=0.02,
            reconnect_backoff_sec=0.05,
        )
        manager.start()
        # Give the lifecycle a tick to create the log file
        time.sleep(0.1)
        assert (tmp_path / "tunnel.log").exists()
        manager.stop()


# ---------------------------------------------------------------------------
# Extra: log rotation when existing >1MB
# ---------------------------------------------------------------------------
def test_log_rotation_on_start(tmp_path: Path) -> None:
    """If tunnel.log exists and >1MB, it's rotated to tunnel.log.1."""
    log_path = tmp_path / "tunnel.log"
    log_path.write_bytes(b"x" * (1024 * 1024 + 10))  # just over 1MB
    fake_proc = _make_fake_proc([None])
    with patch("launcher_support.ssh_tunnel.subprocess.Popen", return_value=fake_proc):
        manager = TunnelManager(
            _default_cfg(),
            log_dir=tmp_path,
            watchdog_interval_sec=0.02,
        )
        manager.start()
        try:
            assert (tmp_path / "tunnel.log.1").exists()
            # New log file should be fresh (small)
            assert (tmp_path / "tunnel.log").stat().st_size < 1024 * 1024
        finally:
            manager.stop()
