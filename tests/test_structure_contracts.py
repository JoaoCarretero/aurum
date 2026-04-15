from __future__ import annotations

import sqlite3
from pathlib import Path

from config import engines as registry
from config.paths import AURUM_DB_PATH, DATA_DIR, NEXUS_DB_PATH, PROC_STATE_PATH
from core import db as trade_db
from core.connections import ConnectionManager, DEFAULT_STATE
from core.engine_base import EngineRuntime
from core import proc


def test_proc_registry_stays_in_sync_with_config_registry():
    assert set(proc.ENGINES) == set(registry.PROC_ENGINES)
    for key, meta in registry.PROC_ENGINES.items():
        assert proc.ENGINES[key]["script"] == meta["script"]
        assert registry.PROC_NAMES[key] == meta["display"]


def test_rooted_paths_contract():
    root = Path(__file__).resolve().parent.parent
    assert DATA_DIR == root / "data"
    assert AURUM_DB_PATH == root / "data" / "aurum.db"
    assert NEXUS_DB_PATH == root / "data" / "nexus.db"
    assert PROC_STATE_PATH == root / "data" / ".aurum_procs.json"


def test_connections_default_state_is_not_mutated_across_instances(tmp_path, monkeypatch):
    monkeypatch.setattr("core.connections.STATE_FILE", tmp_path / "connections.json")
    baseline = DEFAULT_STATE["connections"]["binance_futures"]["connected"]

    a = ConnectionManager()
    b = ConnectionManager()
    a.state["connections"]["binance_futures"]["connected"] = (not baseline)

    assert b.state["connections"]["binance_futures"]["connected"] == baseline
    assert DEFAULT_STATE["connections"]["binance_futures"]["connected"] == baseline


def test_engine_runtime_uses_rooted_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("core.engine_base.DATA_DIR", tmp_path)
    rt = EngineRuntime("demo_engine", subdirs=("logs", "reports"))
    assert rt.run_dir.parent == tmp_path / "demo_engine"
    assert (rt.run_dir / "logs").exists()
    assert (rt.run_dir / "reports").exists()


def test_trade_db_list_runs_normalizes_legacy_engine_aliases(tmp_path, monkeypatch):
    monkeypatch.setattr(trade_db, "DB_PATH", tmp_path / "aurum.db")
    monkeypatch.setattr(trade_db, "INDEX_PATH", tmp_path / "index.json")

    conn = sqlite3.connect(str(trade_db.DB_PATH))
    try:
        conn.executescript(trade_db._SCHEMA)
        conn.execute(
            "INSERT INTO runs (run_id, engine, timestamp, json_path) VALUES (?, ?, ?, ?)",
            ("millennium_2026-01-01_000000", "millennium", "2026-01-01T00:00:00", str(tmp_path / "x.json")),
        )
        conn.execute(
            "INSERT INTO runs (run_id, engine, timestamp, json_path) VALUES (?, ?, ?, ?)",
            ("janestreet_2026-01-01_000001", "janestreet", "2026-01-01T00:01:00", str(tmp_path / "y.json")),
        )
        conn.commit()
    finally:
        conn.close()

    assert len(trade_db.list_runs(engine="multi", limit=10)) == 1
    assert len(trade_db.list_runs(engine="arb", limit=10)) == 1
