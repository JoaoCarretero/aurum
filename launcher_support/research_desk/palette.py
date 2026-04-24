"""Paleta cromatica por operativo — ilhas de cor dentro do mood
amber/charcoal do launcher.

Cada operativo AI carrega uma pedra/metal alquimico (flavor) associado
ao papel, mapeada para um triad primary/dark/dim:

  RESEARCH → ametista   (scanning, visao, intuicao)
  REVIEW   → onix       (julgamento, dureza, justica)
  BUILD    → cobre      (forja, engenharia, materia)
  CURATE   → prata      (preservacao, quietude, memoria)
  AUDIT    → ouro       (integridade, veredito final, transmutacao)

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


# ── Ametista — RESEARCH ───────────────────────────────────────────
# Roxo claro translucido, aludindo a cristal visionario.
RESEARCH = AgentPalette(
    primary="#9966CC",
    dark="#4B0082",
    dim="#6B3F8F",
)

# ── Onix polido — REVIEW ──────────────────────────────────────────
# Onix real (#0A0A0A) desaparece contra charcoal. Usamos slate-onyx
# polido (#6E7276) como primary: preserva o "metal frio de julgamento"
# sem perder contraste.
REVIEW = AgentPalette(
    primary="#6E7276",
    dark="#2D3033",
    dim="#4A4D51",
)

# ── Cobre — BUILD ─────────────────────────────────────────────────
# Tom quente aludindo a forja e oxidacao; proximo do amber do launcher
# mas com shift pro vermelho pra diferenciar visualmente.
BUILD = AgentPalette(
    primary="#B87333",
    dark="#704214",
    dim="#8A5725",
)

# ── Prata — CURATE ────────────────────────────────────────────────
# Neutro frio e minimalista, coerente com o papel "keeper da ordem".
CURATE = AgentPalette(
    primary="#C0C0C0",
    dark="#71797E",
    dim="#989898",
)

# ── Ouro — AUDIT ──────────────────────────────────────────────────
# Tom quente nobre aludindo a veredito final e transmutacao alquimica.
# Gold classico (#D4AF37) eh legivel contra charcoal sem confundir com
# o amber do launcher — shift pro amarelo mais puro.
AUDIT = AgentPalette(
    primary="#D4AF37",
    dark="#8B6914",
    dim="#AA8C2C",
)


AGENT_COLORS: dict[str, AgentPalette] = {
    "RESEARCH": RESEARCH,
    "REVIEW": REVIEW,
    "BUILD": BUILD,
    "CURATE": CURATE,
    "AUDIT": AUDIT,
}
