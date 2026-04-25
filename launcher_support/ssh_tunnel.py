"""SSH tunnel manager para o Aurum launcher.

Mantém `ssh -N -L <local>:<remote_host>:<remote_port> user@host` vivo
num subprocess supervisionado por watchdog thread. Reexecuta se o
subprocess morre; classifica stderr em categorias conhecidas
(auth/dns/refused/timeout); expõe status pra UI poll.

BatchMode=yes é **crítico**: sem isso, uma key ausente faz o ssh pedir
senha interativamente, e o subprocess fica pendurado pra sempre dentro
do launcher. Com BatchMode, ssh sai com código nonzero imediatamente
em falha de auth e o watchdog trata como "morreu, reconecta".

Thread-safe para start/stop. Status é lido por polling (UI thread).
"""
from __future__ import annotations

import enum
import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path


logger = logging.getLogger(__name__)


class TunnelStatus(enum.Enum):
    DISABLED = "disabled"            # no config → nothing to do
    IDLE = "idle"                    # configured, not started
    STARTING = "starting"            # spawn in progress
    UP = "up"                        # subprocess alive
    RECONNECTING = "reconnecting"    # last spawn died, backing off
    STOPPING = "stopping"            # stop() called, draining
    OFFLINE = "offline"              # spawned but died repeatedly


@dataclass(frozen=True)
class TunnelConfig:
    host: str                        # e.g. "37.60.254.151" or "vmi3200601"
    user: str = "root"
    ssh_port: int = 22
    local_port: int = 8787
    remote_host: str = "localhost"
    remote_port: int = 8787
    key_path: str | None = None      # optional -i /path/to/key
    known_hosts_path: str | None = None


_MAX_LOG_BYTES = 1 * 1024 * 1024  # 1MB rotate threshold
_ALIVE_THRESHOLD_SEC = 2.0         # needs to stay alive this long to count as UP
_FAST_DEATH_WINDOW_SEC = 30.0      # deaths within this window count as "fast death"
_STDERR_TRUNC = 120

# Windows: suppress cmd.exe flash when spawning netstat/tasklist/taskkill
# from the reconciliation preflight that runs at launcher startup.
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def _reap_orphan_tunnel_on_port(local_port: int) -> int:
    """Kill orphan ssh processes listening on local_port.

    Runs as preflight before spawning a new tunnel. Only targets ``ssh.exe``/
    ``ssh`` — a cockpit API or unrelated process on the port is left alone
    (and the caller will fail loudly). Returns number of processes killed.
    No-op if the port is free.
    """
    import socket
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(0.3)
    try:
        probe.bind(("127.0.0.1", int(local_port)))
        probe.close()
        return 0
    except OSError:
        probe.close()

    if os.name == "nt":
        return _reap_tunnel_windows(int(local_port))
    return _reap_tunnel_posix(int(local_port))


def _reap_tunnel_windows(local_port: int) -> int:
    needle = f":{local_port}"
    try:
        out = subprocess.check_output(
            ["netstat", "-ano"], timeout=5,
            stderr=subprocess.DEVNULL,
            creationflags=_NO_WINDOW,
        ).decode("latin-1", errors="replace")
    except Exception:
        return 0
    pids: set[int] = set()
    for line in out.splitlines():
        if needle not in line or "LISTENING" not in line:
            continue
        parts = line.split()
        if parts and parts[-1].isdigit():
            pids.add(int(parts[-1]))
    killed = 0
    netstat_pid_dead = False
    for pid in pids:
        try:
            img = subprocess.check_output(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                timeout=3, stderr=subprocess.DEVNULL,
                creationflags=_NO_WINDOW,
            ).decode("latin-1", errors="replace")
            # tasklist returns "INFO: No tasks..." when PID is gone. This
            # happens with `ssh -f` (the parent forks + exits, leaving the
            # netstat owner-PID dangling while the actual listener child
            # owns the socket via fd inheritance under a different PID).
            if "ssh.exe" not in img.lower():
                if "no tasks" in img.lower() or "nenhuma tarefa" in img.lower():
                    netstat_pid_dead = True
                continue
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                timeout=3, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=_NO_WINDOW,
            )
            killed += 1
        except Exception:
            continue
    # Fallback: netstat reported a PID that doesn't exist (typical of
    # `ssh -f` orphans on Windows where the daemonised parent PID survives
    # in the kernel's socket-owner table). Sweep every running ssh.exe —
    # any that's binding our port silently will release it on kill, the
    # OS reclaims the socket, and start() can bind cleanly. Other ssh.exe
    # instances unrelated to the cockpit still die: cost of recovery from
    # a fairly rare state, accepted because the launcher's port=8787 is
    # known and any ssh.exe holding it is presumed stale.
    if killed == 0 and netstat_pid_dead:
        try:
            ssh_list = subprocess.check_output(
                ["tasklist", "/FI", "IMAGENAME eq ssh.exe", "/FO", "CSV", "/NH"],
                timeout=3, stderr=subprocess.DEVNULL,
                creationflags=_NO_WINDOW,
            ).decode("latin-1", errors="replace")
            for line in ssh_list.splitlines():
                # CSV row: "ssh.exe","17656","Console","10","10,596 K"
                parts = [p.strip().strip('"') for p in line.split(",")]
                if len(parts) >= 2 and parts[1].isdigit():
                    try:
                        subprocess.run(
                            ["taskkill", "/F", "/PID", parts[1]],
                            timeout=3,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            creationflags=_NO_WINDOW,
                        )
                        killed += 1
                    except Exception:
                        continue
        except Exception:
            pass
    return killed


