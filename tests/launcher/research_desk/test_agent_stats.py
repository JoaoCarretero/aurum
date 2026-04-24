"""Tests do agent_stats aggregator — funcoes puras sem Tk."""
from __future__ import annotations

import datetime as dt
import time
from pathlib import Path

from launcher_support.research_desk.agent_stats import (
    agent_dict_for,
    ensure_path,
    filter_artifacts_for,
    filter_issues_for,
    shape_stats,
)
from launcher_support.research_desk.agents import BY_KEY, RESEARCH
from launcher_support.research_desk.artifact_scanner import ArtifactEntry


def _make_artifact(
    agent_key: str = "RESEARCH",
    mtime: float | None = None,
    title: str = "spec-x",
) -> ArtifactEntry:
    return ArtifactEntry(
        agent_key=agent_key,
        kind="spec",
        title=title,
        path=f"docs/specs/{title}.md",
        mtime_epoch=mtime if mtime is not None else time.time(),
        is_markdown=True,
    )


def test_shape_stats_counts_tickets_by_status() -> None:
    issues = [
        {"assigned_agent_id": RESEARCH.uuid, "status": "done"},
        {"assigned_agent_id": RESEARCH.uuid, "status": "done"},
        {"assigned_agent_id": RESEARCH.uuid, "status": "in_progress"},
        {"assigned_agent_id": RESEARCH.uuid, "status": "todo"},
        {"assigned_agent_id": "other", "status": "done"},  # nao conta
    ]
    stats = shape_stats(
        agent=RESEARCH, agent_dict=None,
        issues=issues, artifacts=[],
    )
    assert stats.tickets_done == 2
    assert stats.tickets_active == 2


def test_shape_stats_artifact_count_and_label() -> None:
    artifacts = [_make_artifact() for _ in range(5)]
    stats = shape_stats(
        agent=RESEARCH, agent_dict=None,
        issues=[], artifacts=artifacts,
    )
    assert stats.artifacts_total == 5
    assert stats.artifact_kind_label == "specs"


def test_shape_stats_label_per_agent() -> None:
    labels = {}
    for key in ("RESEARCH", "REVIEW", "BUILD", "CURATE"):
        stats = shape_stats(
            agent=BY_KEY[key], agent_dict=None, issues=[], artifacts=[],
        )
        labels[key] = stats.artifact_kind_label
    assert labels == {
        "RESEARCH": "specs",
        "REVIEW": "reviews",
        "BUILD": "branches",
        "CURATE": "audits",
    }


def test_shape_stats_budget_from_agent_dict() -> None:
    agent_dict = {
        "monthly_spent_cents": 1234,
        "monthly_budget_cents": 5000,
    }
    stats = shape_stats(
        agent=RESEARCH, agent_dict=agent_dict,
        issues=[], artifacts=[],
    )
    assert stats.monthly_spent == "$12.34"
    assert stats.monthly_cap == "$50.00"
    assert 0.24 < stats.monthly_pct < 0.25


def test_shape_stats_budget_missing_when_offline() -> None:
    stats = shape_stats(
        agent=RESEARCH, agent_dict=None,
        issues=[], artifacts=[],
    )
    assert stats.monthly_spent == "—"
    assert stats.monthly_cap == "—"
    assert stats.monthly_pct == 0.0


def test_birthday_from_agent_dict_created_at() -> None:
    agent_dict = {"created_at": "2026-04-19T10:00:00Z"}
    stats = shape_stats(
        agent=RESEARCH, agent_dict=agent_dict,
        issues=[], artifacts=[],
    )
    assert stats.birthday == "2026-04-19"
    assert stats.days_active.endswith("d")


def test_birthday_fallback_to_oldest_artifact() -> None:
    old_mtime = time.time() - 5 * 86400
    new_mtime = time.time() - 1 * 86400
    artifacts = [
        _make_artifact(mtime=new_mtime, title="new"),
        _make_artifact(mtime=old_mtime, title="old"),
    ]
    stats = shape_stats(
        agent=RESEARCH, agent_dict=None,
        issues=[], artifacts=artifacts,
    )
    # Birthday deve usar o mais antigo (old_mtime)
    expected_date = dt.datetime.fromtimestamp(old_mtime, dt.timezone.utc).date().isoformat()
    assert stats.birthday == expected_date


def test_birthday_dash_when_no_source() -> None:
    stats = shape_stats(
        agent=RESEARCH, agent_dict=None,
        issues=[], artifacts=[],
    )
    assert stats.birthday == "—"
    assert stats.days_active == "—"


def test_filter_artifacts_for_agent_key() -> None:
    mixed = [
        _make_artifact(agent_key="RESEARCH", title="a"),
        _make_artifact(agent_key="REVIEW", title="b"),
        _make_artifact(agent_key="RESEARCH", title="c"),
    ]
    out = filter_artifacts_for(RESEARCH, mixed)
    assert {a.title for a in out} == {"a", "c"}


def test_filter_issues_for_agent_uuid() -> None:
    issues = [
        {"assigned_agent_id": RESEARCH.uuid, "title": "s1"},
        {"assignee_id": "other-uuid", "title": "other"},
        {"agent_id": RESEARCH.uuid, "title": "s2"},
    ]
    out = filter_issues_for(RESEARCH, issues)
    titles = {i.get("title") for i in out}
    assert titles == {"s1", "s2"}


def test_agent_dict_for_lookup() -> None:
    agents = [
        {"id": RESEARCH.uuid, "name": "RESEARCH"},
        {"id": "other", "name": "other"},
    ]
    found = agent_dict_for(RESEARCH, agents)
    assert found == {"id": RESEARCH.uuid, "name": "RESEARCH"}


def test_agent_dict_for_missing_returns_none() -> None:
    assert agent_dict_for(RESEARCH, [{"id": "nope"}]) is None
    assert agent_dict_for(RESEARCH, []) is None


def test_ensure_path_coerces() -> None:
    assert isinstance(ensure_path("x/y"), Path)
    assert isinstance(ensure_path(Path(".")), Path)
