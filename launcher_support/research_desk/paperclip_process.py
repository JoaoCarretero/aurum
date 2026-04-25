"""Gerencia o processo local `npx paperclipai run` (porta 3100).

Escopo:
  - spawn/stop do server
  - capture de stdout/stderr pra buffer bounded (consumido pelo UI no
    Sprint 3.1 — live log streaming)
  - status machine: OFFLINE -> STARTING -> ONLINE (via health check
    externo confirmando), ou OFFLINE se falhar em spawnar

Nao depende de `core.ops.proc` — aquele gerencia engines Python
registrados em config/engines.py e nao se aplica aqui.

Windows specifics:
  - usa shutil.which pra achar `npx`/`npx.cmd` sem precisar shell=True
  - CREATE_NO_WINDOW esconde console popup
  - CREATE_NEW_PROCESS_GROUP permite enviar CTRL_BREAK_EVENT pra stop
    gracioso (Popen.terminate() em Win nao propaga pro grupo)
  - Fallback: se CTRL_BREAK_EVENT nao disponivel, usa terminate() + kill()

Nao-Windows: terminate() (SIGTERM) + fallback kill() (SIGKILL) ja funciona.
"""
from __future__ import annotations

import shutil
import signal
import subprocess
import sys
import threading
from collections import deque
from dataclasses import dataclass, field
from enum import Enum


class ServerStatus(Enum):
    OFFLINE = "offline"     # nao ha processo spawned por nos, health OFFLINE
    STARTING = "starting"   # spawn acabou de disparar, health nao confirmou
    ONLINE = "online"       # health OK (setado externamente via mark_online)
    STOPPING = "stopping"   # CTRL_BREAK_EVENT enviado, aguardando exit
    EXTERNAL = "external"   # health OK mas nos nao spawnamos — ignora stop


_STDOUT_BUFFER_MAX = 500  # linhas retidas pro live-log reader


