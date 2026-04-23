"""Shape Paperclip agent dicts into view-models para agent cards.

Paperclip retorna JSON solto; a UI so deve consumir shapes canonicos. Este
modulo centraliza a traducao + tolerancia a ausencia de campo (agent que
nunca rodou ainda nao tem current_issue, etc).

Testado via tests/launcher/research_desk/test_agent_view.py — sem Tk.
"""
from __future__ import annotations

from dataclasses import dataclass

from launcher_support.research_desk.paperclip_client import (
    agent_budget_cents,
    agent_spent_cents,
    format_usd_from_cents,
)


@dataclass(frozen=True)
class AgentView:
    """View-model para um agent card. Imutavel por design."""
    status_text: str        # "running" / "idle" / "paused" / "offline"
    status_color_key: str   # "running" | "idle" | "paused" | "offline" pra UI switch
    budget_text: str        # "$0.50 / $10.00"
    budget_pct: float       # 0..1
    last_ticket: str        # titulo da issue atual ou "—"
    last_ticket_age: str    # "2h atras" / "—"

    @property
    def is_offline(self) -> bool:
        return self.status_color_key == "offline"


_OFFLINE = AgentView(
    status_text="offline",
    status_color_key="offline",
    budget_text="—",
    budget_pct=0.0,
    last_ticket="—",
    last_ticket_age="—",
)


def offline_view() -> AgentView:
    """View a mostrar quando Paperclip ta down ou agente nao retornou."""
    return _OFFLINE


def shape_agent(agent: dict | None) -> AgentView:
    """Converte dict raw do Paperclip em AgentView renderizavel.

    Tolerante a schemas variados — fields ausentes caem pra '-'.
    """
    if not agent:
        return _OFFLINE

    status_text, status_key = _extract_status(agent)
    budget_text, budget_pct = _extract_budget(agent)
    last_title, last_age = _extract_current_issue(agent)

    return AgentView(
        status_text=status_text,
        status_color_key=status_key,
        budget_text=budget_text,
        budget_pct=budget_pct,
        last_ticket=last_title,
        last_ticket_age=last_age,
    )


def _extract_status(agent: dict) -> tuple[str, str]:
    """Normaliza status + paused flag para (display_text, semantic_key)."""
    if bool(agent.get("paused")):
        return "paused", "paused"
    raw = agent.get("status") or agent.get("state") or ""
    if isinstance(raw, str):
        norm = raw.lower().strip()
    else:
        norm = ""
    if norm in ("running", "busy", "working"):
        return "running", "running"
    if norm in ("idle", "waiting"):
        return "idle", "idle"
    if norm in ("paused", "stopped"):
        return "paused", "paused"
    if norm == "error":
        return "error", "error"
    if not norm:
        return "idle", "idle"
    return norm, "idle"


def _extract_budget(agent: dict) -> tuple[str, float]:
    spent = agent_spent_cents(agent)
    cap = agent_budget_cents(agent)
    text = f"{format_usd_from_cents(spent)} / {format_usd_from_cents(cap)}"
    pct = (spent / cap) if cap > 0 else 0.0
    # Clamp pct a [0, 1] pra UI nao estourar se spent > budget
    pct = max(0.0, min(1.0, pct))
    return text, pct


def _extract_current_issue(agent: dict) -> tuple[str, str]:
    """Pega a issue em progresso ou a ultima conhecida."""
    issue = agent.get("current_issue") or agent.get("last_issue")
    if not isinstance(issue, dict):
        return "—", "—"
    title = issue.get("title") or issue.get("summary") or ""
    if not isinstance(title, str) or not title.strip():
        title = "—"
    age = _format_age_from_iso(
        issue.get("updated_at") or issue.get("created_at") or ""
    )
    return title.strip()[:60], age


def _format_age_from_iso(iso: str) -> str:
    """'2026-04-23T18:00:00Z' -> 'N min ago' / '3h ago' etc. '-' se invalido."""
    if not iso or not isinstance(iso, str):
        return "—"
    import datetime as dt

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


def shape_agents_by_uuid(agents: list[dict]) -> dict[str, AgentView]:
    """Indexa lista de agents (do /api/companies/:id/agents) por UUID."""
    out: dict[str, AgentView] = {}
    for a in agents:
        uuid = a.get("id") or a.get("uuid")
        if isinstance(uuid, str):
            out[uuid] = shape_agent(a)
    return out
