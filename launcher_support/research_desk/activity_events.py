"""Event merger pro ACTIVITY FEED — combina 3 fontes em timeline unica.

Fontes:
  - issues (/api/companies/:id/issues) — eventos de criacao + mudanca
    de status
  - artifacts (artifact_scanner.scan_artifacts) — criacao/modificacao
    de .md em docs/{specs,reviews,audits}
  - branches (artifact_scanner — kind='branch') — novas branches
    experiment/*

Funcao pura: entrada = 3 listas raw, saida = lista ActivityEvent
ordenada por timestamp DESC. Testavel sem Tk.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from launcher_support.research_desk.agents import BY_UUID, AgentIdentity
from launcher_support.research_desk.artifact_scanner import ArtifactEntry


# Action kinds
ACTION_SPEC = "spec"
ACTION_REVIEW = "review"
ACTION_AUDIT = "audit"
ACTION_BRANCH = "branch"
ACTION_ISSUE_CREATED = "issue_created"
ACTION_ISSUE_CLOSED = "issue_closed"
ACTION_ISSUE_PROGRESS = "issue_progress"


@dataclass(frozen=True)
class ActivityEvent:
    """Um evento no timeline. agent_key pode ser "" se nao atribuido."""
    agent_key: str
    action: str         # constant acima
    title: str          # titulo curto (ex: "spec-phi-fib")
    when_epoch: float
    detail: str         # subtitulo (ex: "in docs/specs")
    payload: object     # ArtifactEntry ou dict de issue — pra navegacao


# Icone unicode por acao — escolhidos pra render consistente em Consolas
_ICONS: dict[str, str] = {
    ACTION_SPEC: "◧",
    ACTION_REVIEW: "◨",
    ACTION_AUDIT: "▣",
    ACTION_BRANCH: "├",
    ACTION_ISSUE_CREATED: "○",
    ACTION_ISSUE_CLOSED: "●",
    ACTION_ISSUE_PROGRESS: "◐",
}


def action_icon(action: str) -> str:
    return _ICONS.get(action, "·")


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
    """Combina + ordena DESC + corta."""
    events: list[ActivityEvent] = []
    events.extend(_events_from_artifacts(artifacts))
    events.extend(_events_from_issues(issues))
    events.sort(key=lambda e: e.when_epoch, reverse=True)
    return events[:limit]


# ── Artifact -> events ────────────────────────────────────────────


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
        detail = f"in {_dir_label(a)}"
        out.append(ActivityEvent(
            agent_key=a.agent_key,
            action=action,
            title=a.title,
            when_epoch=a.mtime_epoch,
            detail=detail,
            payload=a,
        ))
    return out


def _dir_label(entry: ArtifactEntry) -> str:
    if entry.kind == "branch":
        return "git experiment/*"
    # extract dir from path
    path = entry.path.replace("\\", "/")
    if "/" in path:
        return path.rsplit("/", 1)[0]
    return path


# ── Issues -> events ──────────────────────────────────────────────


def _events_from_issues(issues: list[dict]) -> list[ActivityEvent]:
    out: list[ActivityEvent] = []
    for i in issues:
        action, when = _classify_issue(i)
        if action is None or when is None:
            continue
        identity = _issue_agent(i)
        agent_key = identity.key if identity is not None else ""
        title = _str(i, "title", "summary") or "(sem titulo)"
        detail = _issue_detail(i)
        out.append(ActivityEvent(
            agent_key=agent_key,
            action=action,
            title=title[:120],
            when_epoch=when,
            detail=detail,
            payload=i,
        ))
    return out


def _classify_issue(issue: dict) -> tuple[str | None, float | None]:
    """Classifica uma issue em (action, timestamp). Nenhum -> skip."""
    status = (_str(issue, "status", "state") or "").lower()
    created_iso = _str(issue, "created_at", "createdAt")
    updated_iso = _str(issue, "updated_at", "updatedAt")
    closed_iso = _str(issue, "closed_at", "closedAt", "resolved_at")

    # Se tem closed_at + status done/cancelled -> CLOSED
    if status in ("done", "cancelled", "closed") and closed_iso:
        return ACTION_ISSUE_CLOSED, _parse(closed_iso)
    # Se tem closed_at mas sem status terminal, usa closed_at
    if closed_iso:
        return ACTION_ISSUE_CLOSED, _parse(closed_iso)
    # Se status in_progress + updated_at > created_at
    if status == "in_progress" and updated_iso and updated_iso != created_iso:
        return ACTION_ISSUE_PROGRESS, _parse(updated_iso)
    # Default: criacao
    if created_iso:
        return ACTION_ISSUE_CREATED, _parse(created_iso)
    if updated_iso:
        return ACTION_ISSUE_CREATED, _parse(updated_iso)
    return None, None


def _issue_detail(issue: dict) -> str:
    priority = _str(issue, "priority", "prio") or "medium"
    return f"[{priority}]"


def _issue_agent(issue: dict) -> AgentIdentity | None:
    uuid = ""
    for key in ("assigned_agent_id", "assignee_id", "agent_id"):
        val = issue.get(key)
        if isinstance(val, str) and val:
            uuid = val
            break
    return BY_UUID.get(uuid)


# ── Low-level helpers ─────────────────────────────────────────────


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
