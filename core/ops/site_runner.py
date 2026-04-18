"""
☿ AURUM Finance — Site Runner
==============================
Manages a local web dev server (next/vite/nuxt/django/etc) as a long-lived
subprocess owned by the launcher. Auto-detects framework, captures stdout
into a rolling buffer with a monotonic line counter, and exposes a small
API the launcher's UI uses to render and tail the console.

Used by the COMMAND CENTER > SITE LOCAL screen.
"""
from __future__ import annotations

import json
import os
import queue
import shlex
import subprocess
import sys
import threading
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional

from config.paths import SITE_CONFIG_PATH
from core.persistence import atomic_write_json


_DEFAULT_CONFIG = {
    "project_dir":       "",
    "framework":         "auto",
    "port":              3000,
    "command":           "",
    "env":               {},
    "auto_open_browser": True,
}

_FRAMEWORK_COMMANDS = {
    "next":   lambda port: "npx next dev",
    "vite":   lambda port: "npx vite",
    "nuxt":   lambda port: "npx nuxt dev",
    "gatsby": lambda port: "npx gatsby develop",
    "django": lambda port: f"python manage.py runserver {port}",
    "rust":   lambda port: "cargo run",
    "static": lambda port: f"python -m http.server {port}",
    "custom": lambda port: "npm run dev",
}


