"""Alignment scan — detects drift between AURUM canon files and reality.

Pure-Python, no UI. Returns a structured AlignmentReport that the
alignment_panel.py widget renders.

Checks performed (progressively added per plan 2026-04-24-alignment-panel.md):
  1. engine_roster    — engine names cited in canon vs. config/engines.py
  2. path_existence   — filesystem paths referenced in canon exist (Task 2)
  3. staleness        — persona mtime vs. canon mtime (Task 3)
  4. paperclip_sync   — ~/.paperclip/.../AGENTS.md presence + header match (Task 4)
  5. protected_files  — MEMORY.md canonical list exists on disk (Task 5)

Usage:
    from pathlib import Path
    from launcher_support.research_desk.alignment_scan import run_alignment_scan

    report = run_alignment_scan(repo_root=Path("/path/to/aurum.finance"))
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


# Operative names (not engines). Bolded in canon as **SCRYER** etc.
_OPERATIVE_NAMES: frozenset[str] = frozenset({
    "SCRYER", "ARBITER", "ARTIFEX", "CURATOR", "ORACLE",
})

# Tokens that legitimately appear bolded in prose but are NOT engine refs.
# Keep minimal; extend only when new false positives emerge.
_BOLD_IGNORE: frozenset[str] = frozenset({
    # Portuguese prose emphasis
    "NUNCA", "ARQUIVA", "ATENCAO", "ATENÇÃO", "SEMPRE", "MUITO IMPORTANTE",
    # English prose emphasis
    "MUST USE", "CAUTION", "WARNING", "PROTECTED",
    # Verdict / status markers (bolded in tables / callouts)
    "PASS", "FAIL", "SHIP", "ITERATE", "KILL", "BLOCKER",
    "KILL IMEDIATO", "GATE FINAL",
    "VALIDATED", "REJECTED", "CONDITIONAL",
    # Engine stages (bolded in MEMORY.md §4 headers)
    "BOOTSTRAP", "RESEARCH", "QUARANTINED", "EXPERIMENTAL",
    # Common tech acronyms that might get bolded
    "VPS", "GUI", "API", "CLI", "CORE", "TBD", "TODO", "NO", "YES", "OK",
    "N", "M", "X", "Y", "Z",
})

# Bold uppercase marker: `**NAME**` (possibly with internal spaces/underscores)
# Used as primary signal to find engine references in canon.
_BOLD_TOKEN_PATTERN = re.compile(r"\*\*([A-Z][A-Z0-9_ ]{2,}?)\*\*")

# Backtick-quoted relative path with file extension.
#   - Must start with an alphanumeric (excludes absolute /path, ~home, C:\path)
#   - Must contain at least one / or \ (excludes bare filenames / dotted
#     Python module refs like `json.load` or `config.params`)
#   - Must end with .ext (1-6 chars)
#   - Disallow http(s):// URLs (lookahead)
_PATH_REF_PATTERN = re.compile(
    r"`(?!https?://)([a-zA-Z0-9_][a-zA-Z0-9_.-]*[/\\][a-zA-Z0-9_./\\~-]*\.[a-zA-Z0-9]{1,6})`"
)

# Placeholder markers that indicate a TEMPLATE path, not a concrete one.
# Templates like `docs/sessions/YYYY-MM-DD_HHMM.md` should not be flagged.
_PATH_PLACEHOLDERS: tuple[str, ...] = (
    "YYYY", "HHMM", "...",
    "{engine}", "<engine>", "{name}", "<name>", "<slug>", "{slug}",
    "{cid}", "{aid}", "{id}",
)


@dataclass
class CheckResult:
    status: str  # "green" | "yellow" | "red"
    summary: str
    details: list[dict] = field(default_factory=list)


@dataclass
class AlignmentReport:
    timestamp: str  # ISO 8601 UTC
    overall: str   # "green" | "yellow" | "red"
    checks: dict[str, CheckResult] = field(default_factory=dict)


# ── Check 1: engine roster ───────────────────────────────────────
def check_engine_roster(
    canon_files: Iterable[Path],
    *,
    registered_display_names: set[str],
    operative_names: frozenset[str] = _OPERATIVE_NAMES,
    ignore_bold: frozenset[str] = _BOLD_IGNORE,
) -> CheckResult:
    """Scan canon for bolded uppercase tokens (`**NAME**`) that are neither
    registered engines nor operatives nor known non-engine prose tokens.

    Rationale: free-form uppercase scanning is too noisy (Portuguese prose,
    tech acronyms, constants). Bold is the unambiguous signal the canon uses
    for engine names in tables and callouts.
    """
    valid: set[str] = set()
    for name in registered_display_names:
        up = name.upper()
        valid.add(up)
        valid.add(up.replace(" ", "_"))
        valid.add(up.replace(" ", ""))
    ignore_all = operative_names | ignore_bold | valid

    ghosts: dict[str, list[str]] = {}
    for f in canon_files:
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for match in _BOLD_TOKEN_PATTERN.finditer(text):
            token = match.group(1).strip().upper()
            if token in ignore_all:
                continue
            ghosts.setdefault(token, []).append(f.name)

    if not ghosts:
        return CheckResult(
            status="green",
            summary="Todas as referencias bold a engines batem com config/engines.py.",
            details=[],
        )

    details = [
        {"engine": name, "files": sorted(set(files))}
        for name, files in sorted(ghosts.items())
    ]
    return CheckResult(
        status="red",
        summary=f"{len(ghosts)} engine ref(s) bold fantasma — nao estao em config/engines.py.",
        details=details,
    )


# ── Check 2: path existence ──────────────────────────────────────
def check_path_existence(
    canon_files: Iterable[Path],
    *,
    repo_root: Path,
) -> CheckResult:
    """Scan canon for backtick-quoted relative paths and verify they exist.

    Absolute paths and URLs are out of scope (not flagged). Paths are resolved
    relative to repo_root.
    """
    missing: dict[str, list[str]] = {}
    for f in canon_files:
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for match in _PATH_REF_PATTERN.finditer(text):
            rel = match.group(1).replace("\\", "/")
            # Skip template paths (contain placeholder markers).
            if any(ph in rel for ph in _PATH_PLACEHOLDERS):
                continue
            candidate = repo_root / rel
            if not candidate.exists():
                missing.setdefault(rel, []).append(f.name)

    if not missing:
        return CheckResult(
            status="green",
            summary="Todos os paths referenciados existem no repo.",
            details=[],
        )
    details = [
        {"path": p, "cited_in": sorted(set(files))}
        for p, files in sorted(missing.items())
    ]
    return CheckResult(
        status="red",
        summary=f"{len(missing)} path(s) referenciado(s) inexistente(s) no filesystem.",
        details=details,
    )


# ── Check 3: staleness ───────────────────────────────────────────
def check_staleness(
    *,
    personas: Iterable[Path],
    canon_files: Iterable[Path],
    max_age_days: int = 14,
) -> CheckResult:
    """Flag personas whose mtime is older than the newest canon file by
    more than max_age_days. Signal that a persona may be out of sync with
    the authoritative docs it references.
    """
    canon_list = list(canon_files)
    if not canon_list:
        return CheckResult(
            status="yellow", summary="Nenhum canon file encontrado.", details=[]
        )
    # Guard against TOCTOU on syncing filesystems (OneDrive): a canon file
    # listed by _collect_canon_files may vanish between collection and stat.
    mtimes: list[float] = []
    for f in canon_list:
        try:
            mtimes.append(f.stat().st_mtime)
        except OSError:
            continue
    if not mtimes:
        return CheckResult(
            status="yellow", summary="Nenhum canon file acessivel (stat falhou).", details=[],
        )
    newest_canon_mtime = max(mtimes)
    threshold_s = max_age_days * 86400

    stale: list[dict] = []
    for p in personas:
        try:
            age_s = newest_canon_mtime - p.stat().st_mtime
        except OSError:
            continue
        if age_s > threshold_s:
            stale.append({
                "persona": p.name,
                "days_behind_canon": round(age_s / 86400, 1),
            })

    if not stale:
        return CheckResult(
            status="green",
            summary=f"Personas frescas (todas <={max_age_days}d atras do canon).",
            details=[],
        )
    return CheckResult(
        status="yellow",
        summary=f"{len(stale)} persona(s) mais antigas que canon por >{max_age_days}d.",
        details=stale,
    )


# ── Check 4: paperclip sync ──────────────────────────────────────
def check_paperclip_sync(
    *,
    agents: dict[str, str],  # agent_key -> uuid
    paperclip_home: Path,
    company_id: str,
) -> CheckResult:
    """Verify each agent has AGENTS.md in the Paperclip instance tree AND
    its first line starts with `# {AGENT_KEY}`."""
    base = paperclip_home / "instances" / "default" / "companies" / company_id / "agents"
    issues: list[dict] = []
    for key, uid in agents.items():
        f = base / uid / "instructions" / "AGENTS.md"
        if not f.exists():
            issues.append({"agent": key, "reason": "missing", "path": str(f)})
            continue
        try:
            # utf-8-sig transparently strips BOM (Paperclip is Node.js/Electron,
            # writes BOM on Windows which would break startswith() below).
            text = f.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            issues.append({"agent": key, "reason": "unreadable", "path": str(f)})
            continue
        first = text.splitlines()[0] if text else ""
        # Also strip leading whitespace so "  # ORACLE" would still match.
        if not first.lstrip().startswith(f"# {key}"):
            issues.append({
                "agent": key,
                "reason": "header_mismatch",
                "first_line": first[:80],
            })

    if not issues:
        return CheckResult(
            status="green",
            summary=f"{len(agents)}/{len(agents)} Paperclip AGENTS.md sync ok.",
            details=[],
        )
    return CheckResult(
        status="red",
        summary=f"{len(issues)} agent(s) com AGENTS.md missing ou header mismatch.",
        details=issues,
    )


# ── Check 5: protected files ─────────────────────────────────────
# Canonical list per MEMORY.md §1-2 (core/indicators, core/signals,
# core/portfolio, config/params + config/keys.json + launcher.py).
CANONICAL_PROTECTED: tuple[str, ...] = (
    "core/indicators.py",
    "core/signals.py",
    "core/portfolio.py",
    "config/params.py",
    "config/keys.json",
    "launcher.py",
)


def check_protected_files(
    *,
    canonical: Iterable[str],
    repo_root: Path,
) -> CheckResult:
    """Verify each canonical protected file exists in the repo."""
    missing: list[dict] = []
    for rel in canonical:
        if not (repo_root / rel).exists():
            missing.append({"path": rel})

    if not missing:
        return CheckResult(
            status="green",
            summary="Todos os arquivos protegidos canonicos existem.",
            details=[],
        )
    return CheckResult(
        status="red",
        summary=f"{len(missing)} arquivo(s) protegido(s) canonico(s) ausente(s).",
        details=missing,
    )


# ── Orchestration ────────────────────────────────────────────────
def _collect_canon_files(repo_root: Path) -> list[Path]:
    """Return the full canon set (root + personas + WORKFLOWS)."""
    root_files = ("CLAUDE.md", "AGENTS.md", "MEMORY.md", "CONTEXT.md", "SKILLS.md")
    files: list[Path] = [repo_root / name for name in root_files if (repo_root / name).exists()]
    agents_dir = repo_root / "docs" / "agents"
    if agents_dir.exists():
        files.extend(sorted(agents_dir.glob("*.md")))
    return files


def _collect_agent_facing_files(
    repo_root: Path,
    *,
    paperclip_home: Path | None = None,
    company_id: str | None = None,
    agent_uuids: Iterable[str] = (),
) -> list[Path]:
    """Files that agents actually read as primary instruction.

    Root canon (MEMORY.md etc) intentionally mention archived engines as
    historical record — excluded here to avoid false positives in
    engine_roster check.
    """
    files: list[Path] = []
    agents_dir = repo_root / "docs" / "agents"
    if agents_dir.exists():
        files.extend(sorted(agents_dir.glob("*.md")))
    if paperclip_home and company_id:
        base = paperclip_home / "instances" / "default" / "companies" / company_id / "agents"
        for uid in agent_uuids:
            f = base / uid / "instructions" / "AGENTS.md"
            if f.exists():
                files.append(f)
    return files


class EngineRegistryLoadError(RuntimeError):
    """Raised when config/engines.py cannot be loaded. Caller should treat
    this as a scan failure — silently returning an empty set would make
    engine_roster pass as green even when the registry is unreadable."""


def _load_registered_engine_names(repo_root: Path) -> set[str]:
    """Load ENGINE_NAMES display values from config/engines.py.

    Raises EngineRegistryLoadError on any failure (spec resolution, import,
    missing ENGINE_NAMES attribute). Callers must handle this explicitly —
    never fall back to empty set, which would silently green-wash
    engine_roster.
    """
    import importlib.util

    spec_path = repo_root / "config" / "engines.py"
    if not spec_path.exists():
        raise EngineRegistryLoadError(f"config/engines.py not found at {spec_path}")

    spec = importlib.util.spec_from_file_location("_aurum_config_engines", spec_path)
    if spec is None or spec.loader is None:
        raise EngineRegistryLoadError(f"Could not build import spec for {spec_path}")

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001
        raise EngineRegistryLoadError(f"exec_module failed: {exc}") from exc

    names = getattr(module, "ENGINE_NAMES", None)
    if not isinstance(names, dict):
        raise EngineRegistryLoadError("ENGINE_NAMES dict missing or wrong type")
    return set(names.values())


def _aggregate_overall(checks: dict[str, CheckResult]) -> str:
    statuses = {c.status for c in checks.values()}
    if "red" in statuses:
        return "red"
    if "yellow" in statuses:
        return "yellow"
    return "green"


def run_alignment_scan(*, repo_root: Path) -> AlignmentReport:
    """Run all checks and return an aggregated report."""
    registered = _load_registered_engine_names(repo_root)

    # Engine roster check: scope to files agents actually load as instructions.
    # Root canon (MEMORY.md etc) intentionally contain archived-engine history.
    from launcher_support.research_desk.agents import AGENTS as _AGENTS, COMPANY_ID
    paperclip_home = Path.home() / ".paperclip"
    agent_facing = _collect_agent_facing_files(
        repo_root,
        paperclip_home=paperclip_home,
        company_id=COMPANY_ID,
        agent_uuids=[a.uuid for a in _AGENTS],
    )

    # Path existence check: scope to full canon (root + personas + WORKFLOWS).
    # Broken paths in CLAUDE.md etc ARE drift, unlike archived engine names.
    canon = _collect_canon_files(repo_root)

    # Staleness: persona mtime vs newest canon mtime.
    personas_dir = repo_root / "docs" / "agents"
    personas = sorted(personas_dir.glob("*.md")) if personas_dir.exists() else []

    # Paperclip sync.
    agents_map = {a.key: a.uuid for a in _AGENTS}

    checks: dict[str, CheckResult] = {
        "engine_roster": check_engine_roster(agent_facing, registered_display_names=registered),
        "path_existence": check_path_existence(canon, repo_root=repo_root),
        "staleness": check_staleness(personas=personas, canon_files=canon, max_age_days=14),
        "paperclip_sync": check_paperclip_sync(
            agents=agents_map, paperclip_home=paperclip_home, company_id=COMPANY_ID,
        ),
        "protected_files": check_protected_files(
            canonical=CANONICAL_PROTECTED, repo_root=repo_root,
        ),
    }

    return AlignmentReport(
        timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        overall=_aggregate_overall(checks),
        checks=checks,
    )
