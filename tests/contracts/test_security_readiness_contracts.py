from __future__ import annotations

import os

from tools.maintenance.security_readiness import run_check


def test_errors_when_no_key_store_present(tmp_path, monkeypatch):
    monkeypatch.delenv("AURUM_KEY_PASSWORD", raising=False)
    monkeypatch.delenv("AURUM_ALLOW_PLAINTEXT_KEYS", raising=False)
    monkeypatch.delenv("MT5_VNC_PASSWORD", raising=False)
    errors, warnings = run_check(root=tmp_path)
    assert any("no key store found" in item for item in errors)
    assert any("MT5_VNC_PASSWORD" in item for item in warnings)


def test_encrypted_store_requires_password(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "keys.json.enc").write_text("{}", encoding="utf-8")
    monkeypatch.delenv("AURUM_KEY_PASSWORD", raising=False)
    monkeypatch.delenv("AURUM_ALLOW_PLAINTEXT_KEYS", raising=False)
    errors, _warnings = run_check(root=tmp_path)
    assert any("AURUM_KEY_PASSWORD" in item for item in errors)


def test_plaintext_store_requires_explicit_opt_in(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "keys.json").write_text("{}", encoding="utf-8")
    monkeypatch.delenv("AURUM_ALLOW_PLAINTEXT_KEYS", raising=False)
    monkeypatch.delenv("AURUM_KEY_PASSWORD", raising=False)
    errors, _warnings = run_check(root=tmp_path)
    assert any("AURUM_ALLOW_PLAINTEXT_KEYS=1" in item for item in errors)


def test_plaintext_store_can_be_allowed_for_controlled_migration(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "keys.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("AURUM_ALLOW_PLAINTEXT_KEYS", "1")
    monkeypatch.setenv("MT5_VNC_PASSWORD", "pw")
    errors, warnings = run_check(root=tmp_path)
    assert errors == []
    assert any("plaintext key fallback enabled" in item for item in warnings)


def test_encrypted_store_with_password_passes(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "keys.json.enc").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("AURUM_KEY_PASSWORD", "pw")
    monkeypatch.setenv("MT5_VNC_PASSWORD", "pw")
    errors, warnings = run_check(root=tmp_path)
    assert errors == []
    assert warnings == []
