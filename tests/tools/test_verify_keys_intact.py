from __future__ import annotations

import json

from tools.maintenance.verify_keys_intact import run_check


def _healthy_payload() -> dict:
    return {
        "vps_ssh": {"host": "37.60.254.151", "key_path": "C:/keys/id_ed25519"},
        "cockpit_api": {"read_token": "read-token", "admin_token": "admin-token"},
        "telegram": {"bot_token": "bot-token", "chat_id": "123"},
        "demo": {"api_key": "COLE_AQUI", "api_secret": "COLE_AQUI"},
        "testnet": {"api_key": "test-key", "api_secret": "test-secret"},
        "live": {"api_key": "live-key", "api_secret": "live-secret"},
        "macro_brain": {"fred_api_key": "fred", "newsapi_key": "news"},
    }


def test_run_check_reports_missing_file(tmp_path):
    code, problems = run_check(path=tmp_path / "keys.json")

    assert code == 2
    assert any("does not exist" in problem for problem in problems)


def test_run_check_flags_critical_placeholder(tmp_path):
    path = tmp_path / "keys.json"
    payload = _healthy_payload()
    payload["telegram"]["bot_token"] = "COLE_AQUI"
    path.write_text(json.dumps(payload), encoding="utf-8")

    code, problems = run_check(path=path)

    assert code == 1
    assert "telegram.bot_token" in problems[0]


def test_run_check_allows_noncritical_placeholder_without_strict(tmp_path):
    path = tmp_path / "keys.json"
    path.write_text(json.dumps(_healthy_payload()), encoding="utf-8")

    code, problems = run_check(path=path, strict=False)

    assert code == 0
    assert problems == []


def test_run_check_strict_flags_exchange_placeholders(tmp_path):
    path = tmp_path / "keys.json"
    path.write_text(json.dumps(_healthy_payload()), encoding="utf-8")

    code, problems = run_check(path=path, strict=True)

    assert code == 1
    assert any("demo.api_key" in problem for problem in problems)
