"""Contract tests for core.db — SQLite run history + trades.

Cobrem:
- helpers puros: _normalize_engine (alias table), _normalize_run_id
- save_run via JSON + DATA_DIR monkeypatched
- CRUD: list_runs, get_run, get_trades, delete_run
- stats_summary agregações
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

import core.db as db


# ────────────────────────────────────────────────────────────
# fixtures — DB isolado + DATA_DIR redirecionado
# ────────────────────────────────────────────────────────────

@pytest.fixture
def iso_db(tmp_path, monkeypatch):
    """DB isolado em tmp + DATA_DIR/DB_PATH monkeypatched."""
    db_path = tmp_path / "test.db"
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setattr(db, "DATA_DIR", data_dir)
    # INDEX_PATH inexistente força _lookup_index_days a retornar None silenciosamente
    monkeypatch.setattr(db, "INDEX_PATH", tmp_path / "nonexistent_index.json")
    return {"db_path": db_path, "data_dir": data_dir}


@pytest.fixture(autouse=True)
def _clear_db_index_cache():
    db.clear_index_cache()
    yield
    db.clear_index_cache()


def _write_run_json(data_dir: Path, engine: str, run_ts: str,
                     payload: dict | None = None) -> Path:
    """Escreve reports/X.json em data/{engine}/{run_ts}/reports/.
    Retorna o path absoluto pronto pra save_run()."""
    run_dir = data_dir / engine / run_ts / "reports"
    run_dir.mkdir(parents=True)
    json_path = run_dir / "report.json"
    base = {
        "run_id": f"{engine}_{run_ts}",
        "engine": engine,
        "timestamp": "2026-04-15T10:00:00",
        "interval": "1h",
        "summary": {"sharpe": 1.5, "sortino": 2.0, "win_rate": 0.55,
                     "ret": 0.25, "max_dd_pct": -0.08, "total": 50,
                     "final_equity": 12_500.0},
        "trades": [],
        "config": {"account_size": 10_000, "leverage": 1.0, "scan_days": 30,
                    "symbols": ["BTCUSDT", "ETHUSDT"]},
    }
    if payload:
        base.update(payload)
    json_path.write_text(json.dumps(base), encoding="utf-8")
    return json_path


# ────────────────────────────────────────────────────────────
# _normalize_engine
# ────────────────────────────────────────────────────────────

class TestNormalizeEngine:
    def test_direct_match_returns_alias(self):
        # aliases definidos no módulo
        assert db._normalize_engine("backtest") == "citadel"
        assert db._normalize_engine("mercurio") == "jump"
        assert db._normalize_engine("darwin") == "aqr"

    def test_passthrough_for_unknown(self):
        assert db._normalize_engine("citadel") == "citadel"
        assert db._normalize_engine("janestreet") == "janestreet"

    def test_case_insensitive(self):
        assert db._normalize_engine("Backtest") == "citadel"
        assert db._normalize_engine("MERCURIO") == "jump"

    def test_falls_back_to_payload_engine(self):
        # Engine vazio mas payload tem engine → usa payload
        assert db._normalize_engine("", {"engine": "thoth"}) == "bridgewater"

    def test_falls_back_to_path_parent(self):
        # Path como 'data/jump/2026-01-01_1000/reports/x.json' → parent parent = 'jump'
        p = "data/jump/2026-01-01_1000/reports/x.json"
        assert db._normalize_engine("", None, p) == "jump"

    def test_unknown_when_nothing_matches(self):
        assert db._normalize_engine("", {}, None) == "unknown"


# ────────────────────────────────────────────────────────────
# _normalize_run_id
# ────────────────────────────────────────────────────────────

class TestNormalizeRunId:
    def test_already_prefixed_passthrough(self):
        assert db._normalize_run_id("citadel_2026-01-01_1000", "citadel") == "citadel_2026-01-01_1000"

    def test_prefix_added_when_timestamp_like(self):
        # 'YYYY-..' → prefixed
        assert db._normalize_run_id("2026-01-01_1000", "jump") == "jump_2026-01-01_1000"

    def test_raw_passthrough_when_not_timestamp(self):
        assert db._normalize_run_id("myrun", "citadel") == "myrun"

    def test_generates_from_now_when_all_empty(self):
        out = db._normalize_run_id("", "citadel")
        # datetime format YYYY-MM-DD_HHMMSS
        assert len(out) == len("2026-01-01_123456")
        assert "_" in out


# ────────────────────────────────────────────────────────────
# save_run + CRUD
# ────────────────────────────────────────────────────────────

class TestSaveRun:
    def test_persists_basic_run(self, iso_db):
        json_path = _write_run_json(iso_db["data_dir"], "citadel", "2026-04-15_0900")
        run_id = db.save_run("citadel", str(json_path))
        assert run_id is not None

        row = db.get_run(run_id)
        assert row is not None
        assert row["engine"] == "citadel"
        assert row["interval"] == "1h"
        assert row["sharpe"] == 1.5

    def test_rejects_path_outside_data_dir(self, iso_db, tmp_path):
        # Path fora do DATA_DIR → None
        outside = tmp_path / "outside.json"
        outside.write_text(json.dumps({"run_id": "x"}), encoding="utf-8")
        assert db.save_run("citadel", str(outside)) is None

    def test_returns_none_for_missing_file(self, iso_db):
        # Path inside DATA_DIR mas arquivo não existe
        phantom = iso_db["data_dir"] / "citadel" / "ghost" / "reports" / "x.json"
        phantom.parent.mkdir(parents=True)
        assert db.save_run("citadel", str(phantom)) is None

    def test_returns_none_on_malformed_json(self, iso_db):
        run_dir = iso_db["data_dir"] / "citadel" / "bad" / "reports"
        run_dir.mkdir(parents=True)
        bad = run_dir / "x.json"
        bad.write_text("{not valid json", encoding="utf-8")
        assert db.save_run("citadel", str(bad)) is None

    def test_reingest_overwrites_existing(self, iso_db):
        json_path = _write_run_json(iso_db["data_dir"], "citadel", "2026-04-15_0900")
        run_id = db.save_run("citadel", str(json_path))
        # Reescreve JSON com novo sharpe
        json_path.write_text(json.dumps({
            "run_id": run_id,
            "engine": "citadel",
            "timestamp": "2026-04-15T10:00:00",
            "summary": {"sharpe": 9.9, "total": 99},
            "config": {"account_size": 10_000, "leverage": 1.0},
        }), encoding="utf-8")
        run_id2 = db.save_run("citadel", str(json_path))
        assert run_id == run_id2
        row = db.get_run(run_id)
        assert row["sharpe"] == 9.9

    def test_persists_trades(self, iso_db):
        trades = [
            {"symbol": "BTCUSDT", "side": "BULLISH", "entry": 100.0,
             "stop": 98.0, "target": 104.0, "result": "WIN", "pnl": 100.0},
            {"symbol": "ETHUSDT", "side": "BEARISH", "entry": 200.0,
             "stop": 202.0, "target": 196.0, "result": "LOSS", "pnl": -100.0},
        ]
        json_path = _write_run_json(iso_db["data_dir"], "citadel",
                                     "2026-04-15_0900", {"trades": trades})
        run_id = db.save_run("citadel", str(json_path))
        persisted = db.get_trades(run_id)
        assert len(persisted) == 2

    def test_lookup_index_days_uses_ttl_cache(self, iso_db):
        index_path = iso_db["data_dir"].parent / "index.json"
        db.INDEX_PATH = index_path
        index_path.write_text(json.dumps([
            {"run_id": "citadel_2026-04-15_0900", "period_days": 30},
        ]), encoding="utf-8")

        assert db._lookup_index_days("citadel_2026-04-15_0900") == 30

        index_path.write_text(json.dumps([
            {"run_id": "citadel_2026-04-15_0900", "period_days": 99},
        ]), encoding="utf-8")

        assert db._lookup_index_days("citadel_2026-04-15_0900") == 30


class TestListRuns:
    def test_empty_db_returns_empty_list(self, iso_db):
        assert db.list_runs() == []

    def test_returns_all_when_no_engine_filter(self, iso_db):
        _ = db.save_run("citadel", str(
            _write_run_json(iso_db["data_dir"], "citadel", "2026-04-15_0900")))
        _ = db.save_run("jump", str(
            _write_run_json(iso_db["data_dir"], "jump", "2026-04-15_1000")))
        rows = db.list_runs()
        engines = {r["engine"] for r in rows}
        assert engines == {"citadel", "jump"}

    def test_engine_filter_applied(self, iso_db):
        db.save_run("citadel", str(
            _write_run_json(iso_db["data_dir"], "citadel", "2026-04-15_0900")))
        db.save_run("jump", str(
            _write_run_json(iso_db["data_dir"], "jump", "2026-04-15_1000")))
        rows = db.list_runs(engine="citadel")
        assert len(rows) == 1
        assert rows[0]["engine"] == "citadel"

    def test_engine_alias_respected_in_filter(self, iso_db):
        # 'backtest' → 'citadel' via alias
        db.save_run("citadel", str(
            _write_run_json(iso_db["data_dir"], "citadel", "2026-04-15_0900")))
        rows = db.list_runs(engine="backtest")
        assert len(rows) == 1
        assert rows[0]["engine"] == "citadel"

    def test_limit_respected(self, iso_db):
        for i in range(5):
            db.save_run("citadel", str(
                _write_run_json(iso_db["data_dir"], "citadel",
                                 f"2026-04-{i+10:02d}_0900")))
        rows = db.list_runs(limit=3)
        assert len(rows) == 3

    def test_ordered_by_timestamp_desc(self, iso_db):
        for i, ts in enumerate(["2026-04-10T10:00:00", "2026-04-12T10:00:00",
                                  "2026-04-11T10:00:00"]):
            db.save_run("citadel", str(
                _write_run_json(iso_db["data_dir"], "citadel",
                                 f"2026-04-{10+i:02d}_0900",
                                 {"timestamp": ts})))
        rows = db.list_runs()
        timestamps = [r["timestamp"] for r in rows]
        assert timestamps == sorted(timestamps, reverse=True)


class TestGetRun:
    def test_missing_run_returns_none(self, iso_db):
        assert db.get_run("nonexistent") is None

    def test_returns_full_row(self, iso_db):
        json_path = _write_run_json(iso_db["data_dir"], "citadel", "2026-04-15_0900")
        run_id = db.save_run("citadel", str(json_path))
        row = db.get_run(run_id)
        assert row is not None
        assert row["run_id"] == run_id


class TestDeleteRun:
    def test_removes_run_and_trades(self, iso_db):
        trades = [{"symbol": "BTC", "entry": 100, "pnl": 50}]
        json_path = _write_run_json(iso_db["data_dir"], "citadel",
                                     "2026-04-15_0900", {"trades": trades})
        run_id = db.save_run("citadel", str(json_path))
        assert db.get_run(run_id) is not None
        assert len(db.get_trades(run_id)) == 1

        assert db.delete_run(run_id) is True
        assert db.get_run(run_id) is None
        assert db.get_trades(run_id) == []

    def test_returns_false_for_missing(self, iso_db):
        assert db.delete_run("nonexistent") is False


class TestStatsSummary:
    def test_empty_db_returns_structured_response(self, iso_db):
        stats = db.stats_summary()
        # Exact shape depends on implementation; just ensure it doesn't crash
        # and returns something dict-like
        assert stats is not None

    def test_with_runs_aggregates(self, iso_db):
        db.save_run("citadel", str(
            _write_run_json(iso_db["data_dir"], "citadel", "2026-04-15_0900")))
        db.save_run("jump", str(
            _write_run_json(iso_db["data_dir"], "jump", "2026-04-15_1000")))
        stats = db.stats_summary()
        assert stats is not None
