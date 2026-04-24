from __future__ import annotations

import json

import pytest

from core.key_store import KeyStore, KeyStoreLockedError, load_runtime_keys


SAMPLE_KEYS = {
    "testnet": {"api_key": "TK_abcd1234", "api_secret": "secret_xyz"},
    "telegram": {"bot_token": "123:ABC", "chat_id": "555"},
}


def test_runtime_loads_plaintext_when_encrypted_file_missing(tmp_path, monkeypatch):
    pt_path = tmp_path / "keys.json"
    enc_path = tmp_path / "keys.json.enc"
    pt_path.write_text(json.dumps(SAMPLE_KEYS), encoding="utf-8")
    monkeypatch.delenv("AURUM_KEY_PASSWORD", raising=False)
    monkeypatch.delenv("AURUM_ALLOW_PLAINTEXT_KEYS", raising=False)
    assert load_runtime_keys(plaintext_path=pt_path, encrypted_path=enc_path) == SAMPLE_KEYS


def test_runtime_requires_password_when_encrypted_store_exists(tmp_path, monkeypatch):
    pt_path = tmp_path / "keys.json"
    enc_path = tmp_path / "keys.json.enc"
    pt_path.write_text(json.dumps(SAMPLE_KEYS), encoding="utf-8")
    KeyStore(plaintext_path=pt_path, encrypted_path=enc_path).encrypt_from_plaintext("pw")
    monkeypatch.delenv("AURUM_KEY_PASSWORD", raising=False)
    monkeypatch.delenv("AURUM_ALLOW_PLAINTEXT_KEYS", raising=False)
    with pytest.raises(KeyStoreLockedError):
        load_runtime_keys(plaintext_path=pt_path, encrypted_path=enc_path)


def test_runtime_unlocks_encrypted_store_with_password(tmp_path, monkeypatch):
    pt_path = tmp_path / "keys.json"
    enc_path = tmp_path / "keys.json.enc"
    pt_path.write_text(json.dumps(SAMPLE_KEYS), encoding="utf-8")
    KeyStore(plaintext_path=pt_path, encrypted_path=enc_path).encrypt_from_plaintext("pw")
    monkeypatch.setenv("AURUM_KEY_PASSWORD", "pw")
    monkeypatch.delenv("AURUM_ALLOW_PLAINTEXT_KEYS", raising=False)
    assert load_runtime_keys(plaintext_path=pt_path, encrypted_path=enc_path) == SAMPLE_KEYS
