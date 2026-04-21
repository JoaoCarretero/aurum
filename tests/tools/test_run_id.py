"""Unit tests for tools/operations/run_id.py.

Verifies label sanitization rules and RUN_ID composition for multi-
instance runs (spec 2026-04-20-multi-instance-runs-design.md).
"""
from datetime import datetime, timezone

import pytest

from tools.operations.run_id import build_run_id, sanitize_label


class TestSanitizeLabel:
    def test_none_returns_none(self):
        assert sanitize_label(None) is None

    def test_empty_string_returns_none(self):
        assert sanitize_label("") is None

    def test_whitespace_only_returns_none(self):
        assert sanitize_label("   ") is None

    def test_simple_label_unchanged(self):
        assert sanitize_label("kelly5-10k") == "kelly5-10k"

    def test_uppercase_lowered(self):
        assert sanitize_label("Kelly5") == "kelly5"

    def test_spaces_become_dashes(self):
        assert sanitize_label("kelly 5 10k") == "kelly-5-10k"

    def test_special_chars_become_dashes(self):
        assert sanitize_label("kelly#5$10k") == "kelly-5-10k"

    def test_multiple_adjacent_special_chars_collapse(self):
        assert sanitize_label("kelly   5") == "kelly-5"
        assert sanitize_label("kelly!!!5") == "kelly-5"

    def test_trim_leading_and_trailing_dashes(self):
        assert sanitize_label("-kelly-") == "kelly"
        assert sanitize_label("---kelly---") == "kelly"

    def test_truncate_at_40_chars(self):
        long = "a" * 50
        assert sanitize_label(long) == "a" * 40

    def test_truncate_then_trim_trailing_dash(self):
        # 39 chars 'a' + '-' + 'x' → after trunc to 40: 'a'*39 + '-' → trim → 'a'*39
        raw = "a" * 39 + "-" + "xxxxx"
        result = sanitize_label(raw)
        assert result == "a" * 39

    def test_only_special_returns_none(self):
        assert sanitize_label("!!!@@@###") is None

    def test_unicode_chars_become_dashes(self):
        # Accented chars are not [a-z0-9-], so they get replaced
        assert sanitize_label("café") == "caf"

    def test_preserves_digits(self):
        assert sanitize_label("bridgewater-v2") == "bridgewater-v2"


class TestBuildRunId:
    def test_without_label_uses_seconds_precision(self):
        ts = datetime(2026, 4, 20, 16, 54, 32, tzinfo=timezone.utc)
        assert build_run_id(ts=ts) == "2026-04-20_165432"

    def test_without_label_none_arg(self):
        ts = datetime(2026, 4, 20, 16, 54, 32, tzinfo=timezone.utc)
        assert build_run_id(ts=ts, label=None) == "2026-04-20_165432"

    def test_with_label_appends_slug(self):
        ts = datetime(2026, 4, 20, 16, 54, 32, tzinfo=timezone.utc)
        assert build_run_id(ts=ts, label="kelly5-10k") == "2026-04-20_165432_kelly5-10k"

    def test_with_label_sanitizes(self):
        ts = datetime(2026, 4, 20, 16, 54, 32, tzinfo=timezone.utc)
        assert build_run_id(ts=ts, label="Kelly 5") == "2026-04-20_165432_kelly-5"

    def test_empty_label_treated_as_none(self):
        ts = datetime(2026, 4, 20, 16, 54, 32, tzinfo=timezone.utc)
        assert build_run_id(ts=ts, label="") == "2026-04-20_165432"

    def test_label_of_only_special_chars_omitted(self):
        ts = datetime(2026, 4, 20, 16, 54, 32, tzinfo=timezone.utc)
        # After sanitize, "!!!" → None, so no suffix
        assert build_run_id(ts=ts, label="!!!") == "2026-04-20_165432"

    def test_default_ts_uses_now(self):
        # Two consecutive calls within same second should match
        run_id = build_run_id()
        # Format check: YYYY-MM-DD_HHMMSS[_label]
        parts = run_id.split("_")
        assert len(parts) == 2
        assert len(parts[0]) == 10  # YYYY-MM-DD
        assert len(parts[1]) == 6  # HHMMSS

    def test_naive_ts_accepted(self):
        ts = datetime(2026, 4, 20, 16, 54, 32)
        assert build_run_id(ts=ts) == "2026-04-20_165432"

    def test_with_mode_paper_appends_p_suffix(self):
        ts = datetime(2026, 4, 20, 16, 54, 32, tzinfo=timezone.utc)
        assert build_run_id(ts=ts, mode="paper") == "2026-04-20_165432p"

    def test_with_mode_shadow_appends_s_suffix(self):
        ts = datetime(2026, 4, 20, 16, 54, 32, tzinfo=timezone.utc)
        assert build_run_id(ts=ts, mode="shadow") == "2026-04-20_165432s"

    def test_mode_none_keeps_plain_id(self):
        ts = datetime(2026, 4, 20, 16, 54, 32, tzinfo=timezone.utc)
        assert build_run_id(ts=ts, mode=None) == "2026-04-20_165432"

    def test_mode_with_label_both_applied(self):
        ts = datetime(2026, 4, 20, 16, 54, 32, tzinfo=timezone.utc)
        assert build_run_id(ts=ts, mode="paper", label="kelly5") == \
            "2026-04-20_165432p_kelly5"

    def test_unknown_mode_ignored(self):
        ts = datetime(2026, 4, 20, 16, 54, 32, tzinfo=timezone.utc)
        # Unknown mode string → no suffix added, falls through as if mode=None.
        assert build_run_id(ts=ts, mode="nonsense") == "2026-04-20_165432"
