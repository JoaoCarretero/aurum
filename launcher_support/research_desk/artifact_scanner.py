"""Scanner de artefatos produzidos pelos operativos.

RESEARCH -> docs/specs/*.md
REVIEW   -> docs/reviews/*.md
BUILD    -> branches experiment/* via git (refs locais; remote fica fora
           do escopo do Sprint 1 pra nao depender de network)
CURATE   -> docs/audits/*.md
AUDIT    -> docs/audits/engines/*.md

scan_artifacts(root) retorna lista ArtifactEntry ordenada por mtime DESC.
Nao abre os arquivos — so lista. markdown_viewer.py renderiza quando o
user clica.

Nao joga se um dir nao existe — retorna lista vazia daquele agente.
"""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


@dataclass(frozen=True)
class ArtifactEntry:
    """Um artefato producido por um agente."""
    agent_key: str               # "RESEARCH" | "REVIEW" | "BUILD" | "CURATE" | "AUDIT"
    kind: str                    # "spec" | "review" | "branch" | "audit"
    title: str                   # filename sem extensao / nome da branch
    path: str                    # caminho relativo ao root, ou refname do git
    mtime_epoch: float           # seconds since epoch (0 se branch)
    is_markdown: bool            # True se renderivel pelo markdown_viewer


_AGENT_KINDS: list[tuple[str, str, str]] = [
    # (agent_key, kind, relative_dir)
    ("RESEARCH", "spec", "docs/specs"),
    ("REVIEW", "review", "docs/reviews"),
    ("CURATE", "audit", "docs/audits"),
]


def scan_artifacts(root: Path, limit: int = 50) -> list[ArtifactEntry]:
    """Combina filesystem + git refs; retorna ate `limit` itens mais recentes."""
    entries: list[ArtifactEntry] = []
    for agent_key, kind, rel_dir in _AGENT_KINDS:
        entries.extend(_scan_markdown_dir(
            root=root, rel_dir=rel_dir, agent_key=agent_key, kind=kind,
        ))
    entries.extend(_scan_experiment_branches(root=root))

    entries.sort(key=lambda e: e.mtime_epoch, reverse=True)
    return entries[:limit]


def _scan_markdown_dir(
    root: Path, rel_dir: str, agent_key: str, kind: str,
) -> list[ArtifactEntry]:
    base = root / rel_dir
    if not base.exists() or not base.is_dir():
        return []
    out: list[ArtifactEntry] = []
    for p in base.rglob("*.md"):
        try:
            stat = p.stat()
        except OSError:
            continue
        out.append(ArtifactEntry(
            agent_key=agent_key,
            kind=kind,
            title=p.stem,
            path=str(p.relative_to(root)).replace("\\", "/"),
            mtime_epoch=stat.st_mtime,
            is_markdown=True,
        ))
    return out


def _scan_experiment_branches(root: Path) -> list[ArtifactEntry]:
    """Lista branches experiment/* locais via git. Timeout curto pra
    nao travar UI se git tiver issues."""
    try:
        result = subprocess.run(
            ["git", "for-each-ref",
             "--format=%(refname:short)|%(committerdate:unix)",
             "refs/heads/experiment"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=3.0,
            encoding="utf-8",
            errors="replace",
            creationflags=_NO_WINDOW,
        )
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        return []
    if result.returncode != 0:
        return []

    out: list[ArtifactEntry] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|", 1)
        if len(parts) != 2:
            continue
        refname, ts = parts
        try:
            mtime = float(ts)
        except ValueError:
            mtime = 0.0
        # Remove prefix pra title ficar limpo
        title = refname[len("experiment/"):] if refname.startswith("experiment/") else refname
        out.append(ArtifactEntry(
            agent_key="BUILD",
            kind="branch",
            title=title or refname,
            path=refname,
            mtime_epoch=mtime,
            is_markdown=False,
        ))
    return out


def relative_age(entry: ArtifactEntry) -> str:
    """Format 'Nmin atras'/'Nh atras'/'Nd atras' desde mtime."""
    import time
    if entry.mtime_epoch <= 0:
        return "—"
    delta = int(time.time() - entry.mtime_epoch)
    if delta < 0:
        return "agora"
    if delta < 60:
        return f"{delta}s atras"
    if delta < 3600:
        return f"{delta // 60}min atras"
    if delta < 86400:
        return f"{delta // 3600}h atras"
    return f"{delta // 86400}d atras"
