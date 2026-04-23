"""Contract tests for infra utility modules:
core.health, core.failure_policy, core.persistence.

São todos módulos pequenos sem lógica de trading — testes simples e diretos.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.failure_policy import (
    BEST_EFFORT,
    DEGRADE_AND_LOG,
    MUST_FAIL_LOUD,
    SKIP_AND_CONTINUE,
)
from core.health import HealthLedger, runtime_health
from core.persistence import atomic_write_json, atomic_write_text
from launcher_support import bootstrap


# ────────────────────────────────────────────────────────────
# core.health
# ────────────────────────────────────────────────────────────

class TestHealthLedger:
    def test_fresh_ledger_empty_snapshot(self):
        ledger = HealthLedger()
        assert ledger.snapshot() == {}

    def test_record_increments_counter(self):
        ledger = HealthLedger()
        ledger.record("transport.timeout")
        ledger.record("transport.timeout")
        ledger.record("http.429")
        snap = ledger.snapshot()
        assert snap["transport.timeout"] == 2
        assert snap["http.429"] == 1

    def test_record_with_explicit_n(self):
        ledger = HealthLedger()
        ledger.record("retries", n=5)
        assert ledger.snapshot()["retries"] == 5

    def test_diagnostic_payload_has_schema_version(self):
        ledger = HealthLedger()
        ledger.record("x")
        payload = ledger.diagnostic_payload()
        assert payload["schema_version"] == "runtime_health.v1"
        assert payload["counters"] == {"x": 1}

    def test_runtime_health_is_singleton_ledger(self):
        # Módulo expõe uma instância global — serve de sink padrão
        assert isinstance(runtime_health, HealthLedger)

    def test_snapshot_returns_copy(self):
        # Mutação do snapshot não deve afetar ledger interno
        ledger = HealthLedger()
        ledger.record("k")
        snap = ledger.snapshot()
        snap["k"] = 999
        assert ledger.snapshot()["k"] == 1


# ────────────────────────────────────────────────────────────
# core.failure_policy
# ────────────────────────────────────────────────────────────

class TestFailurePolicy:
    @pytest.mark.parametrize("policy", [MUST_FAIL_LOUD, BEST_EFFORT,
                                         DEGRADE_AND_LOG, SKIP_AND_CONTINUE])
    def test_is_frozen_dataclass(self, policy):
        with pytest.raises((AttributeError, Exception)):
            policy.name = "mutated"  # type: ignore[misc]

    def test_must_fail_loud_raises_and_counts(self):
        assert MUST_FAIL_LOUD.should_raise is True
        assert MUST_FAIL_LOUD.log_level == "error"
        assert MUST_FAIL_LOUD.count_in_health is True

    def test_best_effort_silent_with_debug(self):
        assert BEST_EFFORT.should_raise is False
        assert BEST_EFFORT.log_level == "debug"

    def test_degrade_and_log_warning_level(self):
        assert DEGRADE_AND_LOG.should_raise is False
        assert DEGRADE_AND_LOG.log_level == "warning"

    def test_skip_and_continue_info_level(self):
        assert SKIP_AND_CONTINUE.should_raise is False
        assert SKIP_AND_CONTINUE.log_level == "info"

    def test_all_policies_count_in_health(self):
        # Todas as políticas atuais contam — invariante importante
        # (se adicionarem política silenciosa, este teste quebra e força
        # revisão consciente)
        for p in (MUST_FAIL_LOUD, BEST_EFFORT, DEGRADE_AND_LOG, SKIP_AND_CONTINUE):
            assert p.count_in_health is True

    def test_names_are_unique(self):
        policies = [MUST_FAIL_LOUD, BEST_EFFORT, DEGRADE_AND_LOG, SKIP_AND_CONTINUE]
        names = [p.name for p in policies]
        assert len(names) == len(set(names))


# ────────────────────────────────────────────────────────────
# core.persistence
# ────────────────────────────────────────────────────────────

class TestAtomicWriteText:
    def test_writes_content(self, tmp_path):
        target = tmp_path / "out.txt"
        atomic_write_text(target, "hello")
        assert target.read_text(encoding="utf-8") == "hello"

    def test_creates_parent_directories(self, tmp_path):
        target = tmp_path / "deep" / "nested" / "out.txt"
        atomic_write_text(target, "x")
        assert target.read_text() == "x"

    def test_overwrites_existing(self, tmp_path):
        target = tmp_path / "out.txt"
        target.write_text("old", encoding="utf-8")
        atomic_write_text(target, "new")
        assert target.read_text(encoding="utf-8") == "new"

    def test_returns_path_object(self, tmp_path):
        target = tmp_path / "out.txt"
        result = atomic_write_text(target, "x")
        assert isinstance(result, Path)
        assert result == target

    def test_no_temp_files_leak_after_success(self, tmp_path):
        target = tmp_path / "out.txt"
        atomic_write_text(target, "x")
        # Nenhum .tmp deve sobrar no diretório
        siblings = [p.name for p in tmp_path.iterdir()]
        assert all(not s.endswith(".tmp") for s in siblings)

    def test_preserves_original_on_write_failure(self, tmp_path, monkeypatch):
        target = tmp_path / "out.txt"
        target.write_text("original", encoding="utf-8")

        def bad_replace(*_args, **_kwargs):
            raise OSError("simulated rename failure")

        monkeypatch.setattr("core.persistence.os.replace", bad_replace)
        with pytest.raises(OSError):
            atomic_write_text(target, "new content")
        # Original intacto
        assert target.read_text(encoding="utf-8") == "original"
        # Tmp file limpo
        siblings = [p.name for p in tmp_path.iterdir()]
        assert all(not s.endswith(".tmp") for s in siblings)

    def test_encoding_parameter_honored(self, tmp_path):
        target = tmp_path / "out.txt"
        content = "ção — 日本"
        atomic_write_text(target, content, encoding="utf-8")
        assert target.read_bytes() == content.encode("utf-8")


class TestAtomicWriteJson:
    def test_writes_dict(self, tmp_path):
        target = tmp_path / "out.json"
        atomic_write_json(target, {"key": "value", "n": 42})
        loaded = json.loads(target.read_text(encoding="utf-8"))
        assert loaded == {"key": "value", "n": 42}

    def test_indented_by_default(self, tmp_path):
        target = tmp_path / "out.json"
        atomic_write_json(target, {"a": 1, "b": 2})
        content = target.read_text(encoding="utf-8")
        # Indented (indent=2) → contains newlines
        assert "\n" in content

    def test_non_ascii_preserved(self, tmp_path):
        target = tmp_path / "out.json"
        atomic_write_json(target, {"label": "ação"})
        content = target.read_text(encoding="utf-8")
        # ensure_ascii=False default → acento literal, não \uXXXX
        assert "ação" in content

    def test_non_serializable_falls_back_to_str(self, tmp_path):
        target = tmp_path / "out.json"
        # Path não é JSON-serializable por padrão; default=str deve converter
        atomic_write_json(target, {"p": Path("/tmp/x")})
        loaded = json.loads(target.read_text(encoding="utf-8"))
        assert isinstance(loaded["p"], str)

    def test_json_kwargs_override_defaults(self, tmp_path):
        target = tmp_path / "out.json"
        atomic_write_json(target, {"a": 1}, indent=None)
        content = target.read_text(encoding="utf-8")
        # indent=None → no newlines
        assert "\n" not in content.strip()


class TestBootstrapInfraHardening:
    def test_build_vps_ssh_command_enforces_strict_host_checks(self, monkeypatch, tmp_path):
        key_path = tmp_path / "id_ed25519"
        key_path.write_text("dummy", encoding="utf-8")
        monkeypatch.setattr(
            bootstrap,
            "load_vps_config",
            lambda: {
                "host": "37.60.254.151",
                "user": "deploy",
                "port": "2222",
                "key_path": str(key_path),
                "remote_dir": "/srv/aurum.finance",
                "host_display": "deploy@37.60.254.151",
            },
        )

        argv = bootstrap.build_vps_ssh_command("echo ok")

        assert "StrictHostKeyChecking=yes" in argv
        assert "PasswordAuthentication=no" in argv
        assert "IdentitiesOnly=yes" in argv
        assert "StrictHostKeyChecking=no" not in argv
        assert argv[-3:] == ["bash", "-lc", "echo ok"]

    @pytest.mark.parametrize("host", ["bad host", "bad;host", "host\nname"])
    def test_load_vps_config_rejects_invalid_host(self, monkeypatch, tmp_path, host):
        cfg = tmp_path / "vps.json"
        cfg.write_text(json.dumps({"host": host, "user": "deploy", "port": "22"}), encoding="utf-8")
        monkeypatch.setattr(bootstrap, "VPS_CONFIG_PATH", str(cfg))
        monkeypatch.setattr(bootstrap, "_VPS_CFG_CACHE", {"mtime": None, "value": None})

        with pytest.raises(ValueError):
            bootstrap.load_vps_config()

    def test_build_vps_ssh_command_rejects_multiline_remote_command(self, monkeypatch, tmp_path):
        key_path = tmp_path / "id_ed25519"
        key_path.write_text("dummy", encoding="utf-8")
        monkeypatch.setattr(
            bootstrap,
            "load_vps_config",
            lambda: {
                "host": "example.com",
                "user": "deploy",
                "port": "22",
                "key_path": str(key_path),
                "remote_dir": "/srv/aurum.finance",
                "host_display": "deploy@example.com",
            },
        )

        with pytest.raises(ValueError):
            bootstrap.build_vps_ssh_command("echo ok\nrm -rf /")

    def test_project_commands_quote_paths_and_mode(self):
        log_cmd = bootstrap.build_vps_log_tail_command("~/aurum finance")
        launch_cmd = bootstrap.build_millennium_bootstrap_launch_command("~/aurum finance", "diag;rm -rf /")

        assert "$HOME/aurum finance" in log_cmd
        assert "screen -dmS" in launch_cmd
        assert "bash -lc" in launch_cmd
        # O mode malicioso passa por shlex.quote, entao aparece ENTRE ASPAS
        # (inofensivo). A assertion valida o escape explicitamente — antes
        # so verificava presenca da string, o que era enganoso.
        assert "'diag;rm -rf /'" in launch_cmd


class TestDeployArtifactsHardening:
    def test_docker_compose_requires_env_password_and_loopback_binds(self):
        content = Path("docker-compose.yml").read_text(encoding="utf-8")

        assert "127.0.0.1:8001:8001" in content
        assert "127.0.0.1:3000:3000" in content
        assert "VNC_PW=${MT5_VNC_PASSWORD:?" in content
        assert "aurum2026" not in content
        assert "no-new-privileges:true" in content

    def test_systemd_unit_runs_non_root_with_hardening(self):
        content = Path("deploy/aurum_cockpit_api.service").read_text(encoding="utf-8")

        assert "User=aurum" in content
        assert "Group=aurum" in content
        assert "UMask=0077" in content
        assert "NoNewPrivileges=yes" in content
        assert "CapabilityBoundingSet=" in content
        assert "PrivateUsers=yes" in content
        assert "ProtectKernelTunables=yes" in content
        assert "User=root" not in content

    def test_installer_defaults_to_non_root_service_user(self):
        content = Path("deploy/install_cockpit_api_vps.sh").read_text(encoding="utf-8")

        assert 'DEFAULT_SERVICE_USER="${SUDO_USER:-$(whoami)}"' in content
        assert 'DEFAULT_SERVICE_USER="aurum"' in content
        assert 'sudo useradd --system --create-home' in content
        assert 'sudo chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "${DATA_DIR}"' in content
        assert 'sudo systemd-analyze verify "${UNIT_DST}"' in content
