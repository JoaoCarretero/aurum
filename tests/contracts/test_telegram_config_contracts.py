"""Contract tests for bot.telegram._load_telegram_config.

Audit 2026-04-25 Lane 5 finding: bot/telegram.py loaded keys.json with
raw `with open(_KEYS_PATH) as f: cfg = json.load(f)`, bypassing the
encrypted-store path of core.risk.key_store.load_runtime_keys. MEMORY §2
forbids that pattern in new code.

These tests pin the post-fix behavior:
- Plaintext path still works for existing operator setups.
- Allowed-user-ids falls back to chat_id when omitted.
- Explicit allowed_user_ids supersedes the default.
- Missing telegram block returns the empty tuple.
- Corrupt keys.json returns the empty tuple (records health event).
- Loader delegates to load_runtime_keys (regression pin).
"""
from __future__ import annotations

import json

import pytest

from bot.telegram import _load_telegram_config


def _patch_paths(monkeypatch, plaintext, encrypted):
    monkeypatch.setattr("bot.telegram._PLAINTEXT_KEYS", plaintext)
    monkeypatch.setattr("bot.telegram._ENCRYPTED_KEYS", encrypted)


def test_default_allowed_user_ids_falls_back_to_chat_id(tmp_path, monkeypatch):
    pt = tmp_path / "keys.json"
    pt.write_text(json.dumps({"telegram": {"bot_token": "T", "chat_id": "123"}}),
                  encoding="utf-8")
    _patch_paths(monkeypatch, pt, tmp_path / "keys.json.enc")

    token, chat, allowed = _load_telegram_config()
    assert (token, chat, allowed) == ("T", "123", frozenset({"123"}))


def test_explicit_allowed_user_ids_supersedes_chat_id(tmp_path, monkeypatch):
    pt = tmp_path / "keys.json"
    pt.write_text(json.dumps({
        "telegram": {"bot_token": "T", "chat_id": "123",
                     "allowed_user_ids": [999, 888]}
    }), encoding="utf-8")
    _patch_paths(monkeypatch, pt, tmp_path / "keys.json.enc")

    _, _, allowed = _load_telegram_config()
    assert allowed == frozenset({"999", "888"})


def test_missing_telegram_block_returns_empty_tuple(tmp_path, monkeypatch):
    pt = tmp_path / "keys.json"
    pt.write_text(json.dumps({"binance": {"api_key": "x"}}), encoding="utf-8")
    _patch_paths(monkeypatch, pt, tmp_path / "keys.json.enc")

    assert _load_telegram_config() == ("", "", frozenset())


def test_corrupt_keys_falls_back_to_empty_tuple(tmp_path, monkeypatch):
    pt = tmp_path / "keys.json"
    pt.write_text("{not valid json", encoding="utf-8")
    _patch_paths(monkeypatch, pt, tmp_path / "keys.json.enc")

    assert _load_telegram_config() == ("", "", frozenset())


def test_loader_delegates_to_load_runtime_keys(monkeypatch):
    """Pin: telegram routes secrets through load_runtime_keys.

    Prevents regression to raw json.load(open(...)) — MEMORY §2.
    """
    captured: dict[str, object] = {}

    def fake_loader(*, plaintext_path=None, encrypted_path=None, **_kw):
        captured["plaintext_path"] = plaintext_path
        captured["encrypted_path"] = encrypted_path
        return {"telegram": {"bot_token": "X", "chat_id": "Y"}}

    monkeypatch.setattr("bot.telegram.load_runtime_keys", fake_loader)
    _load_telegram_config()
    assert captured["plaintext_path"] is not None
    assert captured["encrypted_path"] is not None
