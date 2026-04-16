from __future__ import annotations

import importlib

import pytest
from fastapi import HTTPException

import api.auth as auth


class _FakeWebSocket:
    def __init__(self, *, authorization: str = "", token: str = ""):
        self.headers = {}
        if authorization:
            self.headers["authorization"] = authorization
        self.query_params = {}
        if token:
            self.query_params["token"] = token


def test_missing_env_secret_uses_ephemeral_key(monkeypatch):
    monkeypatch.delenv("AURUM_JWT_SECRET", raising=False)
    reloaded = importlib.reload(auth)
    try:
        assert reloaded.SECRET_KEY_SOURCE == "ephemeral"
        assert reloaded.SECRET_KEY != "aurum-dev-secret-change-in-production"
    finally:
        importlib.reload(reloaded)


def test_insecure_default_secret_is_rejected_for_runtime_use(monkeypatch):
    monkeypatch.setenv("AURUM_JWT_SECRET", "aurum-dev-secret-change-in-production")
    reloaded = importlib.reload(auth)
    try:
        assert reloaded.SECRET_KEY_SOURCE == "ephemeral"
        assert reloaded.SECRET_KEY != "aurum-dev-secret-change-in-production"
    finally:
        importlib.reload(reloaded)


def test_authenticate_websocket_accepts_bearer_header(monkeypatch):
    monkeypatch.setattr(auth, "get_current_admin_from_token", lambda token: {"id": 1, "role": "admin", "token": token})
    user = auth.authenticate_websocket(
        _FakeWebSocket(authorization="Bearer abc123"),
        require_admin_role=True,
    )
    assert user["token"] == "abc123"


def test_authenticate_websocket_accepts_query_token(monkeypatch):
    monkeypatch.setattr(auth, "get_current_user_from_token", lambda token: {"id": 2, "role": "viewer", "token": token})
    user = auth.authenticate_websocket(_FakeWebSocket(token="qwerty"))
    assert user["token"] == "qwerty"


def test_authenticate_websocket_rejects_missing_token():
    with pytest.raises(HTTPException) as exc:
        auth.authenticate_websocket(_FakeWebSocket(), require_admin_role=True)
    assert exc.value.status_code == 401
