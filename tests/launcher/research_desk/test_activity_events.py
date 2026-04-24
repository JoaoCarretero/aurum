"""Tests do event merger — funcoes puras sem Tk."""
from __future__ import annotations

import datetime as dt
import time

from launcher_support.research_desk.activity_events import (
    ACTION_AUDIT,
    ACTION_BRANCH,
    ACTION_ISSUE_CLOSED,
    ACTION_ISSUE_CREATED,
    ACTION_ISSUE_PROGRESS,
    ACTION_REVIEW,
    ACTION_SPEC,
    ActivityEvent,
    action_icon,
    action_label,
    merge_events,
)
from launcher_support.research_desk.agents import REVIEW, RESEARCH
from launcher_support.research_desk.artifact_scanner import ArtifactEntry


def _mk_artifact(
    agent_key: str = "RESEARCH",
    kind: str = "spec",
    mtime: float | None = None,
    title: str = "x",
) -> ArtifactEntry:
    return ArtifactEntry(
        agent_key=agent_key, kind=kind, title=title,
        path=f"docs/{kind}s/{title}.md",
        mtime_epoch=mtime if mtime is not None else time.time(),
        is_markdown=True,
    )


def _iso_minus(minutes: int) -> str:
    when = dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=minutes)
    return when.isoformat()


def test_action_icon_has_entry_per_kind() -> None:
    for action in (
        ACTION_SPEC, ACTION_REVIEW, ACTION_AUDIT, ACTION_BRANCH,
        ACTION_ISSUE_CREATED, ACTION_ISSUE_CLOSED, ACTION_ISSUE_PROGRESS,
    ):
        icon = action_icon(action)
        assert isinstance(icon, str) and len(icon) >= 1


def test_action_icon_unknown_returns_dot() -> None:
    assert action_icon("nope") == "·"


def test_action_label_all_uppercase() -> None:
    assert action_label(ACTION_SPEC) == "SPEC"
    assert action_label(ACTION_ISSUE_CLOSED) == "CLOSED"
    assert action_label("unknown-kind") == "UNKNOWN-KIND"


def test_merge_empty_returns_empty() -> None:
    assert merge_events(issues=[], artifacts=[]) == []


def test_merge_from_artifacts_only() -> None:
    t1 = time.time() - 100
    t2 = time.time() - 50
    artifacts = [
        _mk_artifact(mtime=t1, title="old"),
        _mk_artifact(mtime=t2, title="new"),
    ]
    events = merge_events(issues=[], artifacts=artifacts)
    assert len(events) == 2
    # Ordenado DESC (mais recente primeiro)
    assert events[0].title == "new"
    assert events[1].title == "old"
    for e in events:
        assert e.action == ACTION_SPEC
        assert e.agent_key == "RESEARCH"


def test_merge_artifact_kind_to_action() -> None:
    artifacts = [
        _mk_artifact(kind="spec"),
        _mk_artifact(kind="review", agent_key="REVIEW"),
        _mk_artifact(kind="audit", agent_key="CURATE"),
        _mk_artifact(kind="branch", agent_key="BUILD"),
    ]
    events = merge_events(issues=[], artifacts=artifacts)
    actions = {e.action for e in events}
    assert actions == {ACTION_SPEC, ACTION_REVIEW, ACTION_AUDIT, ACTION_BRANCH}


def test_merge_issue_created_event() -> None:
    issues = [{
        "id": "i1",
        "title": "Spec X",
        "status": "todo",
        "priority": "high",
        "assigned_agent_id": RESEARCH.uuid,
        "created_at": _iso_minus(30),
    }]
    events = merge_events(issues=issues, artifacts=[])
    assert len(events) == 1
    assert events[0].action == ACTION_ISSUE_CREATED
    assert events[0].agent_key == "RESEARCH"
    assert "high" in events[0].detail


def test_merge_issue_closed_uses_closed_at() -> None:
    issues = [{
        "id": "i1",
        "title": "Done issue",
        "status": "done",
        "priority": "medium",
        "assigned_agent_id": REVIEW.uuid,
        "created_at": _iso_minus(120),
        "closed_at": _iso_minus(5),
    }]
    events = merge_events(issues=issues, artifacts=[])
    assert events[0].action == ACTION_ISSUE_CLOSED
    # Usa closed_at (5min ago) nao created_at (120min ago)
    age = time.time() - events[0].when_epoch
    assert age < 600  # < 10min


def test_merge_issue_in_progress_after_create() -> None:
    issues = [{
        "id": "i1", "title": "Working", "status": "in_progress",
        "assigned_agent_id": RESEARCH.uuid,
        "created_at": _iso_minus(100),
        "updated_at": _iso_minus(10),
    }]
    events = merge_events(issues=issues, artifacts=[])
    assert events[0].action == ACTION_ISSUE_PROGRESS


def test_merge_unassigned_issue_has_empty_agent_key() -> None:
    issues = [{
        "id": "i1", "title": "Orphan", "status": "todo",
        "created_at": _iso_minus(5),
    }]
    events = merge_events(issues=issues, artifacts=[])
    assert events[0].agent_key == ""


def test_merge_invalid_iso_skipped() -> None:
    issues = [
        {"id": "i1", "title": "x", "created_at": "not-a-date"},
        {"id": "i2", "title": "y"},  # nenhum timestamp
    ]
    events = merge_events(issues=issues, artifacts=[])
    assert events == []


def test_merge_respects_limit() -> None:
    artifacts = [_mk_artifact(title=f"a{i}") for i in range(100)]
    events = merge_events(issues=[], artifacts=artifacts, limit=10)
    assert len(events) == 10


def test_merge_sorts_combined_sources_desc() -> None:
    old_artifact = _mk_artifact(mtime=time.time() - 3600, title="old_art")
    new_issue_ts = _iso_minus(5)
    issues = [{
        "id": "i1", "title": "recent_issue",
        "created_at": new_issue_ts,
        "assigned_agent_id": RESEARCH.uuid,
    }]
    events = merge_events(issues=issues, artifacts=[old_artifact])
    # Issue recente vem antes do artefato de 1h atras
    assert events[0].title == "recent_issue"
    assert events[1].title == "old_art"


def test_artifact_detail_shows_dir() -> None:
    art = _mk_artifact(kind="spec", title="phi-fib")
    events = merge_events(issues=[], artifacts=[art])
    assert "docs/specs" in events[0].detail


def test_branch_detail_git_label() -> None:
    art = ArtifactEntry(
        agent_key="BUILD", kind="branch", title="phi-fib",
        path="experiment/phi-fib", mtime_epoch=time.time(),
        is_markdown=False,
    )
    events = merge_events(issues=[], artifacts=[art])
    assert "git" in events[0].detail.lower() or "experiment" in events[0].detail


def test_activityevent_frozen() -> None:
    event = ActivityEvent(
        agent_key="RESEARCH", action=ACTION_SPEC, title="x",
        when_epoch=0.0, detail="", payload=None,
    )
    try:
        event.title = "y"  # type: ignore[misc]
    except AttributeError:
        return
    raise AssertionError("ActivityEvent deveria ser frozen")
