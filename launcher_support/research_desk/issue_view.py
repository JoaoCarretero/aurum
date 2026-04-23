"""Shape Paperclip issue dicts -> view-models para pipeline/artifact panels.

Issue fields canonicos (Paperclip API):
  id, title, description, status, priority, assigned_agent_id,
  created_at, updated_at

Status values: "todo" | "in_progress" | "done" | "blocked" | "cancelled"
Priority: "low" | "medium" | "high"

Testado via tests/launcher/research_desk/test_issue_view.py.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass


# Status que contam como "pipeline ativo" — aparecem no painel
ACTIVE_STATUSES: frozenset[str] = frozenset({"todo", "in_progress"})


@dataclass(frozen=True)
class IssueView:
    """View-model imutavel pra uma issue no pipeline."""
    id: str
    title: str
    status: str            # "todo" | "in_progress" | "done" | ...
    priority: str          # "low" | "medium" | "high"
    assignee_uuid: str     # "" se nao atribuida
    age: str               # "2h atras" / "3d atras" / "agora"
    is_active: bool        # True se em todo/in_progress


def shape_issue(issue: dict) -> IssueView:
    iid = str(issue.get("id") or "")
    title = _str_field(issue, "title", "summary")
    if not title:
        title = "(sem titulo)"
    status = _str_field(issue, "status", "state").lower() or "unknown"
    priority = _str_field(issue, "priority", "prio").lower() or "medium"
    assignee = _str_field(issue, "assigned_agent_id", "assignee_id", "agent_id")

    iso = _str_field(issue, "updated_at", "created_at")
    age = _age(iso)

    return IssueView(
        id=iid,
        title=title[:120],
        status=status,
        priority=priority,
        assignee_uuid=assignee,
        age=age,
        is_active=status in ACTIVE_STATUSES,
    )


def filter_active(issues: list[dict]) -> list[IssueView]:
    """Shape + filtra so as ativas, ordenadas por priority desc + age."""
    views = [shape_issue(i) for i in issues]
    active = [v for v in views if v.is_active]
    # Ordena: in_progress antes de todo; dentro de cada, high > medium > low
    active.sort(key=_sort_key)
    return active


_PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}
_STATUS_RANK = {"in_progress": 0, "todo": 1}


def _sort_key(v: IssueView) -> tuple[int, int, str]:
    return (
        _STATUS_RANK.get(v.status, 99),
        _PRIORITY_RANK.get(v.priority, 99),
        v.id,
    )


def _str_field(issue: dict, *keys: str) -> str:
    for k in keys:
        val = issue.get(k)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _age(iso: str) -> str:
    if not iso:
        return "—"
    try:
        cleaned = iso.replace("Z", "+00:00")
        moment = dt.datetime.fromisoformat(cleaned)
    except ValueError:
        return "—"
    now = dt.datetime.now(dt.timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    delta = now - moment
    total = int(delta.total_seconds())
    if total < 0:
        return "agora"
    if total < 60:
        return f"{total}s atras"
    if total < 3600:
        return f"{total // 60}min atras"
    if total < 86400:
        return f"{total // 3600}h atras"
    return f"{total // 86400}d atras"
