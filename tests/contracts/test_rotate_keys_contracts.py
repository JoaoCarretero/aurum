"""Contract tests for tools.rotate_keys — key rotation flow.

Covers:
- Happy path: rotates a mode, backup created, atomic write applied
- Validation: empty / whitespace / short keys rejected
- Unknown mode rejected
- Other mode blocks left untouched (macro_brain / telegram / other mode)
- Missing keys.json bootstraps a new file with no backup
- Malformed keys.json surfaces an IO error
"""
from __future__ import annotations

import json

import pytest

from tools.rotate_keys import rotate, _VALID_MODES


# Valid length test credentials (> 20 chars)
GOOD_KEY    = "a" * 32
GOOD_SECRET = "b" * 40


# ────────────────────────────────────────────────────────────
# Happy path
# ────────────────────────────────────────────────────────────

class TestRotateHappyPath:
    def test_rotates_testnet_block(self, tmp_path):
        keys = tmp_path / "keys.json"
        keys.write_text(json.dumps({
            "testnet": {"api_key": "OLD_KEY", "api_secret": "OLD_SEC"},
        }), encoding="utf-8")

        code, backup = rotate("testnet", GOOD_KEY, GOOD_SECRET, keys)

        assert code == 0
        assert backup is not None and backup.exists()
        written = json.loads(keys.read_text(encoding="utf-8"))
        assert written["testnet"]["api_key"]    == GOOD_KEY
        assert written["testnet"]["api_secret"] == GOOD_SECRET

    def test_backup_preserves_old_content(self, tmp_path):
        keys = tmp_path / "keys.json"
        original = {"testnet": {"api_key": "OLD_KEY", "api_secret": "OLD_SEC"}}
        keys.write_text(json.dumps(original), encoding="utf-8")

        _, backup = rotate("testnet", GOOD_KEY, GOOD_SECRET, keys)

        assert backup is not None
        backed_up = json.loads(backup.read_text(encoding="utf-8"))
        assert backed_up == original

    def test_other_mode_blocks_untouched(self, tmp_path):
        keys = tmp_path / "keys.json"
        keys.write_text(json.dumps({
            "demo":    {"api_key": "DEMO_K", "api_secret": "DEMO_S"},
            "testnet": {"api_key": "TEST_K", "api_secret": "TEST_S"},
            "live":    {"api_key": "LIVE_K", "api_secret": "LIVE_S"},
            "macro_brain": {"fred_api_key": "F", "newsapi_key": "N"},
            "telegram":    {"bot_token": "T", "chat_id": "C"},
        }), encoding="utf-8")

        rotate("testnet", GOOD_KEY, GOOD_SECRET, keys)

        written = json.loads(keys.read_text(encoding="utf-8"))
        assert written["demo"]["api_key"] == "DEMO_K"
        assert written["live"]["api_key"] == "LIVE_K"
        assert written["macro_brain"]["fred_api_key"] == "F"
        assert written["telegram"]["bot_token"] == "T"
        # Only testnet changed
        assert written["testnet"]["api_key"] == GOOD_KEY

    def test_missing_file_bootstraps_with_no_backup(self, tmp_path):
        keys = tmp_path / "keys.json"
        assert not keys.exists()

        code, backup = rotate("testnet", GOOD_KEY, GOOD_SECRET, keys)

        assert code == 0
        assert backup is None   # nothing to back up
        assert keys.exists()
        assert json.loads(keys.read_text())["testnet"]["api_key"] == GOOD_KEY


# ────────────────────────────────────────────────────────────
# Validation
# ────────────────────────────────────────────────────────────

class TestRotateValidation:
    def test_rejects_unknown_mode(self, tmp_path):
        keys = tmp_path / "keys.json"
        code, _ = rotate("mainnet", GOOD_KEY, GOOD_SECRET, keys)
        assert code == 3
        assert not keys.exists()

    def test_rejects_empty_key(self, tmp_path):
        keys = tmp_path / "keys.json"
        code, _ = rotate("testnet", "", GOOD_SECRET, keys)
        assert code == 1

    def test_rejects_whitespace_padded(self, tmp_path):
        keys = tmp_path / "keys.json"
        code, _ = rotate("testnet", "  " + GOOD_KEY, GOOD_SECRET, keys)
        assert code == 1

    def test_rejects_too_short(self, tmp_path):
        keys = tmp_path / "keys.json"
        code, _ = rotate("testnet", "short_key", GOOD_SECRET, keys)
        assert code == 1

    def test_validation_failure_does_not_touch_file(self, tmp_path):
        keys = tmp_path / "keys.json"
        keys.write_text(json.dumps({"testnet": {"api_key": "OLD"}}),
                        encoding="utf-8")
        rotate("testnet", "", GOOD_SECRET, keys)
        # Still has the original content
        assert json.loads(keys.read_text())["testnet"]["api_key"] == "OLD"


# ────────────────────────────────────────────────────────────
# Error paths
# ────────────────────────────────────────────────────────────

class TestRotateErrors:
    def test_malformed_keys_json_returns_io_error(self, tmp_path):
        keys = tmp_path / "keys.json"
        keys.write_text("{ not valid json", encoding="utf-8")
        code, backup = rotate("testnet", GOOD_KEY, GOOD_SECRET, keys)
        assert code == 2
        assert backup is None


# ────────────────────────────────────────────────────────────
# Mode surface
# ────────────────────────────────────────────────────────────

class TestValidModes:
    def test_expected_modes(self):
        # If we add/remove modes, this test is the reminder to update docs.
        assert set(_VALID_MODES) == {"demo", "testnet", "live"}