def _reap_tunnel_posix(local_port: int) -> int:
    killed = 0
    try:
        out = subprocess.check_output(
            ["lsof", "-iTCP", f"-sTCP:LISTEN", "-P", "-n"],
            timeout=3, stderr=subprocess.DEVNULL,
        ).decode("utf-8", errors="replace")
    except Exception:
        return 0
    needle = f":{local_port}"
    for line in out.splitlines():
        if needle not in line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        name, pid_s = parts[0], parts[1]
        if not name.startswith("ssh") or not pid_s.isdigit():
            continue
        try:
            import signal as _sig
            os.kill(int(pid_s), _sig.SIGKILL)
            killed += 1
        except Exception:
            continue
    return killed


def _classify_stderr(text: str) -> str | None:
    """Return human-readable classification of stderr, or None if empty.

    Scans for known SSH error patterns. Falls back to last nonempty line.
    """
    if not text:
        return None
    lower = text.lower()
    if "permission denied" in lower or "authentication failed" in lower:
        return "ssh auth failed (missing or wrong key)"
    if "could not resolve hostname" in lower:
        return "host not resolvable"
    if "connection refused" in lower:
        return "VPS refused connection"
    if "connection timed out" in lower or "operation timed out" in lower:
        return "VPS unreachable (timeout)"
    if "host key verification failed" in lower:
        return "ssh host key verification failed"
    if "remote host identification has changed" in lower:
        return "ssh host key mismatch"
    # Fallback: last nonempty line, truncated
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return None
    last = lines[-1]
    if len(last) > _STDERR_TRUNC:
        last = last[: _STDERR_TRUNC - 1] + "…"
    return last


