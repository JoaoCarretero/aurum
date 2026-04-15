"""Contract tests for core.failure_policy — policy taxonomy.

Tiny module: 1 frozen dataclass + 4 module-level constants. These
tests are the tripwire if someone renames a policy, changes a log
level, or flips should_raise — all of which would silently change
the resilience behavior of callers without breaking imports.
"""
from __future__ import annotations

import dataclasses

import pytest

from core.failure_policy import (
    BEST_EFFORT,
    DEGRADE_AND_LOG,
    MUST_FAIL_LOUD,
    SKIP_AND_CONTINUE,
    FailurePolicy,
)


ALL_POLICIES = [MUST_FAIL_LOUD, BEST_EFFORT, DEGRADE_AND_LOG, SKIP_AND_CONTINUE]


class TestFailurePolicyDataclass:
    def test_is_frozen(self):
        with pytest.raises(dataclasses.FrozenInstanceError):
            MUST_FAIL_LOUD.name = "changed"  # type: ignore[misc]

    def test_shape_fields(self):
        fields = {f.name for f in dataclasses.fields(FailurePolicy)}
        assert fields == {"name", "should_raise", "log_level", "count_in_health"}


class TestPolicyNames:
    def test_names_unique(self):
        names = [p.name for p in ALL_POLICIES]
        assert len(set(names)) == len(names)

    def test_expected_canonical_names(self):
        # Rename check — the name string is the audit key consumed
        # by health events and other modules.
        assert MUST_FAIL_LOUD.name    == "must_fail_loud"
        assert BEST_EFFORT.name       == "best_effort"
        assert DEGRADE_AND_LOG.name   == "degrade_and_log"
        assert SKIP_AND_CONTINUE.name == "skip_and_continue"


class TestRaiseSemantics:
    def test_only_must_fail_loud_raises(self):
        raising = [p for p in ALL_POLICIES if p.should_raise]
        assert raising == [MUST_FAIL_LOUD]


class TestLogLevels:
    def test_log_levels_are_standard(self):
        valid = {"debug", "info", "warning", "error", "critical"}
        for p in ALL_POLICIES:
            assert p.log_level in valid, f"{p.name} has bad log_level={p.log_level!r}"

    def test_severity_ordering_matches_intent(self):
        # Loudness ordering: raise > warning > info > debug.
        # This encodes the design intent so a future "tone down"
        # refactor needs a conscious update here.
        assert MUST_FAIL_LOUD.log_level    == "error"
        assert DEGRADE_AND_LOG.log_level   == "warning"
        assert SKIP_AND_CONTINUE.log_level == "info"
        assert BEST_EFFORT.log_level       == "debug"


class TestHealthCounting:
    def test_all_policies_counted_in_health(self):
        # Every failure path should show up in observability, regardless
        # of how loudly it surfaces — that's the whole point of the
        # taxonomy. If this ever flips False, it's a deliberate signal
        # loss and should require a test update.
        for p in ALL_POLICIES:
            assert p.count_in_health is True, f"{p.name} skips health"
