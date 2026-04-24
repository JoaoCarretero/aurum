"""Agregador de estatisticas por agente — live via API + filesystem.

Sprint 2.3: o detail view precisa de um statblock com ticket count,
artifact count, cost, birthday. Nao ha SQLite ainda (Sprint 3.4); aqui
derivamos tudo dos sources vivos (Paperclip API + artifact_scanner).

Pure function style: entrada = listas + dict raw; saida = StatsView.
Testavel sem Tk.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

from launcher_support.research_desk.paperclip_client import (
    agent_budget_cents,
    agent_spent_cents,
    format_usd_from_cents,
)
from launcher_support.research_desk.agents import AgentIdentity
from launcher_support.research_desk.artifact_scanner import ArtifactEntry


@dataclass(frozen=True)
class StatsView:
    """View-model pro statblock do detail view."""
    tickets_done: int
    tickets_active: int
    artifacts_total: int
    artifact_kind_label: str  # "specs" / "reviews" / "branches" / "audits"
    monthly_spent: str        # "$12.34"
    monthly_cap: str          # "$50.00"
    monthly_pct: float        # 0..1
    birthday: str             # "2026-04-19" ou "—"
    days_active: str          # "5d" ou "—"


def shape_stats(
    *,
    agent: AgentIdentity,
    agent_dict: dict | None,
    issues: list[dict],
    artifacts: list[ArtifactEntry],
) -> StatsView:
    """Agrega dados dos 3 sources vivos em um StatsView.

    - agent_dict: item raw de /api/companies/:id/agents (None se offline)
    - issues: lista raw de /api/companies/:id/issues
    - artifacts: saida de scan_artifacts filtrada pra este agent_key
    """
    # Ticket counts
    done, active = 0, 0
    for issue in issues:
        if _issue_assignee(issue) != agent.uuid:
            continue
        status = (issue.get("status") or "").lower()
        if status == "done":
            done += 1
        elif status in ("todo", "in_progress"):
            active += 1

    # Artifact count (ja filtrados pelo caller)
    kind_label = _artifact_kind_label(agent)

    # Budget
    if agent_dict:
        spent = agent_spent_cents(agent_dict)
        cap = agent_budget_cents(agent_dict)
        pct = (spent / cap) if cap > 0 else 0.0
        pct = max(0.0, min(1.0, pct))
        spent_text = format_usd_from_cents(spent)
        cap_text = format_usd_from_cents(cap)
    else:
        spent_text = "—"
        cap_text = "—"
        pct = 0.0

    # Birthday: mais antigo artefato conhecido. Se zero artefatos, usa
    # created_at do agent_dict se existir; senao "—".
    birthday, days_active = _compute_birthday(agent_dict, artifacts)

    return StatsView(
        tickets_done=done,
        tickets_active=active,
        artifacts_total=len(artifacts),
        artifact_kind_label=kind_label,
        monthly_spent=spent_text,
        monthly_cap=cap_text,
        monthly_pct=pct,
        birthday=birthday,
        days_active=days_active,
    )


def filter_artifacts_for(
    agent: AgentIdentity, artifacts: list[ArtifactEntry],
) -> list[ArtifactEntry]:
    return [a for a in artifacts if a.agent_key == agent.key]


def filter_issues_for(
    agent: AgentIdentity, issues: list[dict],
) -> list[dict]:
    return [i for i in issues if _issue_assignee(i) == agent.uuid]


def agent_dict_for(
    agent: AgentIdentity, agents_raw: list[dict],
) -> dict | None:
    for a in agents_raw:
        aid = a.get("id") or a.get("uuid")
        if aid == agent.uuid:
            return a
    return None


# ── Helpers ───────────────────────────────────────────────────────


def _issue_assignee(issue: dict) -> str:
    for key in ("assigned_agent_id", "assignee_id", "agent_id"):
        val = issue.get(key)
        if isinstance(val, str):
            return val
    return ""


def _artifact_kind_label(agent: AgentIdentity) -> str:
    return {
        "RESEARCH": "specs",
        "REVIEW": "reviews",
        "BUILD": "branches",
        "CURATE": "audits",
        "AUDIT": "audits",
    }.get(agent.key, "artifacts")


def _compute_birthday(
    agent_dict: dict | None, artifacts: list[ArtifactEntry],
) -> tuple[str, str]:
    """Retorna (birthday_iso_date, days_active_text)."""
    # 1. Prefere created_at do agent_dict se disponivel
    if agent_dict:
        iso = agent_dict.get("created_at") or agent_dict.get("createdAt")
        if isinstance(iso, str) and iso:
            parsed = _parse_iso(iso)
            if parsed is not None:
                return parsed.date().isoformat(), _format_days_since(parsed)

    # 2. Fallback: artefato mais antigo conhecido
    if artifacts:
        oldest = min(
            (a for a in artifacts if a.mtime_epoch > 0),
            key=lambda a: a.mtime_epoch,
            default=None,
        )
        if oldest is not None:
            when = dt.datetime.fromtimestamp(oldest.mtime_epoch, dt.timezone.utc)
            return when.date().isoformat(), _format_days_since(when)

    return "—", "—"


def _parse_iso(iso: str) -> dt.datetime | None:
    try:
        cleaned = iso.replace("Z", "+00:00")
        return dt.datetime.fromisoformat(cleaned)
    except ValueError:
        return None


def _format_days_since(moment: dt.datetime) -> str:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    delta = dt.datetime.now(dt.timezone.utc) - moment
    days = max(0, delta.days)
    return f"{days}d"


def ensure_path(path: object) -> Path:
    """Coerce string/Path -> Path. Usado por detail view."""
    return path if isinstance(path, Path) else Path(str(path))
