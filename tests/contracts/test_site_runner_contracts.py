from __future__ import annotations

import io
import json
import subprocess

import core.site_runner as sr
from core.site_runner import SiteRunner


class _DummyThread:
    def __init__(self, target=None, daemon=None):
        self.target = target
        self.daemon = daemon

    def start(self):
        return None


class _FakeProc:
    def __init__(self):
        self.stdout = io.StringIO("")
        self.pid = 123

    def poll(self):
        return None


def test_resolved_command_splits_override_without_shell(tmp_path):
    runner = SiteRunner(config_path=tmp_path / "site.json")
    runner.config["framework"] = "custom"
    runner.config["command"] = "npm run dev -- --host 0.0.0.0"

    framework, command = runner.resolved_command()

    assert framework == "custom"
    assert command == ["npm", "run", "dev", "--", "--host", "0.0.0.0"]


def test_start_uses_argv_without_shell(tmp_path, monkeypatch):
    project_dir = tmp_path / "site"
    project_dir.mkdir()

    runner = SiteRunner(config_path=tmp_path / "site.json")
    runner.config.update(
        {
            "project_dir": str(project_dir),
            "framework": "custom",
            "command": "npm run dev",
        }
    )

    fake_proc = _FakeProc()
    captured: dict = {}

    def _fake_popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return fake_proc

    monkeypatch.setattr("core.site_runner.threading.Thread", _DummyThread)
    monkeypatch.setattr(subprocess, "Popen", _fake_popen)

    ok, framework = runner.start()

    assert ok is True
    assert framework == "custom"
    assert captured["command"] == ["npm", "run", "dev"]
    assert captured["kwargs"].get("shell", False) is False


def test_load_config_uses_ttl_cache(tmp_path, monkeypatch):
    config_path = tmp_path / "site.json"
    config_path.write_text(json.dumps({"port": 3100}), encoding="utf-8")
    clock = {"value": 100.0}
    monkeypatch.setattr(sr.time, "monotonic", lambda: clock["value"])
    sr._CONFIG_CACHE.clear()

    runner = SiteRunner(config_path=config_path)
    assert runner.config["port"] == 3100

    config_path.write_text(json.dumps({"port": 3200}), encoding="utf-8")
    cached_runner = SiteRunner(config_path=config_path)
    assert cached_runner.config["port"] == 3100

    clock["value"] += sr._CONFIG_CACHE_TTL_S + 0.1
    fresh_runner = SiteRunner(config_path=config_path)
    assert fresh_runner.config["port"] == 3200


def test_detect_framework_uses_ttl_cache(tmp_path, monkeypatch):
    project_dir = tmp_path / "site"
    project_dir.mkdir()
    (project_dir / "next.config.js").write_text("module.exports = {}", encoding="utf-8")
    runner = SiteRunner(config_path=tmp_path / "site.json")
    runner.config["port"] = 3000
    clock = {"value": 200.0}
    monkeypatch.setattr(sr.time, "monotonic", lambda: clock["value"])

    framework, _command = runner.detect_framework(str(project_dir))
    assert framework == "next"

    (project_dir / "next.config.js").unlink()
    (project_dir / "vite.config.ts").write_text("export default {}", encoding="utf-8")
    cached_framework, _ = runner.detect_framework(str(project_dir))
    assert cached_framework == "next"

    clock["value"] += sr._FRAMEWORK_CACHE_TTL_S + 0.1
    fresh_framework, _ = runner.detect_framework(str(project_dir))
    assert fresh_framework == "vite"