@dataclass
class PaperclipProcess:
    """Owner de um processo `npx paperclipai run`.

    Uma instancia gerencia no maximo 1 processo vivo. Se ja existe um
    server externo (spawned na mao pelo user), nao tentamos stop — o
    status vira EXTERNAL e o botao de stop fica desabilitado.
    """

    cmd: tuple[str, ...] = ("paperclipai", "run")
    cwd: str | None = None
    status: ServerStatus = ServerStatus.OFFLINE
    _proc: subprocess.Popen | None = None
    _reader_thread: threading.Thread | None = None
    _stdout_buffer: deque[str] = field(default_factory=lambda: deque(maxlen=_STDOUT_BUFFER_MAX))
    _buffer_lock: threading.Lock = field(default_factory=threading.Lock)

    def is_owned(self) -> bool:
        """True se nos spawnamos o processo e ele ta vivo."""
        return self._proc is not None and self._proc.poll() is None

    def mark_online(self) -> None:
        """Chamado pelo poller quando health confirma ONLINE.

        Se nao temos proc owned, marca EXTERNAL (server foi spawnado
        fora — CLI, outro launcher, etc). Se owned, vira ONLINE.
        """
        if self.is_owned():
            self.status = ServerStatus.ONLINE
        else:
            self.status = ServerStatus.EXTERNAL

    def mark_offline(self) -> None:
        """Health falhou. Se processo owned morreu, limpa refs."""
        if self._proc is not None and self._proc.poll() is not None:
            # Morreu por si so
            self._proc = None
            self._reader_thread = None
        if not self.is_owned():
            self.status = ServerStatus.OFFLINE

    def can_start(self) -> bool:
        return self.status in (ServerStatus.OFFLINE,) and not self.is_owned()

    def can_stop(self) -> bool:
        return self.is_owned() and self.status in (
            ServerStatus.ONLINE,
            ServerStatus.STARTING,
        )

    # ── Start ─────────────────────────────────────────────────────

    def start(self) -> tuple[bool, str]:
        """Dispara subprocess.Popen. Retorna (ok, msg)."""
        if self.is_owned():
            return False, "paperclip ja rodando (owned)"
        if self.status == ServerStatus.EXTERNAL:
            return False, "server externo ja ativo — stop via CLI"

        argv = _resolve_argv(self.cmd)
        if argv is None:
            return False, f"comando nao encontrado no PATH: {self.cmd[0]}"

        try:
            self._proc = subprocess.Popen(
                argv,
                cwd=self.cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,  # line-buffered
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=_spawn_flags(),
            )
        except (OSError, ValueError) as exc:
            self._proc = None
            return False, f"spawn falhou: {exc}"

        self.status = ServerStatus.STARTING
        self._start_reader()
        return True, f"spawned pid={self._proc.pid}"

    def _start_reader(self) -> None:
        """Thread daemon que drena stdout line-by-line pro buffer."""
        if self._proc is None or self._proc.stdout is None:
            return
        proc = self._proc

        def _drain() -> None:
            assert proc.stdout is not None
            try:
                for line in proc.stdout:
                    with self._buffer_lock:
                        self._stdout_buffer.append(line.rstrip("\r\n"))
            except (OSError, ValueError):
                pass

        t = threading.Thread(target=_drain, daemon=True, name="paperclip-stdout")
        t.start()
        self._reader_thread = t

    # ── Stop ──────────────────────────────────────────────────────

    def stop(self, wait_sec: float = 5.0) -> tuple[bool, str]:
        """Stop gracioso. CTRL_BREAK no Win, SIGTERM em outros.
        Fallback kill() apos wait_sec se nao saiu."""
        if not self.is_owned():
            if self.status == ServerStatus.EXTERNAL:
                return False, "server externo — nao posso stop"
            return False, "sem processo owned"

        proc = self._proc
        assert proc is not None
        self.status = ServerStatus.STOPPING
        try:
            if sys.platform == "win32" and hasattr(signal, "CTRL_BREAK_EVENT"):
                # Requere CREATE_NEW_PROCESS_GROUP no spawn
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                proc.terminate()
        except (OSError, ValueError):
            # Fallback imediato
            try:
                proc.kill()
            except OSError:
                pass

        try:
            proc.wait(timeout=wait_sec)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
                proc.wait(timeout=2.0)
            except (OSError, subprocess.TimeoutExpired):
                pass

        self._proc = None
        self._reader_thread = None
        self.status = ServerStatus.OFFLINE
        return True, "stopped"

    # ── Log buffer access ─────────────────────────────────────────

    def recent_lines(self, n: int = 50) -> list[str]:
        """Snapshot das ultimas n linhas de stdout. Thread-safe."""
        with self._buffer_lock:
            return list(self._stdout_buffer)[-n:]


# ── Helpers ───────────────────────────────────────────────────────


def _resolve_argv(cmd: tuple[str, ...]) -> list[str] | None:
    """Resolve primeira entry via shutil.which — handle npx.cmd no Win.

    Se a primeira entry nao existe no PATH, retorna None (caller trata).
    Demais args ficam inalterados.
    """
    if not cmd:
        return None
    exe = shutil.which(cmd[0])
    if exe is None:
        return None
    return [exe, *cmd[1:]]


def _spawn_flags() -> int:
    """CREATE_NO_WINDOW + CREATE_NEW_PROCESS_GROUP no Windows, 0 em outros."""
    if sys.platform != "win32":
        return 0
    # 0x08000000 | 0x00000200
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
        subprocess, "CREATE_NEW_PROCESS_GROUP", 0,
    )


def default_paperclip_cmd() -> tuple[str, ...]:
    """Comando canonico pra subir o server.

    Prefere o binario `paperclipai` se o user rodou npm install -g; senao
    cai pro invocation via npx. `npx paperclipai run` e a forma
    documentada em CLAUDE.md / spec do Research Desk.
    """
    if shutil.which("paperclipai"):
        return ("paperclipai", "run")
    return ("npx", "paperclipai", "run")