class SiteRunner:
    """Owns the dev-server subprocess + a thread-safe rolling stdout buffer."""

    def __init__(self, config_path: str | Path = SITE_CONFIG_PATH):
        self.config_path = Path(config_path)
        self.config: dict = self._load_config()
        self.proc: Optional[subprocess.Popen] = None
        self.start_time: Optional[datetime] = None
        # Rolling output: deque caps memory; total_emitted is monotonic so
        # consumers can resync after the deque rotates.
        self.buffer: deque = deque(maxlen=2000)
        self.total_emitted: int = 0
        self._reader: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    # ── CONFIG ────────────────────────────────────────────────
    def _load_config(self) -> dict:
        merged = dict(_DEFAULT_CONFIG)
        if self.config_path.exists():
            try:
                data = json.loads(self.config_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    for k, v in data.items():
                        merged[k] = v
            except Exception:
                pass
        return merged

    def save_config(self, **kwargs) -> None:
        """Update config with the given kwargs and persist to disk."""
        for k, v in kwargs.items():
            self.config[k] = v
        atomic_write_json(self.config_path, self.config)

    # ── FRAMEWORK DETECTION ───────────────────────────────────
    def detect_framework(self, project_dir: str | None = None) -> tuple[str, str]:
        """Inspect the project dir and return (framework, command)."""
        d = Path(project_dir or self.config.get("project_dir", ""))
        port = int(self.config.get("port", 3000) or 3000)
        if not d.exists() or not d.is_dir():
            return ("unknown", "npm run dev")

        # 1. Next.js
        if any(d.glob("next.config.*")):
            return ("next", _FRAMEWORK_COMMANDS["next"](port))
        # 2. Vite
        if any(d.glob("vite.config.*")):
            return ("vite", _FRAMEWORK_COMMANDS["vite"](port))
        # 3. Nuxt
        if any(d.glob("nuxt.config.*")):
            return ("nuxt", _FRAMEWORK_COMMANDS["nuxt"](port))
        # 4. Gatsby
        if any(d.glob("gatsby-config.*")):
            return ("gatsby", _FRAMEWORK_COMMANDS["gatsby"](port))
        # 5/6. package.json scripts
        pkg = d / "package.json"
        if pkg.exists():
            try:
                pkg_data = json.loads(pkg.read_text(encoding="utf-8"))
                scripts = pkg_data.get("scripts", {}) if isinstance(pkg_data, dict) else {}
                if "dev" in scripts:
                    return ("custom", "npm run dev")
                if "start" in scripts:
                    return ("custom", "npm start")
            except Exception:
                pass
        # 7. Django
        if (d / "manage.py").exists():
            return ("django", _FRAMEWORK_COMMANDS["django"](port))
        # 8. Rust
        if (d / "Cargo.toml").exists():
            return ("rust", _FRAMEWORK_COMMANDS["rust"](port))
        # 9. Static HTML
        if (d / "index.html").exists():
            return ("static", _FRAMEWORK_COMMANDS["static"](port))
        return ("unknown", "npm run dev")

    def resolved_command(self) -> tuple[str, list[str]]:
        """Apply user override / explicit framework selection / autodetect."""
        override = (self.config.get("command") or "").strip()
        if override:
            framework = self.config.get("framework", "custom") or "custom"
            return (framework, self._split_command(override))
        framework = self.config.get("framework", "auto") or "auto"
        if framework == "auto":
            framework, command = self.detect_framework()
            return (framework, self._split_command(command))
        port = int(self.config.get("port", 3000) or 3000)
        builder = _FRAMEWORK_COMMANDS.get(framework, _FRAMEWORK_COMMANDS["custom"])
        return (framework, self._split_command(builder(port)))

    def _split_command(self, command: str) -> list[str]:
        posix = sys.platform != "win32"
        parts = shlex.split(command, posix=posix)
        return parts or [command]

    # ── LIFECYCLE ─────────────────────────────────────────────
    def is_running(self) -> bool:
        return bool(self.proc and self.proc.poll() is None)

    def start(self) -> tuple[bool, str]:
        if self.is_running():
            return (False, "already running")
        d = (self.config.get("project_dir") or "").strip()
        if not d:
            return (False, "project_dir not set")
        if not Path(d).is_dir():
            return (False, "project_dir does not exist")

        framework, command = self.resolved_command()
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["FORCE_COLOR"] = "0"   # most node tools honour this → no ANSI to strip
        env["CI"] = "1"            # next/vite emit terser, non-interactive output
        for k, v in (self.config.get("env") or {}).items():
            env[str(k)] = str(v)

        popen_kwargs: dict = dict(
            cwd=d,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        try:
            self.proc = subprocess.Popen(command, **popen_kwargs)
        except Exception as e:
            return (False, f"spawn failed: {e}")

        self.start_time = datetime.now()
        self.buffer.clear()
        self.total_emitted = 0
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

        # Persist the resolved framework so the config screen reflects reality.
        if self.config.get("framework") == "auto":
            try:
                self.save_config(framework=framework)
            except Exception:
                pass

        header = f"▶ {subprocess.list2cmdline(command) if sys.platform == 'win32' else shlex.join(command)}\n"
        with self._lock:
            self.buffer.append(header)
            self.total_emitted += 1
        return (True, framework)

    def _read_loop(self) -> None:
        try:
            assert self.proc and self.proc.stdout
            for line in iter(self.proc.stdout.readline, ""):
                if not line:
                    break
                with self._lock:
                    self.buffer.append(line)
                    self.total_emitted += 1
            try:
                self.proc.stdout.close()
            except Exception:
                pass
        except Exception:
            pass

    def stop(self) -> bool:
        if not self.is_running():
            self.start_time = None
            return False
        try:
            if sys.platform == "win32":
                # /T kills the entire process tree (npm → node → server).
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(self.proc.pid)],
                    capture_output=True,
                    timeout=5,
                )
            else:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
        except Exception:
            pass
        self.start_time = None
        with self._lock:
            self.buffer.append("\n>> SIGTERM\n")
            self.total_emitted += 1
        return True

    # ── INTROSPECTION ─────────────────────────────────────────
    def uptime(self) -> str:
        if not self.start_time:
            return "00:00:00"
        delta = datetime.now() - self.start_time
        s = int(delta.total_seconds())
        h, s = divmod(s, 3600)
        m, s = divmod(s, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    def url(self) -> str:
        port = int(self.config.get("port", 3000) or 3000)
        return f"http://localhost:{port}"

    def lines_after(self, idx: int) -> tuple[int, list[str]]:
        """
        Return (new_total_emitted, lines_to_append).

        ``idx`` is the consumer's last-seen absolute line index. Any lines
        that have rolled out of the deque since are silently skipped — the
        new index is clamped to the current buffer base.
        """
        with self._lock:
            snap = list(self.buffer)
            total = self.total_emitted
        base = total - len(snap)
        start = max(idx, base)
        if start >= total:
            return (total, [])
        return (total, snap[start - base:])

    def reset_buffer(self) -> None:
        """Drop everything in the buffer (used by the UI 'CLEAR' button)."""
        with self._lock:
            self.buffer.clear()
            # Don't reset total_emitted — consumers track absolute positions.
