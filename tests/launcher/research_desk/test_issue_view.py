"""Tests do shape_issue — sem Tk."""
from __future__ import annotations

import datetime as dt

from launcher_support.research_desk.issue_view import (
    IssueView,
    filter_active,
    shape_issue,
)


def test_shape_issue_basic() -> None:
    view = shape_issue({
        "id": "i1",
        "title": "Spec KEPOS",
        "status": "in_progress",
        "priority": "high",
        "assigned_agent_id": "uuid-1",
        "updated_at": "2026-04-23T17:00:00Z",
    })
    assert view.id == "i1"
    assert view.title == "Spec KEPOS"
    assert view.status == "in_progress"
    assert view.priority == "high"
    assert view.assignee_uuid == "uuid-1"
    assert view.is_active is True


def test_shape_issue_missing_fields_uses_defaults() -> None:
    view = shape_issue({})
    assert view.id == ""
    assert view.title == "(sem titulo)"
    assert view.status == "unknown"
    assert view.priority == "medium"
    assert view.assignee_uuid == ""
    assert view.is_active is False


def test_shape_issue_fallback_keys() -> None:
    view = shape_issue({
        "id": "i2",
        "summary": "fallback title",
        "state": "TODO",
        "prio": "LOW",
        "assignee_id": "uuid-2",
    })
    assert view.title == "fallback title"
    assert view.status == "todo"
    assert view.priority == "low"
    assert view.assignee_uuid == "uuid-2"
    assert view.is_active is True


def test_title_truncated_to_120() -> None:
    long = "x" * 300
    view = shape_issue({"title": long})
    assert len(view.title) == 120


def test_is_active_only_for_todo_or_in_progress() -> None:
    assert shape_issue({"status": "in_progress"}).is_active
    assert shape_issue({"status": "todo"}).is_active
    assert not shape_issue({"status": "done"}).is_active
    assert not shape_issue({"status": "blocked"}).is_active


def test_age_formats() -> None:
    now = dt.datetime.now(dt.timezone.utc)
    ten_min = (now - dt.timedelta(minutes=10)).isoformat()
    view = shape_issue({"updated_at": ten_min})
    assert view.age.endswith("atras")
    assert "min" in view.age


def test_age_invalid_returns_dash() -> None:
    assert shape_issue({"updated_at": "not-a-date"}).age == "—"


def test_filter_active_sorts_in_progress_first() -> None:
    issues = [
        {"id": "a", "status": "todo", "priority": "high"},
        {"id": "b", "status": "in_progress", "priority": "low"},
        {"id": "c", "status": "in_progress", "priority": "high"},
        {"id": "d", "status": "done", "priority": "high"},
    ]
    actives = filter_active(issues)
    assert [v.id for v in actives] == ["c", "b", "a"]
    # done fica de fora
    assert all(v.is_active for v in actives)


def test_filter_active_handles_empty() -> None:
    assert filter_active([]) == []


def test_filter_active_drops_unknown_status() -> None:
    issues = [{"id": "x", "status": "cancelled"}]
    assert filter_active(issues) == []


def test_issueview_frozen() -> None:
    view = shape_issue({"id": "x"})
    try:
        view.id = "y"  # type: ignore[misc]
    except AttributeError:
        return
    raise AssertionError("IssueView deveria ser frozen")
