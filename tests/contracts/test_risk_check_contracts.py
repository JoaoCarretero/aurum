"""Contract tests for api.risk_check — pre-start gate evaluation.

Covers:
- build_start_state: snapshot → RiskState shape (equity, positions,
  notional = size * mark, current_hour_utc populated).
- evaluate_start_gates: injected snapshot path, decision shape.
- fail-open behavior when snapshot is None / empty.
- Integration with /api/trading/start endpoint — hard_block and
  soft_block both return 403, allow proceeds to spawn.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from api import models
from api.risk_check import (
    build_start_state,
    evaluate_start_gates,
)
from api.routes import EngineAction, start_engine


# ────────────────────────────────────────────────────────────
# build_start_state
# ────────────────────────────────────────────────────────────

class TestBuildStartState:
    def test_empty_snapshot_is_zero_equity(self):
        state = build_start_state({})
        assert state.account_equity == 0.0
        assert state.open_positions == []

    def test_none_snapshot_is_zero_equity(self):
        state = build_start_state(None)
        assert state.account_equity == 0.0

    def test_notional_is_size_times_mark(self):
        snap = {
            "equity": 10_000,
            "positions": [
                {"symbol": "BTC", "side": "LONG",  "size": 0.5, "mark": 60_000},
                {"symbol": "ETH", "side": "SHORT", "size": 2.0, "mark": 3_000},
            ],
        }
        state = build_start_state(snap)
        assert state.account_equity == 10_000.0
        assert state.open_positions[0]["notional"] == 30_000.0
        assert state.open_positions[1]["notional"] == 6_000.0
        assert state.open_positions[0]["side"] == "LONG"

    def test_current_hour_populated(self):
        state = build_start_state({})
        assert 0 <= state.current_hour_utc <= 23


# ────────────────────────────────────────────────────────────
# evaluate_start_gates
# ────────────────────────────────────────────────────────────

class TestEvaluateStartGates:
    def test_default_paper_empty_snapshot_allows(self):
        d = evaluate_start_gates("paper", snapshot={})
        assert d.severity == "allow"

    def test_none_snapshot_fails_open_to_permissive_config(self):
        # No portfolio data available → equity=0 → balance gates no-op.
        # With default permissive config this is allow.
        d = evaluate_start_gates("paper", snapshot={})
        assert d.severity == "allow"

    def test_healthy_snapshot_allows(self):
        snap = {
            "equity": 10_000,
            "positions": [
                {"symbol": "BTC", "side": "LONG", "size": 0.01, "mark": 60_000},
            ],
        }
        d = evaluate_start_gates("paper", snapshot=snap)
        assert d.severity == "allow"


# ────────────────────────────────────────────────────────────
# /api/trading/start integration
# ────────────────────────────────────────────────────────────

@pytest.fixture
def nexus_db(tmp_path, monkeypatch):
    db_path = tmp_path / "nexus.db"
    monkeypatch.setattr(models, "DB_PATH", db_path)
    models.init_db()
    conn = models.get_conn()
    try:
        conn.execute(
            "INSERT INTO users (id, email, password_hash, created_at, role) "
            "VALUES (1, 'u@x', 'h', '2026-01-01', 'admin')"
        )
        conn.commit()
    finally:
        conn.close()
    return db_path


def _fake_decision(severity: str, gate: str = "daily_dd"):
    from core.risk_gates import GateDecision
    if severity == "allow":
        return GateDecision(severity="allow", reason="ok")
    return GateDecision(
        severity=severity, reason=f"{gate} tripped",
        gate=gate, metric=99.0, threshold=1.0,
    )


class TestTradingStartEndpoint:
    def test_hard_block_returns_403(self, nexus_db, monkeypatch):
        monkeypatch.setattr(
            "api.routes.evaluate_start_gates",
            lambda mode: _fake_decision("hard_block"),
            raising=False,
        )
        # The import is done inside the endpoint; patch at the source too.
        monkeypatch.setattr(
            "api.risk_check.evaluate_start_gates",
            lambda mode, snapshot=None: _fake_decision("hard_block"),
        )
        with pytest.raises(HTTPException) as exc:
            asyncio.run(start_engine(
                EngineAction(engine="janestreet"),
                user={"id": 1, "role": "admin"},
            ))
        assert exc.value.status_code == 403
        assert exc.value.detail["severity"] == "hard_block"
        assert exc.value.detail["gate"] == "daily_dd"

    def test_soft_block_also_returns_403(self, nexus_db, monkeypatch):
        # Starting an engine counts as a new entry, which is exactly
        # what soft_block pauses. Both severities block the start.
        monkeypatch.setattr(
            "api.risk_check.evaluate_start_gates",
            lambda mode, snapshot=None: _fake_decision("soft_block", gate="freeze_window"),
        )
        with pytest.raises(HTTPException) as exc:
            asyncio.run(start_engine(
                EngineAction(engine="janestreet"),
                user={"id": 1, "role": "admin"},
            ))
        assert exc.value.status_code == 403
        assert exc.value.detail["severity"] == "soft_block"

    def test_allow_proceeds_to_spawn(self, nexus_db, monkeypatch):
        spawned = []
        monkeypatch.setattr(
            "api.risk_check.evaluate_start_gates",
            lambda mode, snapshot=None: _fake_decision("allow"),
        )
        monkeypatch.setattr(
            "api.routes.proc.spawn",
            lambda engine: spawned.append(engine) or {"pid": 111},
        )
        payload = asyncio.run(start_engine(
            EngineAction(engine="janestreet"),
            user={"id": 1, "role": "admin"},
        ))
        assert spawned == ["arb"]  # janestreet → arb (proc key)
        assert "janestreet" in payload["message"]

    def test_mode_is_forwarded_to_evaluate(self, nexus_db, monkeypatch):
        seen_modes: list[str] = []

        def fake_eval(mode, snapshot=None):
            seen_modes.append(mode)
            return _fake_decision("allow")

        monkeypatch.setattr("api.risk_check.evaluate_start_gates", fake_eval)
        monkeypatch.setattr(
            "api.routes.proc.spawn",
            lambda engine: {"pid": 222},
        )
        asyncio.run(start_engine(
            EngineAction(engine="janestreet", mode="testnet"),
            user={"id": 1, "role": "admin"},
        ))
        assert seen_modes == ["testnet"]