class TunnelManager:
    """Keeps `ssh -N -L local_port:remote_host:remote_port user@host` alive.

    Lifecycle (thread-safe for start/stop; status polled by UI thread)::

        manager = TunnelManager(cfg, log_dir=Path("data/.cockpit_cache"))
        manager.start()          # spawns subprocess + watchdog thread
        ...  # UI polls manager.status periodically
        manager.stop()           # kills subprocess, joins watchdog

    If ``cfg is None``, status stays DISABLED and all calls are no-ops.

    The watchdog daemon thread re-spawns the ssh subprocess if it dies.
    Backoff is ``reconnect_backoff_sec`` between retries. After
    ``offline_after_failures`` consecutive failures-to-stay-up (each
    within 30s of spawn), status becomes OFFLINE and the watchdog
    continues to retry with longer ``offline_backoff_sec`` backoff.
    Never gives up entirely — user can reconnect VPS and tunnel recovers.
    """

    def __init__(
        self,
        config: TunnelConfig | None,
        log_dir: Path,
        watchdog_interval_sec: float = 2.0,
        reconnect_backoff_sec: float = 5.0,
        offline_after_failures: int = 5,
        offline_backoff_sec: float = 60.0,
    ) -> None:
        self._config = config
        self._log_dir = Path(log_dir)
        self._watchdog_interval = float(watchdog_interval_sec)
        self._reconnect_backoff = float(reconnect_backoff_sec)
        self._offline_after_failures = int(offline_after_failures)
        self._offline_backoff = float(offline_backoff_sec)

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._watchdog_thread: threading.Thread | None = None
        self._proc: subprocess.Popen[bytes] | None = None
        self._log_file = None  # open handle (binary append mode)

        self._status: TunnelStatus = (
            TunnelStatus.DISABLED if config is None else TunnelStatus.IDLE
        )
        self._last_error: str | None = None
        self._fast_death_count: int = 0
        self._started: bool = False  # start() was called (idempotency flag)

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------
    @property
    def status(self) -> TunnelStatus:
        return self._status

    @property
    def last_error(self) -> str | None:
        return self._last_error

    # ------------------------------------------------------------------
    # Command construction (exposed for tests)
    # ------------------------------------------------------------------
    def _build_cmd(self) -> list[str]:
        """Build the ssh command line. Assumes config is not None."""
        assert self._config is not None, "_build_cmd called with None config"
        cfg = self._config
        # `-F NUL` (Windows) / `-F /dev/null` (POSIX): ignora ~/.ssh/config.
        # Sem isso, um config file world-readable em
        # `~/.ssh/config` faz ssh recusar com "Bad permissions" e a tunnel
        # nunca sobe — bug surfaced 2026-04-25 quando um config criado
        # via tooling com perms herdadas (CodexSandboxUsers no grupo)
        # bloqueou o tunnel da launcher por horas. Esta flag isola o
        # tunnel da launcher de qualquer ~/.ssh/config do operador, bom
        # ou mau — todas as opcoes vem do _build_cmd via -o, autonomo.
        null_path = "NUL" if os.name == "nt" else "/dev/null"
        cmd: list[str] = [
            "ssh",
            "-F", null_path,
            "-N",
            "-o", "ExitOnForwardFailure=yes",
            "-o", "ServerAliveInterval=30",
            "-o", "ServerAliveCountMax=3",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=10",
            "-p", str(cfg.ssh_port),
        ]
        if cfg.known_hosts_path:
            cmd.extend(["-o", f"UserKnownHostsFile={cfg.known_hosts_path}"])
        if cfg.key_path:
            cmd.extend(["-i", cfg.key_path])
        cmd.extend([
            "-L", f"{cfg.local_port}:{cfg.remote_host}:{cfg.remote_port}",
            f"{cfg.user}@{cfg.host}",
        ])
        return cmd

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        """Idempotent: already-started is a no-op. DISABLED is a no-op."""
        with self._lock:
            if self._config is None:
                # DISABLED — nothing to do
                return
            if self._started:
                return
            self._started = True
            self._stop_event.clear()
            # Reap any orphan ssh tunnel parked on our local port (common
            # after a launcher crash — OpenSSH won't die until explicitly
            # killed, and a second tunnel can't bind the same port).
            try:
                n = _reap_orphan_tunnel_on_port(self._config.local_port)
                if n:
                    logger.info("reaped %d orphan ssh tunnel proc(s) on :%d",
                                n, self._config.local_port)
            except Exception as exc:  # noqa: BLE001
                logger.debug("orphan reap failed (non-fatal): %s", exc)
            # Prepare log dir + rotate
            try:
                self._log_dir.mkdir(parents=True, exist_ok=True)
                if self._config is not None and self._config.known_hosts_path:
                    kh = Path(self._config.known_hosts_path).expanduser()
                    kh.parent.mkdir(parents=True, exist_ok=True)
                    kh.touch(exist_ok=True)
                self._rotate_log_if_needed()
                log_path = self._log_dir / "tunnel.log"
                # Touch the file so it exists even if nothing is written yet
                log_path.touch(exist_ok=True)
                # Open in binary append mode (subprocess stdout/stderr are bytes)
                self._log_file = open(log_path, "ab", buffering=0)
            except OSError as exc:
                logger.warning("tunnel log setup failed: %s", exc)
                self._log_file = None

            self._status = TunnelStatus.STARTING
            self._fast_death_count = 0

            # Spawn watchdog — it handles initial spawn + supervision
            self._watchdog_thread = threading.Thread(
                target=self._watchdog_loop,
                name="ssh-tunnel-watchdog",
                daemon=True,
            )
            self._watchdog_thread.start()

    def stop(self, timeout_sec: float = 5.0) -> None:
        """Idempotent. SIGTERM, wait, SIGKILL if needed. Safe from atexit."""
        with self._lock:
            if self._config is None:
                return
            if not self._started and self._status != TunnelStatus.STOPPING:
                return
            if self._status == TunnelStatus.STOPPING:
                # already stopping — let the other caller finish
                watchdog = self._watchdog_thread
                proc = self._proc
            else:
                self._status = TunnelStatus.STOPPING
                self._stop_event.set()
                watchdog = self._watchdog_thread
                proc = self._proc

        # Terminate subprocess outside lock to avoid deadlock w/ watchdog
        self._terminate_proc(proc, timeout_sec)

        if watchdog is not None and watchdog.is_alive():
            watchdog.join(timeout=max(timeout_sec, 1.0))

        with self._lock:
            self._close_log_file()
            self._proc = None
            self._watchdog_thread = None
            self._started = False

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _terminate_proc(
        self,
        proc: subprocess.Popen[bytes] | None,
        timeout_sec: float,
    ) -> None:
        if proc is None:
            return
        if proc.poll() is not None:
            return
        try:
            proc.terminate()
        except Exception as exc:  # noqa: BLE001 — best-effort cleanup
            logger.debug("proc.terminate raised: %s", exc)
        try:
            proc.wait(timeout=timeout_sec)
            return
        except subprocess.TimeoutExpired:
            pass
        except Exception as exc:  # noqa: BLE001
            logger.debug("proc.wait raised: %s", exc)
        try:
            proc.kill()
        except Exception as exc:  # noqa: BLE001
            logger.debug("proc.kill raised: %s", exc)
        try:
            proc.wait(timeout=timeout_sec)
        except Exception as exc:  # noqa: BLE001
            logger.debug("post-kill wait raised: %s", exc)

    def _close_log_file(self) -> None:
        if self._log_file is not None:
            try:
                self._log_file.close()
            except Exception as exc:  # noqa: BLE001
                logger.debug("log file close raised: %s", exc)
            self._log_file = None

    def _rotate_log_if_needed(self) -> None:
        log_path = self._log_dir / "tunnel.log"
        try:
            if not log_path.exists():
                return
            if log_path.stat().st_size <= _MAX_LOG_BYTES:
                return
        except OSError as exc:
            logger.debug("log stat failed: %s", exc)
            return
        rotated = self._log_dir / "tunnel.log.1"
        try:
            if rotated.exists():
                rotated.unlink()
            log_path.replace(rotated)
        except OSError as exc:
            logger.debug("log rotate failed: %s", exc)

    def _spawn(self) -> subprocess.Popen[bytes] | None:
        """Launch the ssh subprocess. Returns None on spawn failure."""
        cmd = self._build_cmd()
        logger.info("spawning ssh tunnel: %s", " ".join(cmd))
        popen_kwargs: dict = dict(
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        # Windows: evita flash de cmd.exe ao spawnar ssh dentro do TkInter.
        if os.name == "nt":
            creationflags = 0
            for flag_name in ("CREATE_NO_WINDOW", "DETACHED_PROCESS"):
                flag = getattr(subprocess, flag_name, 0)
                creationflags |= flag
            if creationflags:
                popen_kwargs["creationflags"] = creationflags
            startupinfo = getattr(subprocess, "STARTUPINFO", None)
            if startupinfo is not None:
                si = subprocess.STARTUPINFO()  # type: ignore[attr-defined]
                si.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 1)
                si.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
                popen_kwargs["startupinfo"] = si
        try:
            # Pipe stderr for classification; pipe stdout to the log file
            # directly (ssh -N produces nothing on stdout anyway).
            proc = subprocess.Popen(cmd, **popen_kwargs)
            return proc
        except (OSError, ValueError) as exc:
            logger.error("ssh spawn failed: %s", exc)
            self._last_error = f"ssh spawn failed: {exc}"
            return None

    def _is_subprocess_alive(self) -> bool:
        proc = self._proc
        if proc is None:
            return False
        return proc.poll() is None

    def _drain_stderr(self, proc: subprocess.Popen[bytes]) -> str:
        """Read all remaining stderr. Best-effort, never raises."""
        if proc.stderr is None:
            return ""
        try:
            data = proc.stderr.read() or b""
        except Exception as exc:  # noqa: BLE001
            logger.debug("stderr read raised: %s", exc)
            return ""
        try:
            text = data.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            text = ""
        if text and self._log_file is not None:
            try:
                self._log_file.write(data)
            except Exception as exc:  # noqa: BLE001
                logger.debug("log write raised: %s", exc)
        return text

    def _drain_stdout(self, proc: subprocess.Popen[bytes]) -> None:
        """Drain stdout into log file. Best-effort."""
        if proc.stdout is None:
            return
        try:
            data = proc.stdout.read() or b""
        except Exception as exc:  # noqa: BLE001
            logger.debug("stdout read raised: %s", exc)
            return
        if data and self._log_file is not None:
            try:
                self._log_file.write(data)
            except Exception as exc:  # noqa: BLE001
                logger.debug("log write raised: %s", exc)

    def _sleep_interruptible(self, seconds: float) -> bool:
        """Sleep up to ``seconds``, return True if stop was signalled."""
        return self._stop_event.wait(timeout=max(0.0, seconds))

    def _watchdog_loop(self) -> None:
        """Supervise the ssh subprocess, respawning as needed."""
        try:
            while not self._stop_event.is_set():
                # Spawn phase
                with self._lock:
                    if self._status != TunnelStatus.STOPPING:
                        self._status = TunnelStatus.STARTING
                proc = self._spawn()
                spawn_time = time.monotonic()

                if proc is None:
                    # Spawn failed entirely (ssh binary missing?) — treat as death
                    self._fast_death_count += 1
                    if self._stop_event.is_set():
                        break
                    backoff = self._current_backoff()
                    with self._lock:
                        if self._status != TunnelStatus.STOPPING:
                            self._status = (
                                TunnelStatus.OFFLINE
                                if self._fast_death_count >= self._offline_after_failures
                                else TunnelStatus.RECONNECTING
                            )
                    if self._sleep_interruptible(backoff):
                        break
                    continue

                with self._lock:
                    self._proc = proc

                # Monitor loop — poll until it dies or stop is signalled
                became_up = False
                while not self._stop_event.is_set():
                    rc = proc.poll()
                    if rc is not None:
                        break
                    # Promote to UP once it's stayed alive past threshold
                    if (
                        not became_up
                        and (time.monotonic() - spawn_time) >= _ALIVE_THRESHOLD_SEC
                    ):
                        became_up = True
                        with self._lock:
                            if self._status != TunnelStatus.STOPPING:
                                self._status = TunnelStatus.UP
                                self._last_error = None
                                # Reset fast-death counter when we successfully
                                # stay up long enough
                                self._fast_death_count = 0
                    if self._stop_event.wait(timeout=self._watchdog_interval):
                        break

                # Stop requested — let stop() handle termination
                if self._stop_event.is_set():
                    break

                # Subprocess died on its own
                alive_duration = time.monotonic() - spawn_time
                stderr_text = self._drain_stderr(proc)
                self._drain_stdout(proc)
                classified = _classify_stderr(stderr_text)
                if classified is not None:
                    self._last_error = classified
                elif proc.returncode is not None and proc.returncode != 0:
                    self._last_error = f"ssh exited rc={proc.returncode}"
                else:
                    self._last_error = "ssh process exited"

                # Track fast deaths (even those that briefly hit UP count if
                # within the window; protects against flapping tunnels).
                if alive_duration < _FAST_DEATH_WINDOW_SEC:
                    self._fast_death_count += 1
                else:
                    self._fast_death_count = 0

                with self._lock:
                    self._proc = None
                    if self._status != TunnelStatus.STOPPING:
                        if self._fast_death_count >= self._offline_after_failures:
                            self._status = TunnelStatus.OFFLINE
                        else:
                            self._status = TunnelStatus.RECONNECTING

                if self._stop_event.is_set():
                    break
                if self._sleep_interruptible(self._current_backoff()):
                    break
        except Exception as exc:  # noqa: BLE001 — never let watchdog crash silently
            logger.exception("ssh tunnel watchdog crashed: %s", exc)
            with self._lock:
                if self._status != TunnelStatus.STOPPING:
                    self._last_error = f"watchdog crashed: {exc}"
                    self._status = TunnelStatus.OFFLINE

    def _current_backoff(self) -> float:
        if self._fast_death_count >= self._offline_after_failures:
            return self._offline_backoff
        return self._reconnect_backoff


__all__ = [
    "TunnelStatus",
    "TunnelConfig",
    "TunnelManager",
]
