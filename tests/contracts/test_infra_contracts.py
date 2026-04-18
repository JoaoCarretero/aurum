"""Contract tests for infra utility modules:
core.health, core.failure_policy, core.persistence.

São todos módulos pequenos sem lógica de trading — testes simples e diretos.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from core.failure_policy import (
    BEST_EFFORT,
    DEGRADE_AND_LOG,
    MUST_FAIL_LOUD,
    SKIP_AND_CONTINUE,
    FailurePolicy,
)
from core.health import HealthLedger, runtime_health
from core.persistence import atomic_write_json, atomic_write_text


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
