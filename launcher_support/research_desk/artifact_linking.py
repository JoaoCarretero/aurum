"""Linkagem de artifacts — spec -> review -> branch -> backtest.

Dado um conjunto de ArtifactEntry, agrupa por "stem" (nome base) em
cadeias:

  RESEARCH spec    docs/specs/phi-fib.md
  REVIEW review    docs/reviews/phi-fib.md
  BUILD branch     experiment/phi-fib
  backtest run     data/phi/2026-04-23_1403/

Heuristica: mesma stem (normalizada: lowercase, espacos/hifens/
underscores preservados como hifens). Se 2+ artifacts diferentes
tem mesmo stem, viram um LinkedChain.

Tambem identifica engine pelo stem (ex: "phi-fib" -> "PHI") via
simple prefix match contra lista canonica.

Pure function — testavel sem Tk/filesystem.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from launcher_support.research_desk.artifact_scanner import ArtifactEntry


# Engines canonicos pra match de prefixo no stem
_KNOWN_ENGINES = (
    "CITADEL", "RENAISSANCE", "JANE_STREET", "DE_SHAW", "BRIDGEWATER",
    "JUMP", "TWO_SIGMA", "AQR", "MILLENNIUM", "WINTON", "PHI", "KEPOS",
    "MEDALLION", "GRAHAM",
)


@dataclass(frozen=True)
class LinkedChain:
    """Uma cadeia de trabalho relacionada por stem comum."""
    stem: str                    # normalizado, ex: "phi-fib"
    spec: ArtifactEntry | None = None
    review: ArtifactEntry | None = None
    branch: ArtifactEntry | None = None
    audit: ArtifactEntry | None = None
    backtest_run_id: str = ""    # "engine/run_id" se backtest linkado
    engine: str | None = None    # ex: "PHI" se matchou prefixo

    @property
    def is_complete(self) -> bool:
        """Spec + review + branch = cadeia 'completa' (3 fases)."""
        return (self.spec is not None
                and self.review is not None
                and self.branch is not None)

    @property
    def parts(self) -> list[ArtifactEntry]:
        """Lista de artefatos nao-None nesta cadeia."""
        return [p for p in (self.spec, self.review, self.branch, self.audit)
                if p is not None]


def normalize_stem(raw: str) -> str:
    """'PHI FiB_v2' -> 'phi-fib-v2'. Idempotente.

    Titulos livres podem ter brackets/pontuacao ('[PHI] fib_v2') —
    strip non-alphanum (exceto hyphen) antes de colapsar, senao o
    prefix match de detect_engine passa batido.
    """
    stem = raw.strip().lower()
    stem = re.sub(r"[^a-z0-9\-]+", "-", stem)
    stem = re.sub(r"-+", "-", stem)
    return stem.strip("-")


def detect_engine(stem: str) -> str | None:
    """Tenta casar stem contra nomes de engine canonicos (prefix match)."""
    # stem normalizado ja; comparar lower-case com variantes
    candidates_lower = [e.lower().replace("_", "-") for e in _KNOWN_ENGINES]
    for canonical, cand in zip(_KNOWN_ENGINES, candidates_lower):
        if stem == cand or stem.startswith(cand + "-"):
            return canonical
    return None


def link_artifacts(artifacts: Iterable[ArtifactEntry]) -> list[LinkedChain]:
    """Agrupa artefatos por stem normalizado. Chain so e emitida se >=2
    artefatos distintos compartilham stem (senao seria 1 spec solto)."""
    by_stem: dict[str, dict[str, ArtifactEntry]] = {}
    backtests_by_engine: dict[str, ArtifactEntry] = {}

    for art in artifacts:
        if art.kind == "backtest":
            # Guarda o backtest mais recente por engine (vem pré-ordenado do scan)
            if not art.engine:
                # Defensive: ArtifactEntry.engine defaults to ""; a malformed
                # entry would otherwise insert under key "" and shadow real
                # engines via subsequent lookups.
                continue
            key = art.engine.lower()
            if key not in backtests_by_engine:
                backtests_by_engine[key] = art
            continue
        stem = normalize_stem(art.title)
        slot = by_stem.setdefault(stem, {})
        # Primeiro artifact daquele kind ganha (mais recente ja pelo scan)
        if art.kind not in slot:
            slot[art.kind] = art

    chains: list[LinkedChain] = []
    for stem, slots in by_stem.items():
        if len(slots) < 2:
            continue
        engine_key = detect_engine(stem)
        bt_entry = None
        if engine_key is not None:
            bt_entry = backtests_by_engine.get(engine_key.lower())
        chains.append(LinkedChain(
            stem=stem,
            spec=slots.get("spec"),
            review=slots.get("review"),
            branch=slots.get("branch"),
            audit=slots.get("audit"),
            backtest_run_id=(
                f"{bt_entry.engine}/{bt_entry.run_id}" if bt_entry else ""
            ),
            engine=engine_key,
        ))

    # Ordena chains pela mtime_epoch do artefato mais recente
    def _latest_mtime(chain: LinkedChain) -> float:
        return max((p.mtime_epoch for p in chain.parts), default=0.0)

    chains.sort(key=_latest_mtime, reverse=True)
    return chains


def chains_for_agent(
    chains: list[LinkedChain], agent_key: str,
) -> list[LinkedChain]:
    """Filtra chains que envolvem o agente dado (i.e., tem artefato de que
    agente produz)."""
    agent_kind_map = {
        "RESEARCH": "spec",
        "REVIEW": "review",
        "BUILD": "branch",
        "CURATE": "audit",
        "AUDIT": "audit",
    }
    needed = agent_kind_map.get(agent_key)
    if needed is None:
        return []
    out = []
    for c in chains:
        if needed == "spec" and c.spec is not None:
            out.append(c)
        elif needed == "review" and c.review is not None:
            out.append(c)
        elif needed == "branch" and c.branch is not None:
            out.append(c)
        elif needed == "audit" and c.audit is not None:
            out.append(c)
    return out


# ── Backtest command builder ─────────────────────────────────────


def backtest_command_for(chain: LinkedChain) -> str:
    """Monta comando para rodar backtest deste engine. String copy-ready.

    Convencao do projeto: python engines/{engine_lower}.py <args>
    Sem engine detectado retorna placeholder comentado.
    """
    if chain.engine is None:
        return f"# sem engine detectado pra stem '{chain.stem}' — ajuste manual"
    script = f"engines/{chain.engine.lower()}.py"
    return f"python {script} --tag {chain.stem}"
