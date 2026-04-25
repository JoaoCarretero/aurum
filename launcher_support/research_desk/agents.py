"""Identidade canonica dos 5 operativos AI do Research Desk.

UUIDs vem da instancia Paperclip local da AURUM Research Desk
(company id c2ccbb97-bda1-45db-ab53-5b2bb63962ee). Sao IDs estaveis
— se o Paperclip for recriado, atualizar aqui.

Estrutura de cada AgentIdentity:
  key        — identifier interno funcional uppercase
              (RESEARCH, REVIEW, BUILD, CURATE, AUDIT)
  uuid       — Paperclip agent id
  role       — cargo na mesa (Research Analyst, Risk Reviewer, ...)
  archetype  — legacy label kept for API compatibility; now operational scope
  stone      — legacy label kept for API compatibility; now artifact scope
  tagline    — frase curta que vai no card
  typeface   — hint de fonte distintiva (Sprint 2 aplica)

Fonte de caminhos de filesystem de cada agente (specs, reviews, etc) —
essas constantes sao usadas pelo artifact_scanner.py.

Historia: antes de 2026-04-24 os operativos tinham nomes archetipicos
(SCRYER/ARBITER/ARTIFEX/CURATOR/ORACLE). Renomeados para functional
Bloomberg-style pra consistencia com o resto do launcher (AMBER/HL2
palette + minimal functional UI). Archetype fica nos metadados como
flavor; key e o identifier operacional.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentIdentity:
    key: str
    uuid: str
    role: str
    archetype: str
    stone: str
    tagline: str
    typeface: str
    artifact_dir: str  # caminho relativo ao repo root, ou "" se nao tem dir


RESEARCH = AgentIdentity(
    key="RESEARCH",
    uuid="c28d2218-9941-4c44-a318-6d9d2df129d2",
    role="Research Analyst",
    archetype="Market Intel",
    stone="Specs",
    tagline="Anomaly scans and research specs.",
    typeface="mono",
    artifact_dir="docs/specs",
)

REVIEW = AgentIdentity(
    key="REVIEW",
    uuid="246a2339-1cb1-4732-b588-16764487d05d",
    role="Risk & Code Reviewer",
    archetype="Validation",
    stone="Reviews",
    tagline="Hypothesis and code review gates.",
    typeface="mono",
    artifact_dir="docs/reviews",
)

BUILD = AgentIdentity(
    key="BUILD",
    uuid="34d56cfa-014e-4b20-903d-96f4ae5c2b05",
    role="Quant Developer",
    archetype="Implementation",
    stone="Branches",
    tagline="Feature and engine implementation.",
    typeface="mono",
    artifact_dir="",  # usa branches experiment/* no git, nao dir fixo
)

CURATE = AgentIdentity(
    key="CURATE",
    uuid="a424432d-be6d-44ea-80e3-f9b2c3b9d534",
    role="Repository Curator",
    archetype="Knowledge Base",
    stone="Docs",
    tagline="Docs, audits and session memory.",
    typeface="mono",
    artifact_dir="docs/audits",
)

AUDIT = AgentIdentity(
    key="AUDIT",
    uuid="2f790a10-55d1-4b4c-9a48-30db1e4cb73b",
    role="Integrity Auditor",
    archetype="Integrity Gate",
    stone="Audits",
    tagline="Final evidence-based validation.",
    typeface="mono",
    artifact_dir="docs/audits/engines",
)


AGENTS: tuple[AgentIdentity, ...] = (RESEARCH, REVIEW, BUILD, CURATE, AUDIT)
BY_KEY: dict[str, AgentIdentity] = {a.key: a for a in AGENTS}
BY_UUID: dict[str, AgentIdentity] = {a.uuid: a for a in AGENTS}


# Hard budget caps per agent in cents (USD). Values from AGENTS.md §4
# (RESEARCH $80 / REVIEW $100 / BUILD $250 / CURATE $50 / AUDIT $80).
#
# Acts as a defensive ceiling: when Paperclip's `monthly_budget_cents`
# returns 0 (server hasn't been configured / API shape drift), the
# cockpit still has a budget to enforce against. Without this fallback,
# `cap_text` shows "—" and the agent appears unbounded — alerts become
# theatre.
#
# The enforcer (screens/research_desk.py:_enforce_budget_caps) calls
# `pause_agent` when `spent_cents >= effective_cap` AND the agent is
# not already paused — idempotent. Joao can edit caps via Paperclip
# server config; client-side floor stays as the safety net.
HARD_BUDGETS_CENTS: dict[str, int] = {
    "RESEARCH": 8000,
    "REVIEW": 10000,
    "BUILD": 25000,
    "CURATE": 5000,
    "AUDIT": 8000,
}


def effective_budget_cents(agent: AgentIdentity, server_cap: int) -> int:
    """Return the active cap for budget enforcement.

    Prefers the server value when non-zero (Joao's authoritative knob).
    Falls back to HARD_BUDGETS_CENTS when server returns 0 — typical
    when a fresh Paperclip instance hasn't seeded budgets yet.
    """
    if server_cap > 0:
        return server_cap
    return HARD_BUDGETS_CENTS.get(agent.key, 0)


# ── Paperclip company / project context ───────────────────────────
COMPANY_ID = "c2ccbb97-bda1-45db-ab53-5b2bb63962ee"
PROJECT_ID = "b1830f57-5bfa-4071-992b-8a0dc3b5ed90"
GOAL_ID = "415e3107-9599-4ba0-88d2-8c38f9e6f34e"

# Paperclip server endpoint (modo local_trusted, sem token)
PAPERCLIP_BASE_URL = "http://127.0.0.1:3100"

# Path para AGENTS.md de cada agente (editor inline — Sprint 3)
AGENTS_MD_TEMPLATE = (
    "{home}/.paperclip/instances/default/companies/{company_id}"
    "/agents/{agent_uuid}/instructions/AGENTS.md"
)

# Path para settings json por nome de agente (Sprint 3)
AGENT_SETTINGS_TEMPLATE = (
    "{home}/.paperclip/agent-configs/{name_lower}-settings.json"
)
