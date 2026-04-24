from __future__ import annotations

import sqlite3
from pathlib import Path

from config import engines as registry
from config.paths import AURUM_DB_PATH, AURUM_JWT_SECRET_PATH, DATA_DIR, NEXUS_DB_PATH, PROC_STATE_PATH
from core import db as trade_db
from core.connections import ConnectionManager, DEFAULT_STATE
from core.engine_base import EngineRuntime
from core import proc
from core.ops import HealthLedger, atomic_write_json, runtime_health
from core.risk import RiskGateConfig, RiskState, check_gates
from core.ui import FundingScanner, PortfolioMonitor


def test_proc_registry_stays_in_sync_with_config_registry():
    assert set(proc.ENGINES) == set(registry.PROC_ENGINES)
    for key, meta in registry.PROC_ENGINES.items():
        assert proc.ENGINES[key]["script"] == meta["script"]
        assert registry.PROC_NAMES[key] == meta["display"]


def test_rooted_paths_contract():
    root = Path(__file__).resolve().parent.parent.parent
    assert DATA_DIR == root / "data"
    assert AURUM_DB_PATH == root / "data" / "aurum.db"
    assert NEXUS_DB_PATH == root / "data" / "nexus.db"
    assert PROC_STATE_PATH == root / "data" / ".aurum_procs.json"
    assert AURUM_JWT_SECRET_PATH == root / "data" / ".secrets" / "jwt_secret.txt"


def test_config_paths_anchored_to_config_dir():
    from config.paths import (
        CONFIG_DIR,
        VPS_CONFIG_PATH,
        PAPER_STATE_PATH,
        ALCHEMY_PARAMS_PATH,
        ALCHEMY_PARAMS_RELOAD_FLAG,
        SITE_CONFIG_PATH,
        CONNECTIONS_STATE_PATH,
    )
    assert VPS_CONFIG_PATH == CONFIG_DIR / "vps.json"
    assert PAPER_STATE_PATH == CONFIG_DIR / "paper_state.json"
    assert ALCHEMY_PARAMS_PATH == CONFIG_DIR / "alchemy_params.json"
    assert ALCHEMY_PARAMS_RELOAD_FLAG == CONFIG_DIR / "alchemy_params.json.reload"
    assert SITE_CONFIG_PATH == CONFIG_DIR / "site.json"
    assert CONNECTIONS_STATE_PATH == CONFIG_DIR / "connections.json"


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


def test_canonical_ops_package_exports_same_runtime_contract():
    from core.ops import EngineRuntime as OpsEngineRuntime

    assert OpsEngineRuntime is EngineRuntime
    assert HealthLedger is runtime_health.__class__
    assert callable(atomic_write_json)


def test_canonical_risk_package_exports_live_gate_types():
    decision = check_gates(
        RiskState(account_equity=1_000.0, open_positions=[]),
        RiskGateConfig(),
    )

    assert decision.severity == "allow"
    assert hasattr(decision, "reason")


def test_canonical_ui_package_exports_dashboard_entrypoints():
    assert PortfolioMonitor.__name__ == "PortfolioMonitor"
    assert FundingScanner.__name__ == "FundingScanner"
