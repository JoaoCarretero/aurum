"""Identidade canonica dos 4 operativos AI do Research Desk.

UUIDs vem da instancia Paperclip local da AURUM Research Desk
(company id c2ccbb97-bda1-45db-ab53-5b2bb63962ee). Sao IDs estaveis
— se o Paperclip for recriado, atualizar aqui.

Estrutura de cada AgentIdentity:
  key        — identifier interno (SCRYER, ARBITER, ...)
  uuid       — Paperclip agent id
  role       — cargo na mesa (Research Analyst, Risk Reviewer, ...)
  archetype  — nome arquetipico (The Seer, The Judge, ...)
  stone      — pedra/metal alquimico associado
  tagline    — frase curta que vai no card
  typeface   — hint de fonte distintiva (Sprint 2 aplica)

Fonte de caminhos de filesystem de cada agente (specs, reviews, etc) —
essas constantes sao usadas pelo artifact_scanner.py.
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


SCRYER = AgentIdentity(
    key="SCRYER",
    uuid="c28d2218-9941-4c44-a318-6d9d2df129d2",
    role="Research Analyst",
    archetype="The Seer",
    stone="Amethyst",
    tagline="Scans, specs, hypothesis.",
    typeface="serif",
    artifact_dir="docs/specs",
)

ARBITER = AgentIdentity(
    key="ARBITER",
    uuid="246a2339-1cb1-4732-b588-16764487d05d",
    role="Risk & Code Reviewer",
    archetype="The Judge",
    stone="Onyx",
    tagline="Adversarial, concise, ruthless.",
    typeface="sans-rigorous",
    artifact_dir="docs/reviews",
)

ARTIFEX = AgentIdentity(
    key="ARTIFEX",
    uuid="34d56cfa-014e-4b20-903d-96f4ae5c2b05",
    role="Quant Developer",
    archetype="The Forger",
    stone="Copper",
    tagline="Metodical, engineer, hammer-in-hand.",
    typeface="mono",
    artifact_dir="",  # usa branches experiment/* no git, nao dir fixo
)

CURATOR = AgentIdentity(
    key="CURATOR",
    uuid="a424432d-be6d-44ea-80e3-f9b2c3b9d534",
    role="Repository Curator",
    archetype="The Keeper",
    stone="Silver",
    tagline="Quiet, minimal, observant.",
    typeface="sans-neutral",
    artifact_dir="docs/audits",
)


AGENTS: tuple[AgentIdentity, ...] = (SCRYER, ARBITER, ARTIFEX, CURATOR)
BY_KEY: dict[str, AgentIdentity] = {a.key: a for a in AGENTS}
BY_UUID: dict[str, AgentIdentity] = {a.uuid: a for a in AGENTS}


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
