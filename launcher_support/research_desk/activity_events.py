"""Activity feed event merger.

Combines Paperclip issues and local artifacts into one chronological stream.
This module is pure and UI-free; widgets decide how much visual treatment each
event receives.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from launcher_support.research_desk.agents import BY_UUID, AgentIdentity
from launcher_support.research_desk.artifact_scanner import ArtifactEntry


ACTION_SPEC = "spec"
ACTION_REVIEW = "review"
ACTION_AUDIT = "audit"
ACTION_BRANCH = "branch"
ACTION_ISSUE_CREATED = "issue_created"
ACTION_ISSUE_CLOSED = "issue_closed"
ACTION_ISSUE_PROGRESS = "issue_progress"


@dataclass(frozen=True)
class ActivityEvent:
    """One event in the unified Research Desk timeline."""
    agent_key: str
    action: str
    title: str
    when_epoch: float
    detail: str
    payload: object


_ICONS: dict[str, str] = {
    ACTION_SPEC: "SP",
    ACTION_REVIEW: "RV",
    ACTION_AUDIT: "AU",
    ACTION_BRANCH: "BR",
    ACTION_ISSUE_CREATED: "NT",
    ACTION_ISSUE_CLOSED: "CL",
    ACTION_ISSUE_PROGRESS: "IP",
}


def action_icon(action: str) -> str:
    """Return a compact ASCII code for non-UI callers."""
    return _ICONS.get(action, ".")


def action_label(action: str) -> str:
    return {
        ACTION_SPEC: "SPEC",
        ACTION_REVIEW: "REVIEW",
        ACTION_AUDIT: "AUDIT",
        ACTION_BRANCH: "BRANCH",
        ACTION_ISSUE_CREATED: "NEW TICKET",
        ACTION_ISSUE_CLOSED: "CLOSED",
        ACTION_ISSUE_PROGRESS: "PROGRESS",
    }.get(action, action.upper())


def merge_events(
    *,
    issues: list[dict],
    artifacts: list[ArtifactEntry],
    limit: int = 100,
) -> list[ActivityEvent]:
    """Combine, sort descending by timestamp, and truncate."""
    events: list[ActivityEvent] = []
    events.extend(_events_from_artifacts(artifacts))
    events.extend(_events_from_issues(issues))
    events.sort(key=lambda e: e.when_epoch, reverse=True)
    return events[:limit]


_ARTIFACT_KIND_TO_ACTION: dict[str, str] = {
    "spec": ACTION_SPEC,
    "review": ACTION_REVIEW,
    "audit": ACTION_AUDIT,
    "branch": ACTION_BRANCH,
}


def _events_from_artifacts(artifacts: list[ArtifactEntry]) -> list[ActivityEvent]:
    out: list[ActivityEvent] = []
    for a in artifacts:
        action = _ARTIFACT_KIND_TO_ACTION.get(a.kind, a.kind)
        out.append(ActivityEvent(
            agent_key=a.agent_key,
            action=action,
            title=a.title,
            when_epoch=a.mtime_epoch,
            detail=f"in {_dir_label(a)}",
            payload=a,
        ))
    return out


def _dir_label(entry: ArtifactEntry) -> str:
    if entry.kind == "branch":
        return "git experiment/*"
    path = entry.path.replace("\\", "/")
    if "/" in path:
        return path.rsplit("/", 1)[0]
    return path


def _events_from_issues(issues: list[dict]) -> list[ActivityEvent]:
    out: list[ActivityEvent] = []
    for issue in issues:
        action, when = _classify_issue(issue)
        if action is None or when is None:
            continue
        identity = _issue_agent(issue)
        title = _str(issue, "title", "summary") or "(sem titulo)"
        out.append(ActivityEvent(
            agent_key=identity.key if identity is not None else "",
            action=action,
            title=title[:120],
            when_epoch=when,
            detail=_issue_detail(issue),
            payload=issue,
        ))
    return out


def _classify_issue(issue: dict) -> tuple[str | None, float | None]:
    status = (_str(issue, "status", "state") or "").lower()
    created_iso = _str(issue, "created_at", "createdAt")
    updated_iso = _str(issue, "updated_at", "updatedAt")
    closed_iso = _str(issue, "closed_at", "closedAt", "resolved_at")

    if status in ("done", "cancelled", "closed") and closed_iso:
        return ACTION_ISSUE_CLOSED, _parse(closed_iso)
    if closed_iso:
        return ACTION_ISSUE_CLOSED, _parse(closed_iso)
    if status == "in_progress" and updated_iso and updated_iso != created_iso:
        return ACTION_ISSUE_PROGRESS, _parse(updated_iso)
    if created_iso:
        return ACTION_ISSUE_CREATED, _parse(created_iso)
    if updated_iso:
        return ACTION_ISSUE_CREATED, _parse(updated_iso)
    return None, None


def _issue_detail(issue: dict) -> str:
    priority = _str(issue, "priority", "prio") or "medium"
    return f"[{priority}]"


def _issue_agent(issue: dict) -> AgentIdentity | None:
    for key in ("assigned_agent_id", "assignee_id", "agent_id"):
        val = issue.get(key)
        if isinstance(val, str) and val:
            return BY_UUID.get(val)
    return None


def _str(d: dict, *keys: str) -> str:
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _parse(iso: str) -> float | None:
    if not iso:
        return None
    try:
        cleaned = iso.replace("Z", "+00:00")
        moment = dt.datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    return moment.timestamp()
