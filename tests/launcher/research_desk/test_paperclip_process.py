"""Tests do PaperclipProcess — status machine, resolve, stop flow.

Subprocess e mockada: nao gastamos tempo com npx real.
"""
from __future__ import annotations

import subprocess
import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from launcher_support.research_desk.paperclip_process import (
    PaperclipProcess,
    ServerStatus,
    _resolve_argv,
    default_paperclip_cmd,
)


def test_resolve_argv_returns_none_when_cmd_missing() -> None:
    with patch("shutil.which", return_value=None):
        assert _resolve_argv(("nope-cmd", "run")) is None


def test_resolve_argv_injects_resolved_exe() -> None:
    with patch("shutil.which", return_value="/usr/bin/fake"):
        argv = _resolve_argv(("fake", "run", "--x"))
    assert argv == ["/usr/bin/fake", "run", "--x"]


def test_resolve_argv_handles_empty() -> None:
    assert _resolve_argv(()) is None


def test_default_cmd_prefers_paperclipai_when_available() -> None:
    with patch("shutil.which", side_effect=lambda name: "/x/paperclipai" if name == "paperclipai" else None):
        assert default_paperclip_cmd() == ("paperclipai", "run")


def test_default_cmd_falls_back_to_npx() -> None:
    with patch("shutil.which", return_value=None):
        assert default_paperclip_cmd() == ("npx", "paperclipai", "run")


def test_status_starts_offline() -> None:
    p = PaperclipProcess()
    assert p.status == ServerStatus.OFFLINE
    assert p.can_start() is True
    assert p.can_stop() is False
    assert p.is_owned() is False


def test_start_fails_when_cmd_unresolvable() -> None:
    p = PaperclipProcess(cmd=("inexistente-binario-12345",))
    with patch("shutil.which", return_value=None):
        ok, msg = p.start()
    assert ok is False
    assert "PATH" in msg or "nao encontrado" in msg
    assert p.status == ServerStatus.OFFLINE


def test_start_spawns_and_transitions_to_starting() -> None:
    fake_proc = _fake_popen(alive=True)
    with patch("shutil.which", return_value="/x/fake"), \
         patch("subprocess.Popen", return_value=fake_proc) as popen_mock:
        p = PaperclipProcess(cmd=("fake", "run"))
        ok, msg = p.start()

    assert ok is True
    assert "pid=" in msg
    assert p.status == ServerStatus.STARTING
    assert p.is_owned() is True
    # Verify spawn flags eram passados
    _, kwargs = popen_mock.call_args
    if sys.platform == "win32":
        assert kwargs["creationflags"] != 0
    assert kwargs["stdout"] == subprocess.PIPE
    assert kwargs["stderr"] == subprocess.STDOUT


def test_start_rejects_when_already_owned() -> None:
    p = PaperclipProcess()
    p._proc = _fake_popen(alive=True)  # noqa: SLF001
    ok, msg = p.start()
    assert ok is False
    assert "owned" in msg or "rodando" in msg


def test_mark_online_transitions() -> None:
    p = PaperclipProcess()
    # Sem proc owned -> EXTERNAL
    p.mark_online()
    assert p.status == ServerStatus.EXTERNAL
    # Com proc owned -> ONLINE
    p2 = PaperclipProcess()
    p2._proc = _fake_popen(alive=True)  # noqa: SLF001
    p2.mark_online()
    assert p2.status == ServerStatus.ONLINE


def test_mark_offline_clears_dead_proc() -> None:
    p = PaperclipProcess()
    dead = _fake_popen(alive=False)
    p._proc = dead  # noqa: SLF001
    p.status = ServerStatus.ONLINE
    p.mark_offline()
    assert p._proc is None  # noqa: SLF001
    assert p.status == ServerStatus.OFFLINE


def test_stop_refuses_when_external() -> None:
    p = PaperclipProcess()
    p.status = ServerStatus.EXTERNAL
    ok, msg = p.stop()
    assert ok is False
    assert "externo" in msg


def test_stop_terminates_owned_proc() -> None:
    fake = _fake_popen(alive=True)
    p = PaperclipProcess()
    p._proc = fake  # noqa: SLF001
    p.status = ServerStatus.ONLINE

    ok, _msg = p.stop(wait_sec=0.1)
    assert ok is True
    assert p.status == ServerStatus.OFFLINE
    assert p._proc is None  # noqa: SLF001
    # Enviou sinal de parada
    assert fake.send_signal.called or fake.terminate.called
    assert fake.wait.called


def test_stop_kills_after_timeout() -> None:
    fake = _fake_popen(alive=True)
    fake.wait.side_effect = [subprocess.TimeoutExpired(cmd="x", timeout=0.1), None]
    p = PaperclipProcess()
    p._proc = fake  # noqa: SLF001
    p.status = ServerStatus.ONLINE
    ok, _ = p.stop(wait_sec=0.1)
    assert ok is True
    assert fake.kill.called


def test_recent_lines_thread_safe_snapshot() -> None:
    p = PaperclipProcess()
    for i in range(10):
        p._stdout_buffer.append(f"line{i}")  # noqa: SLF001
    lines = p.recent_lines(5)
    assert lines == [f"line{i}" for i in range(5, 10)]


def test_buffer_is_bounded() -> None:
    p = PaperclipProcess()
    for i in range(1000):
        p._stdout_buffer.append(f"line{i}")  # noqa: SLF001
    assert len(p._stdout_buffer) <= 500  # noqa: SLF001


# ── Helpers ───────────────────────────────────────────────────────


def _fake_popen(alive: bool) -> Any:
    mock = MagicMock(spec=subprocess.Popen)
    mock.pid = 12345
    mock.poll.return_value = None if alive else 0
    mock.stdout = None
    return mock
