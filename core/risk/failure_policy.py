"""Failure policy taxonomy for infrastructure code."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FailurePolicy:
    name: str
    should_raise: bool
    log_level: str
    count_in_health: bool


MUST_FAIL_LOUD = FailurePolicy(
    name="must_fail_loud",
    should_raise=True,
    log_level="error",
    count_in_health=True,
)

BEST_EFFORT = FailurePolicy(
    name="best_effort",
    should_raise=False,
    log_level="debug",
    count_in_health=True,
)

DEGRADE_AND_LOG = FailurePolicy(
    name="degrade_and_log",
    should_raise=False,
    log_level="warning",
    count_in_health=True,
)

SKIP_AND_CONTINUE = FailurePolicy(
    name="skip_and_continue",
    should_raise=False,
    log_level="info",
    count_in_health=True,
)
