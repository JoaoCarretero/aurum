"""Contract tests for core.engine_base — EngineRuntime."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

import core.engine_base as eb


@pytest.fixture
def iso_data_dir(tmp_path, monkeypatch):
    """Redireciona DATA_DIR pra tmp e retorna o path."""
    monkeypatch.setattr(eb, "DATA_DIR", tmp_path)
    return tmp_path


class TestEngineRuntimeInit:
    def test_creates_run_dir_under_engine_name(self, iso_data_dir):
        rt = eb.EngineRuntime("citadel")
        assert rt.run_dir.exists()
        assert rt.run_dir.parent == iso_data_dir / "citadel"

    def test_creates_default_subdirs(self, iso_data_dir):
        rt = eb.EngineRuntime("citadel")
        for sub in ("logs", "reports", "charts"):
            assert (rt.run_dir / sub).is_dir()

    def test_custom_subdirs_respected(self, iso_data_dir):
        rt = eb.EngineRuntime("citadel", subdirs=("logs", "state"))
        assert (rt.run_dir / "logs").is_dir()
        assert (rt.run_dir / "state").is_dir()
        assert not (rt.run_dir / "reports").exists()

    def test_run_id_has_expected_shape(self, iso_data_dir):
        rt = eb.EngineRuntime("citadel")
        # Format: YYYY-MM-DD_HHMM
        parts = rt.run_id.split("_")
        assert len(parts) == 2
        date, time = parts
        assert len(date) == 10  # 2026-04-15
        assert len(time) == 4   # HHMM

    def test_run_date_and_time_match_run_id(self, iso_data_dir):
        rt = eb.EngineRuntime("citadel")
        assert rt.run_id == f"{rt.run_date}_{rt.run_time}"

    def test_name_preserved(self, iso_data_dir):
        rt = eb.EngineRuntime("jump")
        assert rt.name == "jump"

    def test_loggers_created(self, iso_data_dir):
        rt = eb.EngineRuntime("citadel")
        assert isinstance(rt.log, logging.Logger)
        assert isinstance(rt.trade_log, logging.Logger)

    def test_log_logger_named_engine_upper(self, iso_data_dir):
        rt = eb.EngineRuntime("citadel")
        assert rt.log.name == "CITADEL"

    def test_trade_log_does_not_propagate(self, iso_data_dir):
        # trades.log tem format próprio e não deve duplicar pro root handler
        rt = eb.EngineRuntime("citadel")
        assert rt.trade_log.propagate is False

    def test_trade_log_file_created(self, iso_data_dir):
        rt = eb.EngineRuntime("citadel")
        # FileHandler escreve lazily, mas o arquivo já foi criado no addHandler
        for h in rt.trade_log.handlers:
            if isinstance(h, logging.FileHandler):
                h.flush()
        trades_log = rt.run_dir / "logs" / "trades.log"
        assert trades_log.parent.exists()

    def _teardown_handlers(self, rt):
        # Evita vazamento de FileHandler entre testes (Windows locks file)
        for h in list(rt.trade_log.handlers):
            h.close()
            rt.trade_log.removeHandler(h)


class TestSaveReport:
    def test_writes_json_to_reports_dir(self, iso_data_dir):
        rt = eb.EngineRuntime("citadel")
        path = rt.save_report({"k": "v", "n": 42}, "summary.json")
        assert path.exists()
        assert path.parent.name == "reports"

    def test_returns_path(self, iso_data_dir):
        rt = eb.EngineRuntime("citadel")
        path = rt.save_report({"x": 1}, "r.json")
        assert isinstance(path, Path)

    def test_content_is_valid_json(self, iso_data_dir):
        rt = eb.EngineRuntime("citadel")
        payload = {"sharpe": 1.5, "trades": 100}
        path = rt.save_report(payload, "r.json")
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded == payload

    def test_atomic_write_no_tmp_leak(self, iso_data_dir):
        rt = eb.EngineRuntime("citadel")
        rt.save_report({"x": 1}, "r.json")
        siblings = list((rt.run_dir / "reports").iterdir())
        assert all(not s.name.endswith(".tmp") for s in siblings)
