from __future__ import annotations

import asyncio
import inspect
import sqlite3

import pytest
from fastapi import HTTPException
from fastapi.params import Depends

from api import models
from api.auth import require_admin
from api.routes import (
    DepositRequest,
    EngineAction,
    WithdrawRequest,
    benchmark,
    deposit,
    equity_curve,
    get_account,
    open_positions,
    per_engine_performance,
    start_engine,
    stop_engine,
    trade_history,
    trading_status,
    withdraw,
)


@pytest.fixture
def nexus_db(tmp_path, monkeypatch):
    db_path = tmp_path / "nexus.db"
    monkeypatch.setattr(models, "DB_PATH", db_path)
    models.init_db()
    conn = models.get_conn()
    try:
        conn.execute(
            "INSERT INTO users (id, email, password_hash, created_at, role) VALUES (1, 'u@x', 'h', '2026-01-01', 'admin')"
        )
        conn.execute(
            "INSERT INTO accounts (user_id, balance, total_deposited, total_withdrawn) VALUES (1, 1000, 400, 50)"
        )
        conn.commit()
    finally:
        conn.close()
    return db_path


def test_pending_deposit_does_not_mutate_balance_or_totals(nexus_db):
    user = {"id": 1, "role": "admin"}
    asyncio.run(deposit(DepositRequest(amount=125.0, method="pix"), user=user))

    conn = models.get_conn()
    try:
        acct = conn.execute(
            "SELECT balance, total_deposited, total_withdrawn FROM accounts WHERE user_id = 1"
        ).fetchone()
        dep = conn.execute(
            "SELECT amount, status FROM deposits WHERE user_id = 1 ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()

    assert dict(acct) == {
        "balance": 1000.0,
        "total_deposited": 400.0,
        "total_withdrawn": 50.0,
    }
    assert dict(dep) == {"amount": 125.0, "status": "pending"}


def test_pending_withdrawal_uses_available_balance_without_mutating_ledger(nexus_db):
    user = {"id": 1, "role": "admin"}
    asyncio.run(withdraw(WithdrawRequest(amount=300.0), user=user))

    conn = models.get_conn()
    try:
        acct = conn.execute(
            "SELECT balance, total_deposited, total_withdrawn FROM accounts WHERE user_id = 1"
        ).fetchone()
        wd = conn.execute(
            "SELECT amount, status FROM withdrawals WHERE user_id = 1 ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()

    assert dict(acct) == {
        "balance": 1000.0,
        "total_deposited": 400.0,
        "total_withdrawn": 50.0,
    }
    assert dict(wd) == {"amount": 300.0, "status": "pending"}


def test_second_pending_withdrawal_respects_reserved_balance(nexus_db):
    user = {"id": 1, "role": "admin"}
    asyncio.run(withdraw(WithdrawRequest(amount=700.0), user=user))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(withdraw(WithdrawRequest(amount=400.0), user=user))
    assert exc.value.status_code == 400
    assert "Insufficient balance" in exc.value.detail


def test_get_account_exposes_pending_and_available_balance(nexus_db):
    user = {"id": 1, "role": "admin"}
    asyncio.run(deposit(DepositRequest(amount=125.0, method="pix"), user=user))
    asyncio.run(withdraw(WithdrawRequest(amount=300.0), user=user))

    payload = asyncio.run(get_account(user=user))

    assert payload["balance"] == 1000.0
    assert payload["available_balance"] == 700.0
    assert payload["pending_deposits"] == 125.0
    assert payload["pending_withdrawals"] == 300.0
    assert payload["pnl"] == 650.0


def test_trading_status_normalizes_proc_and_db_engine_keys(nexus_db, monkeypatch):
    conn = models.get_conn()
    try:
        conn.execute(
            "INSERT INTO engine_state (engine, status, fitness_score) VALUES ('janestreet', 'running', 1.5)"
        )
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(
        "api.routes.proc.list_procs",
        lambda: [{"engine": "arb", "pid": 99, "alive": True, "status": "running", "started": "2026-01-01T00:00:00"}],
    )

    payload = asyncio.run(trading_status(user={"id": 1, "role": "admin"}))
    assert "janestreet" in payload["engines"]
    assert "arb" not in payload["engines"]
    assert payload["engines"]["janestreet"]["process"]["pid"] == 99
    assert payload["engines"]["janestreet"]["db_state"]["engine"] == "janestreet"


def test_start_and_stop_engine_accept_canonical_names(nexus_db, monkeypatch):
    spawned = []
    stopped = []
    monkeypatch.setattr("api.routes.proc.spawn", lambda engine: spawned.append(engine) or {"pid": 321})
    monkeypatch.setattr(
        "api.routes.proc.list_procs",
        lambda: [{"engine": "arb", "pid": 321, "alive": True, "status": "running"}],
    )
    monkeypatch.setattr("api.routes.proc.stop_proc", lambda pid: stopped.append(pid) or True)

    start_payload = asyncio.run(start_engine(EngineAction(engine="janestreet"), user={"id": 1, "role": "admin"}))
    stop_payload = asyncio.run(stop_engine(EngineAction(engine="janestreet"), user={"id": 1, "role": "admin"}))

    assert spawned == ["arb"]
    assert stopped == [321]
    assert "janestreet" in start_payload["message"]
    assert "janestreet" in stop_payload["message"]

    conn = models.get_conn()
    try:
        row = conn.execute("SELECT engine, status FROM engine_state WHERE engine = 'janestreet'").fetchone()
    finally:
        conn.close()
    assert dict(row) == {"engine": "janestreet", "status": "stopped"}


@pytest.mark.parametrize(
    ("fn", "param_name"),
    [
        (trading_status, "user"),
        (open_positions, "user"),
        (trade_history, "user"),
        (equity_curve, "user"),
        (per_engine_performance, "user"),
        (benchmark, "user"),
    ],
)
def test_global_operational_routes_require_admin(fn, param_name):
    dep = inspect.signature(fn).parameters[param_name].default
    assert isinstance(dep, Depends)
    assert dep.dependency is require_admin
