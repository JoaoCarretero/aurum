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

Nao joga se um dir nao existe — retorna lista vazia daquele agente,
mais um _LOG.info one-time pra distinguir "diretorio ausente" de
"diretorio vazio" (Lane 4 CRIT #3 do audit).
"""
from __future__ import annotations

import logging
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_LOG = logging.getLogger(__name__)
_MISSING_DIRS_LOGGED: set[str] = set()  # one-time log per missing dir per process

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

_RUN_SUBDIR = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{4}$")
_EXPERIMENT_WINDOW_SEC = 3600


def _load_valid_engines() -> set[str] | None:
    """Set of lowercased engine keys from config/engines.py, or None if
    the registry can't be loaded. Caller treats None as 'don't filter' —
    backward-compat with bare-tree tests that don't have config/.
    """
    try:
        from config.engines import ENGINE_NAMES
        return {k.lower() for k in ENGINE_NAMES.keys()}
    except Exception:  # noqa: BLE001
        return None


@dataclass(frozen=True)
class ArtifactEntry:
    """Um artefato producido por um agente ou run de backtest."""
    agent_key: str               # "RESEARCH" | "REVIEW" | "BUILD" | "CURATE" | "AUDIT" | ""
    kind: str                    # "spec" | "review" | "branch" | "audit" | "backtest"
    title: str
    path: str
    mtime_epoch: float
    is_markdown: bool
    engine: str = ""             # só backtest: "citadel", "phi", ...
    run_id: str = ""             # só backtest: "2026-04-23_1403"
    origin: str = ""             # "agent" | "human" | "" (não-backtest)


_AGENT_KINDS: list[tuple[str, str, str]] = [
    # (agent_key, kind, relative_dir)
    ("RESEARCH", "spec", "docs/specs"),
    ("REVIEW", "review", "docs/reviews"),
    ("CURATE", "audit", "docs/audits"),
]


def scan_artifacts(
    root: Path, limit: int = 50, issues: list[dict] | None = None,
) -> list[ArtifactEntry]:
    """Combina filesystem + git refs + backtests; limit mais recentes."""
    entries: list[ArtifactEntry] = []
    for agent_key, kind, rel_dir in _AGENT_KINDS:
        entries.extend(_scan_markdown_dir(
            root=root, rel_dir=rel_dir, agent_key=agent_key, kind=kind,
        ))
    entries.extend(_scan_experiment_branches(root=root))
    entries.extend(_scan_backtests(root, issues=issues))

    entries.sort(key=lambda e: e.mtime_epoch, reverse=True)
    return entries[:limit]


def _scan_markdown_dir(
    root: Path, rel_dir: str, agent_key: str, kind: str,
) -> list[ArtifactEntry]:
    base = root / rel_dir
    if not base.exists() or not base.is_dir():
        # One-time per process per dir — distinguishes "0 specs because
        # nothing yet" from "0 specs because docs/specs doesn't exist".
        # Without this, a typo in _AGENT_KINDS or a renamed dir silently
        # surfaces as empty in the UI forever.
        if rel_dir not in _MISSING_DIRS_LOGGED:
            _MISSING_DIRS_LOGGED.add(rel_dir)
            _LOG.info(
                "artifact_scanner: dir missing %s (agent=%s kind=%s) — "
                "panel will show 0 entries",
                rel_dir, agent_key, kind,
            )
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


def _scan_backtests(
    root: Path, issues: list[dict] | None = None,
) -> list[ArtifactEntry]:
    """Varre data/<engine>/<YYYY-MM-DD_HHMM>/ e retorna entries
    com kind='backtest'. Retorna [] se data/ não existe.

    Engine filter: skip subdirs whose name isn't a registered engine
    in config/engines.py — drops `_archive`, `db`, `exports`,
    `aurum.db.backup-*` etc that polluted backtest entries before.
    Falls back to no-filter if config/engines.py isn't loadable
    (bare-tree tests).

    Reflog parsed ONCE at the top — `_was_on_experiment_branch` was
    O(N·M) on N runs × M reflog lines (typical reflog is 10k+ lines
    on dev machines).
    """
    base = root / "data"
    if not base.exists() or not base.is_dir():
        return []
    issues = issues or []
    valid_engines = _load_valid_engines()
    reflog_events = _parse_reflog_once(root)

    out: list[ArtifactEntry] = []
    for engine_dir in base.iterdir():
        if not engine_dir.is_dir():
            continue
        engine = engine_dir.name
        if valid_engines is not None and engine.lower() not in valid_engines:
            continue
        for run_dir in engine_dir.iterdir():
            if not run_dir.is_dir():
                continue
            if not _RUN_SUBDIR.match(run_dir.name):
                continue
            try:
                stat = run_dir.stat()
            except OSError:
                continue
            run_id = run_dir.name
            origin = _detect_origin(
                root, engine, run_id, issues,
                mtime_epoch=stat.st_mtime,
                reflog_events=reflog_events,
            )
            out.append(ArtifactEntry(
                agent_key="",
                kind="backtest",
                title=f"{engine}/{run_id}",
                path=str(run_dir.relative_to(root)).replace("\\", "/"),
                mtime_epoch=stat.st_mtime,
                is_markdown=False,
                engine=engine,
                run_id=run_id,
                origin=origin,
            ))
    return out


def _detect_origin(
    root: Path, engine: str, run_id: str, issues: list[dict],
    mtime_epoch: float = 0.0,
    reflog_events: list[tuple[float, str]] | None = None,
) -> str:
    """agent se label 'run:<engine>/<run_id>' em alguma issue OR body tem
    '**run_id:** <engine>/<run_id>' OR .git/logs/HEAD mostra checkout em
    experiment/* dentro de ±1h do mtime_epoch. Senão human.

    `reflog_events` (optional): pre-parsed list from `_parse_reflog_once`.
    When None (e.g. tests calling _detect_origin directly), falls back
    to per-call file read via `_was_on_experiment_branch`.
    """
    needle = f"{engine}/{run_id}"
    label_needle = f"run:{needle}"
    body_needle = f"**run_id:** {needle}"
    for issue in issues:
        labels = issue.get("labels") or []
        if isinstance(labels, list) and label_needle in labels:
            return "agent"
        desc = issue.get("description") or issue.get("body") or ""
        if isinstance(desc, str) and body_needle in desc:
            return "agent"

    if reflog_events is not None:
        if _was_on_experiment_branch_cached(reflog_events, mtime_epoch):
            return "agent"
    else:
        if _was_on_experiment_branch(root, mtime_epoch):
            return "agent"
    return "human"


def _parse_reflog_once(root: Path) -> list[tuple[float, str]]:
    """Read .git/logs/HEAD once, return [(ts_epoch, message), ...] for
    every line that mentions both `checkout:` and `experiment/`.

    Returns [] on missing reflog or any parse/IO error — caller treats
    as "no experiment activity recorded".
    """
    reflog = root / ".git" / "logs" / "HEAD"
    if not reflog.exists():
        return []
    events: list[tuple[float, str]] = []
    try:
        with open(reflog, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                tab_split = line.split("\t", 1)
                if len(tab_split) < 2:
                    continue
                header, message = tab_split
                if "checkout:" not in message or "experiment/" not in message:
                    continue
                tokens = header.rsplit(None, 2)
                if len(tokens) < 3:
                    continue
                try:
                    ts = float(tokens[-2])
                except ValueError:
                    continue
                events.append((ts, message))
    except OSError:
        return []
    return events


def _was_on_experiment_branch_cached(
    reflog_events: list[tuple[float, str]],
    mtime_epoch: float,
    window_sec: int = _EXPERIMENT_WINDOW_SEC,
) -> bool:
    """O(M) check over pre-parsed reflog events. No FS I/O."""
    if mtime_epoch <= 0:
        return False
    return any(abs(ts - mtime_epoch) <= window_sec for ts, _ in reflog_events)


def _was_on_experiment_branch(
    root: Path, mtime_epoch: float, window_sec: int = _EXPERIMENT_WINDOW_SEC,
) -> bool:
    """Backward-compat: per-call file read of .git/logs/HEAD.

    Used only by tests that call `_detect_origin` directly without
    pre-parsing the reflog. Production path (`_scan_backtests`) calls
    `_parse_reflog_once` + `_was_on_experiment_branch_cached` to avoid
    O(N·M) reads.
    """
    if mtime_epoch <= 0:
        return False
    return _was_on_experiment_branch_cached(
        _parse_reflog_once(root), mtime_epoch, window_sec,
    )


def list_backtest_runs(
    root: Path, limit: int = 50,
) -> list[tuple[str, str, float]]:
    """(engine, run_id, mtime) ordenado desc por mtime."""
    entries = _scan_backtests(root, issues=[])
    entries.sort(key=lambda e: e.mtime_epoch, reverse=True)
    return [(e.engine, e.run_id, e.mtime_epoch) for e in entries[:limit]]


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
