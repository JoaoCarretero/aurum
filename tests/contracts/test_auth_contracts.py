from __future__ import annotations

import importlib

import pytest
from fastapi import HTTPException

import api.auth as auth
from config import paths as config_paths


class _FakeWebSocket:
    def __init__(self, *, authorization: str = "", token: str = ""):
        self.headers = {}
        if authorization:
            self.headers["authorization"] = authorization
        self.query_params = {}
        if token:
            self.query_params["token"] = token


def test_missing_env_secret_persists_file_backed_key(tmp_path, monkeypatch):
    monkeypatch.delenv("AURUM_JWT_SECRET", raising=False)
    monkeypatch.setattr(config_paths, "AURUM_JWT_SECRET_PATH", tmp_path / "jwt_secret.txt")
    reloaded = importlib.reload(auth)
    try:
        assert reloaded.SECRET_KEY_SOURCE in {"file", "file-generated"}
        assert reloaded.SECRET_KEY == (tmp_path / "jwt_secret.txt").read_text(encoding="utf-8").strip()
        reloaded_again = importlib.reload(reloaded)
        assert reloaded_again.SECRET_KEY == reloaded.SECRET_KEY
    finally:
        importlib.reload(reloaded)


def test_insecure_default_secret_is_rejected_for_runtime_use(tmp_path, monkeypatch):
    sentinel = auth._INSECURE_DEFAULT_SECRET
    monkeypatch.setenv("AURUM_JWT_SECRET", sentinel)
    monkeypatch.setattr(config_paths, "AURUM_JWT_SECRET_PATH", tmp_path / "jwt_secret_fallback.txt")
    reloaded = importlib.reload(auth)
    try:
        assert reloaded.SECRET_KEY_SOURCE == "file-generated"
        assert reloaded.SECRET_KEY != sentinel
    finally:
        importlib.reload(reloaded)


def test_secret_bootstrap_fails_closed_when_persistence_fails(tmp_path, monkeypatch):
    from core import persistence

    monkeypatch.delenv("AURUM_JWT_SECRET", raising=False)
    monkeypatch.setattr(config_paths, "AURUM_JWT_SECRET_PATH", tmp_path / "jwt_secret_fail.txt")
    original_write = persistence.atomic_write_text

    def _fail_write(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("core.persistence.atomic_write_text", _fail_write)
    with pytest.raises(RuntimeError, match="refusing insecure startup"):
        importlib.reload(auth)
    monkeypatch.setattr("core.persistence.atomic_write_text", original_write)
    importlib.reload(auth)


def test_authenticate_websocket_accepts_bearer_header(monkeypatch):
    monkeypatch.setattr(auth, "get_current_admin_from_token", lambda token: {"id": 1, "role": "admin", "token": token})
    user = auth.authenticate_websocket(
        _FakeWebSocket(authorization="Bearer abc123"),
        require_admin_role=True,
    )
    assert user["token"] == "abc123"


def test_authenticate_websocket_rejects_query_token(monkeypatch):
    monkeypatch.setattr(auth, "get_current_user_from_token", lambda token: {"id": 2, "role": "viewer", "token": token})
    with pytest.raises(HTTPException) as exc:
        auth.authenticate_websocket(_FakeWebSocket(token="qwerty"))
    assert exc.value.status_code == 401


def test_authenticate_websocket_rejects_missing_token():
    with pytest.raises(HTTPException) as exc:
        auth.authenticate_websocket(_FakeWebSocket(), require_admin_role=True)
    assert exc.value.status_code == 401
