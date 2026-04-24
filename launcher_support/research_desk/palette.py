"""Paleta cromatica hermetica por agente — ilhas de cor dentro do mood
amber/charcoal do launcher.

Cada operativo AI carrega uma pedra/metal alquimico associado ao papel:

  SCRYER  → ametista   (research, visao, intuicao)
  ARBITER → onix       (julgamento, dureza, justica)
  ARTIFEX → cobre      (forja, engenharia, materia)
  CURATOR → prata      (preservacao, quietude, memoria)
  ORACLE  → ouro       (integridade, veredito final, transmutacao)

Essas cores aparecem em:
  - borda esquerda/accent dos cards (acent de ~2px)
  - sigil strokes
  - nome do operativo (header do card)
  - borda pulsante quando running (Sprint 3)

Contraste: todos os tons primarios foram escolhidos pra destacar contra
BG=#2A2A2A (charcoal). ONYX verdadeiro #0A0A0A seria invisivel no BG;
usamos polished onyx (slate cold) pra preservar semantica sem sumir.

Import: from launcher_support.research_desk.palette import AGENT_COLORS
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentPalette:
    """Triade cromatica por agente: primary (accent), dark (shade), dim (subdued)."""
    primary: str
    dark: str
    dim: str


# ── Ametista — SCRYER ─────────────────────────────────────────────
# Roxo claro translucido, aludindo a cristal visionario.
SCRYER = AgentPalette(
    primary="#9966CC",
    dark="#4B0082",
    dim="#6B3F8F",
)

# ── Onix polido — ARBITER ─────────────────────────────────────────
# Onix real (#0A0A0A) desaparece contra charcoal. Usamos slate-onyx
# polido (#6E7276) como primary: preserva o "metal frio de julgamento"
# sem perder contraste.
ARBITER = AgentPalette(
    primary="#6E7276",
    dark="#2D3033",
    dim="#4A4D51",
)

# ── Cobre — ARTIFEX ───────────────────────────────────────────────
# Tom quente aludindo a forja e oxidacao; proximo do amber do launcher
# mas com shift pro vermelho pra diferenciar visualmente.
ARTIFEX = AgentPalette(
    primary="#B87333",
    dark="#704214",
    dim="#8A5725",
)

# ── Prata — CURATOR ───────────────────────────────────────────────
# Neutro frio e minimalista, coerente com o papel "keeper da ordem".
CURATOR = AgentPalette(
    primary="#C0C0C0",
    dark="#71797E",
    dim="#989898",
)

# ── Ouro — ORACLE ─────────────────────────────────────────────────
# Tom quente nobre aludindo a veredito final e transmutacao alquimica.
# Gold classico (#D4AF37) eh legivel contra charcoal sem confundir com
# o amber do launcher — shift pro amarelo mais puro.
ORACLE = AgentPalette(
    primary="#D4AF37",
    dark="#8B6914",
    dim="#AA8C2C",
)


AGENT_COLORS: dict[str, AgentPalette] = {
    "SCRYER": SCRYER,
    "ARBITER": ARBITER,
    "ARTIFEX": ARTIFEX,
    "CURATOR": CURATOR,
    "ORACLE": ORACLE,
}
