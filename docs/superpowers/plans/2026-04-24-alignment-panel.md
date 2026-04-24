# Alignment Panel — Research Desk Integration (Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a pure-Python alignment scanner + TkInter panel that shows drift between AURUM canon files (CLAUDE/AGENTS/MEMORY/CONTEXT/SKILLS/docs/agents/*) and reality (config/engines.py, filesystem, Paperclip instance files).

**Architecture:** Two new modules in `launcher_support/research_desk/`: `alignment_scan.py` (pure function, returns dict) + `alignment_panel.py` (TkInter widget). Wired into existing research_desk container panel. Five deterministic checks: engine_roster, path_existence, protected_files, staleness, paperclip_sync.

**Tech Stack:** Python 3.11, TkInter (existing launcher stack), pytest.

**Preconditions confirmed:**
- `config/engines.py ENGINES` dict is source of truth for engines (12 entries)
- `launcher_support/research_desk/agents.py` has `AGENTS_MD_TEMPLATE` + UUIDs — but only 4 operatives (missing ORACLE — **Task 0 fixes**)
- Canon files at repo root: CLAUDE.md, AGENTS.md, MEMORY.md, CONTEXT.md, SKILLS.md
- Personas at `docs/agents/{scryer,arbiter,artifex,curator,oracle}.md` + `docs/agents/WORKFLOWS.md`
- Paperclip instance files at `~/.paperclip/instances/default/companies/{cid}/agents/{aid}/instructions/AGENTS.md`

---

### Task 0: Add ORACLE to `launcher_support/research_desk/agents.py`

**Files:**
- Modify: `launcher_support/research_desk/agents.py` (add ORACLE AgentIdentity + update AGENTS tuple)
- Modify: `tests/launcher/research_desk/test_scaffold.py` or new test (verify 5 operatives present)

- [ ] **Step 0.1: Write the failing test**

Append to `tests/launcher/research_desk/test_scaffold.py`:

```python
def test_oracle_registered():
    from launcher_support.research_desk.agents import AGENTS, BY_KEY, ORACLE
    assert ORACLE.key == "ORACLE"
    assert ORACLE.uuid == "2f790a10-55d1-4b4c-9a48-30db1e4cb73b"
    assert ORACLE.role == "Integrity Auditor"
    assert ORACLE in AGENTS
    assert BY_KEY["ORACLE"] is ORACLE
    assert len(AGENTS) == 5
```

- [ ] **Step 0.2: Run test, verify FAIL**

Run: `pytest tests/launcher/research_desk/test_scaffold.py::test_oracle_registered -v`
Expected: FAIL with ImportError or AssertionError (ORACLE not yet in agents.py).

- [ ] **Step 0.3: Add ORACLE to agents.py**

Add after `CURATOR = AgentIdentity(...)` (around line 78):

```python
ORACLE = AgentIdentity(
    key="ORACLE",
    uuid="2f790a10-55d1-4b4c-9a48-30db1e4cb73b",
    role="Integrity Auditor",
    archetype="The Oracle",
    stone="Gold",
    tagline="Oracular, cirurgical, veredito com evidencia.",
    typeface="serif-grave",
    artifact_dir="docs/audits/engines",
)
```

Change `AGENTS` tuple to `(SCRYER, ARBITER, ARTIFEX, CURATOR, ORACLE)`.

- [ ] **Step 0.4: Run test, verify PASS**

Run: `pytest tests/launcher/research_desk/test_scaffold.py::test_oracle_registered -v`
Expected: PASS.

- [ ] **Step 0.5: Full suite passes**

Run: `pytest tests/launcher/research_desk/ -q`
Expected: all pass (no regression from adding ORACLE).

- [ ] **Step 0.6: Commit**

```bash
git add launcher_support/research_desk/agents.py tests/launcher/research_desk/test_scaffold.py
git commit -m "feat(research-desk): register ORACLE as 5th operative

Paperclip instance already has ORACLE (uuid 2f790a10-...) and the repo-level
AGENTS.md §4 lists it. Add the missing AgentIdentity entry so the launcher's
research desk panel can discover it alongside SCRYER/ARBITER/ARTIFEX/CURATOR."
```

---

### Task 1: `alignment_scan.py` skeleton + engine_roster check (TDD)

**Files:**
- Create: `launcher_support/research_desk/alignment_scan.py`
- Create: `tests/launcher/research_desk/test_alignment_scan.py`

- [ ] **Step 1.1: Write the failing test**

Create `tests/launcher/research_desk/test_alignment_scan.py`:

```python
"""Alignment scan — drift checks between AURUM canon files and reality."""
from __future__ import annotations

from pathlib import Path

import pytest

from launcher_support.research_desk.alignment_scan import (
    AlignmentReport,
    CheckResult,
    run_alignment_scan,
    check_engine_roster,
)


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_run_alignment_scan_returns_report():
    report = run_alignment_scan(repo_root=REPO_ROOT)
    assert isinstance(report, AlignmentReport)
    assert report.overall in {"green", "yellow", "red"}
    assert set(report.checks.keys()) >= {"engine_roster"}
    assert all(isinstance(v, CheckResult) for v in report.checks.values())


def test_check_engine_roster_green_when_all_refs_valid(tmp_path):
    # Fixture: canon file cites only real engines
    canon = tmp_path / "AGENTS.md"
    canon.write_text("CITADEL, JUMP, and JANE STREET are our validated engines.")
    registered = {"citadel", "jump", "janestreet"}
    result = check_engine_roster([canon], registered_display_names={"CITADEL", "JUMP", "JANE STREET"})
    assert result.status == "green"
    assert result.details == []


def test_check_engine_roster_red_when_ghost_engine_referenced(tmp_path):
    canon = tmp_path / "AGENTS.md"
    canon.write_text("AZOTH and HERMES are our engines, plus CITADEL.")
    result = check_engine_roster([canon], registered_display_names={"CITADEL"})
    assert result.status == "red"
    # details lists the ghost engines
    ghost_names = {d["engine"] for d in result.details}
    assert "AZOTH" in ghost_names
    assert "HERMES" in ghost_names
    assert "CITADEL" not in ghost_names


def test_check_engine_roster_ignores_common_english_words(tmp_path):
    # UPPERCASE words in canon that are not engines should not be flagged
    canon = tmp_path / "AGENTS.md"
    canon.write_text("CORE files are PROTECTED. See MEMORY.md and CLAUDE.md.")
    result = check_engine_roster([canon], registered_display_names={"CITADEL"})
    # Should not flag CORE, PROTECTED, MEMORY, CLAUDE as ghost engines
    ghost_names = {d["engine"] for d in result.details}
    assert "CORE" not in ghost_names
    assert "PROTECTED" not in ghost_names
```

- [ ] **Step 1.2: Run test, verify FAIL**

Run: `pytest tests/launcher/research_desk/test_alignment_scan.py -v`
Expected: FAIL with ImportError.

- [ ] **Step 1.3: Create `alignment_scan.py`**

Create `launcher_support/research_desk/alignment_scan.py`:

```python
"""Alignment scan — detects drift between AURUM canon files and reality.

Pure-Python, no UI. Returns a structured AlignmentReport that the
alignment_panel.py widget renders.

Checks performed:
  1. engine_roster    — engine names cited in canon vs. config/engines.py
  2. path_existence   — filesystem paths referenced in canon exist
  3. protected_files  — MEMORY.md canonical list vs. references
  4. staleness        — persona mtime vs. canon mtime
  5. paperclip_sync   — ~/.paperclip/.../AGENTS.md presence + header match

Run via: run_alignment_scan(repo_root=Path("/path/to/aurum.finance"))
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


# English uppercase words that would false-positive as engine names.
# Keep minimal — only truly common words that can appear alone in canon prose.
COMMON_UPPER_WORDS: frozenset[str] = frozenset({
    "CORE", "MEMORY", "CONTEXT", "SKILLS", "AGENTS", "WORKFLOWS",
    "CLAUDE", "MD", "AURUM", "API", "CLI", "GUI", "UI", "SSL", "TLS",
    "HTTP", "HTTPS", "JSON", "CSV", "SQL", "HTML", "CSS", "USD", "USDT",
    "BTC", "ETH", "EOD", "OOS", "WF", "IS", "DSR", "SHIP", "ITERATE",
    "KILL", "MAJOR", "MINOR", "BLOCKER", "PASS", "FAIL", "TIPO", "TBD",
    "TODO", "ATENCAO", "VALIDATED", "REJECTED", "CONDITIONAL",
    "SCRYER", "ARBITER", "ARTIFEX", "CURATOR", "ORACLE",
    "PROTECTED", "OK", "NO", "YES", "N", "M", "ID", "IDS", "UUID",
    "READ", "WRITE", "EDIT", "PATCH", "POST", "GET", "DELETE",
    "LIVE", "TEST", "PROD", "DEV", "TDD", "RCE", "VPS", "EN", "PT",
    "BR", "UTF", "LOC", "PR", "CI", "CD", "QA", "PM", "SME",
    "AURUM", "BOARD", "ETA", "SST", "NO_EDGE", "INSUFFICIENT_SAMPLE",
    "NEEDS_REVIEW", "SAFE_TO_DELETE", "KEEP", "DUPLICATION", "DORMANT",
    "HEAD", "L", "N_OK", "N_TOTAL", "N_DIVERGE", "N_AUSENTE", "X",
    "Y", "Z", "IS", "WINNER", "MVP", "SSH", "REST", "SDK",
})

# Pattern: standalone uppercase identifier (2+ chars, all caps, optionally
# with underscores). Used to scan canon for potential engine references.
_ENGINE_REF_PATTERN = re.compile(r"\b([A-Z][A-Z0-9_]{1,})\b")


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


def check_engine_roster(
    canon_files: Iterable[Path],
    *,
    registered_display_names: set[str],
    ignore_words: frozenset[str] = COMMON_UPPER_WORDS,
) -> CheckResult:
    """Scan canon files for UPPERCASE tokens that look like engine names
    but are not registered in config/engines.py.

    Returns green when zero ghosts, red when >= 1 ghost is found.
    """
    # Also expand ignore set with the registered names themselves (in any form)
    valid_names = {name.upper().replace(" ", "_") for name in registered_display_names}
    valid_names |= {name.upper().replace(" ", "") for name in registered_display_names}
    valid_names |= {name.upper() for name in registered_display_names}

    ghosts: dict[str, list[str]] = {}  # engine_name -> list of files it appears in
    for f in canon_files:
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for match in _ENGINE_REF_PATTERN.finditer(text):
            token = match.group(1)
            # Skip: too short, pure digits, in ignore set, valid engine name
            if len(token) < 3 or token.isdigit():
                continue
            if token in ignore_words or token in valid_names:
                continue
            ghosts.setdefault(token, []).append(f.name)

    if not ghosts:
        return CheckResult(
            status="green",
            summary="Todas as referencias a engines batem com config/engines.py.",
            details=[],
        )

    details = [
        {"engine": name, "files": sorted(set(files))}
        for name, files in sorted(ghosts.items())
    ]
    return CheckResult(
        status="red",
        summary=f"{len(ghosts)} engine ref(s) fantasma — nao estao em config/engines.py.",
        details=details,
    )


def _collect_canon_files(repo_root: Path) -> list[Path]:
    """Return the list of canon files to scan."""
    root_files = ["CLAUDE.md", "AGENTS.md", "MEMORY.md", "CONTEXT.md", "SKILLS.md"]
    agents_dir = repo_root / "docs" / "agents"
    files: list[Path] = []
    for name in root_files:
        p = repo_root / name
        if p.exists():
            files.append(p)
    if agents_dir.exists():
        files.extend(sorted(agents_dir.glob("*.md")))
    return files


def _load_registered_engine_names(repo_root: Path) -> set[str]:
    """Load ENGINE_NAMES display values from config/engines.py."""
    import sys
    config_path = repo_root / "config"
    if str(config_path.parent) not in sys.path:
        sys.path.insert(0, str(config_path.parent))
    from config.engines import ENGINE_NAMES  # type: ignore[import-not-found]
    return set(ENGINE_NAMES.values())


def _aggregate_overall(checks: dict[str, CheckResult]) -> str:
    statuses = {c.status for c in checks.values()}
    if "red" in statuses:
        return "red"
    if "yellow" in statuses:
        return "yellow"
    return "green"


def run_alignment_scan(*, repo_root: Path) -> AlignmentReport:
    """Run all checks and return an aggregated report."""
    canon = _collect_canon_files(repo_root)
    registered = _load_registered_engine_names(repo_root)

    checks: dict[str, CheckResult] = {
        "engine_roster": check_engine_roster(canon, registered_display_names=registered),
    }

    return AlignmentReport(
        timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        overall=_aggregate_overall(checks),
        checks=checks,
    )
```

- [ ] **Step 1.4: Run test, verify PASS**

Run: `pytest tests/launcher/research_desk/test_alignment_scan.py -v`
Expected: all 4 tests pass.

- [ ] **Step 1.5: Commit**

```bash
git add launcher_support/research_desk/alignment_scan.py tests/launcher/research_desk/test_alignment_scan.py
git commit -m "feat(research-desk): alignment_scan skeleton + engine_roster check"
```

---

### Task 2: Add `path_existence` check (TDD)

**Files:**
- Modify: `launcher_support/research_desk/alignment_scan.py` (add check_path_existence + wire into run_alignment_scan)
- Modify: `tests/launcher/research_desk/test_alignment_scan.py` (add tests)

- [ ] **Step 2.1: Add failing tests**

Append to `test_alignment_scan.py`:

```python
from launcher_support.research_desk.alignment_scan import check_path_existence


def test_check_path_existence_green_when_all_paths_exist(tmp_path):
    existing = tmp_path / "real.py"
    existing.write_text("x = 1")
    canon = tmp_path / "canon.md"
    canon.write_text(f"See `{existing.relative_to(tmp_path)}` for details.")
    result = check_path_existence([canon], repo_root=tmp_path)
    assert result.status == "green"


def test_check_path_existence_red_when_broken_ref(tmp_path):
    canon = tmp_path / "canon.md"
    canon.write_text("See `does/not/exist.py` — also `still/missing.md`.")
    result = check_path_existence([canon], repo_root=tmp_path)
    assert result.status == "red"
    missing = {d["path"] for d in result.details}
    assert "does/not/exist.py" in missing
    assert "still/missing.md" in missing


def test_check_path_existence_ignores_urls(tmp_path):
    canon = tmp_path / "canon.md"
    canon.write_text("See [link](https://example.com/foo.md) for more.")
    result = check_path_existence([canon], repo_root=tmp_path)
    assert result.status == "green"


def test_run_alignment_scan_includes_path_existence():
    report = run_alignment_scan(repo_root=REPO_ROOT)
    assert "path_existence" in report.checks
```

- [ ] **Step 2.2: Run, verify FAIL**

Run: `pytest tests/launcher/research_desk/test_alignment_scan.py -v`
Expected: 4 new tests FAIL (ImportError for check_path_existence).

- [ ] **Step 2.3: Implement check_path_existence**

Add to `alignment_scan.py` (before run_alignment_scan):

```python
# Pattern: matches `path/to/file.ext` inside backticks.
# Excludes URLs (must not start with http:// or https://).
_PATH_REF_PATTERN = re.compile(r"`(?!https?://)([a-zA-Z0-9_./\\~-]+\.[a-zA-Z0-9]{1,6})`")


def check_path_existence(
    canon_files: Iterable[Path],
    *,
    repo_root: Path,
) -> CheckResult:
    """Scan canon files for backtick-quoted paths and verify they exist."""
    missing: dict[str, list[str]] = {}  # path -> files citing it
    for f in canon_files:
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for match in _PATH_REF_PATTERN.finditer(text):
            rel = match.group(1).replace("\\", "/")
            # Resolve relative to repo_root
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
        summary=f"{len(missing)} path(s) referenciado(s) mas inexistente(s).",
        details=details,
    )
```

Wire into `run_alignment_scan`:

```python
checks: dict[str, CheckResult] = {
    "engine_roster": check_engine_roster(canon, registered_display_names=registered),
    "path_existence": check_path_existence(canon, repo_root=repo_root),
}
```

- [ ] **Step 2.4: Run, verify PASS**

Run: `pytest tests/launcher/research_desk/test_alignment_scan.py -v`
Expected: all pass.

- [ ] **Step 2.5: Commit**

```bash
git add launcher_support/research_desk/alignment_scan.py tests/launcher/research_desk/test_alignment_scan.py
git commit -m "feat(research-desk): add path_existence check to alignment scan"
```

---

### Task 3: Add `staleness` check (TDD)

(Simpler than protected_files — let's do this first to keep momentum.)

**Files:**
- Modify: `launcher_support/research_desk/alignment_scan.py`
- Modify: `tests/launcher/research_desk/test_alignment_scan.py`

- [ ] **Step 3.1: Add failing tests**

Append:

```python
import os
import time
from launcher_support.research_desk.alignment_scan import check_staleness


def test_check_staleness_green_when_personas_fresher(tmp_path):
    canon = tmp_path / "MEMORY.md"
    canon.write_text("canon")
    personas_dir = tmp_path / "docs" / "agents"
    personas_dir.mkdir(parents=True)
    persona = personas_dir / "scryer.md"
    persona.write_text("persona")
    # Make persona 10s older than canon — should still be green (within threshold)
    now = time.time()
    os.utime(canon, (now, now))
    os.utime(persona, (now - 10, now - 10))
    result = check_staleness(
        personas=[persona],
        canon_files=[canon],
        max_age_days=14,
    )
    assert result.status == "green"


def test_check_staleness_yellow_when_persona_older_than_threshold(tmp_path):
    canon = tmp_path / "MEMORY.md"
    canon.write_text("canon")
    persona = tmp_path / "scryer.md"
    persona.write_text("persona")
    now = time.time()
    os.utime(canon, (now, now))
    # 20 days older than canon
    os.utime(persona, (now - 20 * 86400, now - 20 * 86400))
    result = check_staleness(
        personas=[persona],
        canon_files=[canon],
        max_age_days=14,
    )
    assert result.status == "yellow"
    assert len(result.details) == 1
    assert result.details[0]["persona"].endswith("scryer.md")


def test_run_alignment_scan_includes_staleness():
    report = run_alignment_scan(repo_root=REPO_ROOT)
    assert "staleness" in report.checks
```

- [ ] **Step 3.2: Run, verify FAIL**

Run: `pytest tests/launcher/research_desk/test_alignment_scan.py -v`
Expected: new tests FAIL.

- [ ] **Step 3.3: Implement check_staleness**

Add to `alignment_scan.py`:

```python
def check_staleness(
    *,
    personas: Iterable[Path],
    canon_files: Iterable[Path],
    max_age_days: int = 14,
) -> CheckResult:
    """Flag personas whose mtime is older than newest canon by >max_age_days."""
    canon_list = list(canon_files)
    if not canon_list:
        return CheckResult(status="yellow", summary="Nenhum canon file encontrado.", details=[])
    newest_canon_mtime = max(f.stat().st_mtime for f in canon_list)

    stale: list[dict] = []
    threshold_s = max_age_days * 86400
    for p in personas:
        try:
            age_s = newest_canon_mtime - p.stat().st_mtime
        except OSError:
            continue
        if age_s > threshold_s:
            stale.append({
                "persona": str(p),
                "age_days": round(age_s / 86400, 1),
            })

    if not stale:
        return CheckResult(status="green", summary="Personas frescas.", details=[])
    return CheckResult(
        status="yellow",
        summary=f"{len(stale)} persona(s) mais antigas que canon por >{max_age_days}d.",
        details=stale,
    )
```

Wire into `run_alignment_scan`:

```python
personas_dir = repo_root / "docs" / "agents"
personas = sorted(personas_dir.glob("*.md")) if personas_dir.exists() else []
checks["staleness"] = check_staleness(
    personas=personas, canon_files=canon, max_age_days=14,
)
```

- [ ] **Step 3.4: Run, verify PASS**

Run: `pytest tests/launcher/research_desk/test_alignment_scan.py -v`

- [ ] **Step 3.5: Commit**

```bash
git add launcher_support/research_desk/alignment_scan.py tests/launcher/research_desk/test_alignment_scan.py
git commit -m "feat(research-desk): add staleness check to alignment scan"
```

---

### Task 4: Add `paperclip_sync` check (TDD)

**Files:**
- Modify: `alignment_scan.py`
- Modify: `test_alignment_scan.py`

- [ ] **Step 4.1: Add failing tests**

```python
from launcher_support.research_desk.alignment_scan import check_paperclip_sync


def test_check_paperclip_sync_green_when_all_agents_file_present(tmp_path):
    # Build fake Paperclip tree
    company = "c2ccbb97-bda1-45db-ab53-5b2bb63962ee"
    cid_path = tmp_path / ".paperclip" / "instances" / "default" / "companies" / company / "agents"
    agents_map = {
        "SCRYER": "c28d2218-9941-4c44-a318-6d9d2df129d2",
        "ORACLE": "2f790a10-55d1-4b4c-9a48-30db1e4cb73b",
    }
    for name, uid in agents_map.items():
        inst_dir = cid_path / uid / "instructions"
        inst_dir.mkdir(parents=True)
        (inst_dir / "AGENTS.md").write_text(f"# {name} — Title here\n\nContent.")
    result = check_paperclip_sync(
        agents=agents_map,
        paperclip_home=tmp_path / ".paperclip",
        company_id=company,
    )
    assert result.status == "green"


def test_check_paperclip_sync_red_when_file_missing_or_header_mismatch(tmp_path):
    company = "c2ccbb97-bda1-45db-ab53-5b2bb63962ee"
    cid_path = tmp_path / ".paperclip" / "instances" / "default" / "companies" / company / "agents"
    agents_map = {
        "SCRYER": "aaa",  # file absent
        "ORACLE": "bbb",  # file present but wrong header
    }
    inst = cid_path / "bbb" / "instructions"
    inst.mkdir(parents=True)
    (inst / "AGENTS.md").write_text("# WRONG HEADER")
    result = check_paperclip_sync(
        agents=agents_map,
        paperclip_home=tmp_path / ".paperclip",
        company_id=company,
    )
    assert result.status == "red"
    issues = {d["agent"]: d for d in result.details}
    assert issues["SCRYER"]["reason"] == "missing"
    assert issues["ORACLE"]["reason"] == "header_mismatch"
```

- [ ] **Step 4.2: Verify FAIL**

- [ ] **Step 4.3: Implement check_paperclip_sync**

```python
def check_paperclip_sync(
    *,
    agents: dict[str, str],  # agent_key -> uuid
    paperclip_home: Path,
    company_id: str,
) -> CheckResult:
    """Verify each agent has an AGENTS.md in the Paperclip instance tree
    AND its first line starts with `# {AGENT_KEY}`."""
    base = paperclip_home / "instances" / "default" / "companies" / company_id / "agents"
    issues: list[dict] = []
    for key, uid in agents.items():
        f = base / uid / "instructions" / "AGENTS.md"
        if not f.exists():
            issues.append({"agent": key, "reason": "missing", "path": str(f)})
            continue
        try:
            first = f.read_text(encoding="utf-8").splitlines()[0] if f.read_text(encoding="utf-8") else ""
        except (OSError, UnicodeDecodeError):
            issues.append({"agent": key, "reason": "unreadable", "path": str(f)})
            continue
        if not first.startswith(f"# {key}"):
            issues.append({
                "agent": key,
                "reason": "header_mismatch",
                "path": str(f),
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
```

Wire into `run_alignment_scan`:

```python
from launcher_support.research_desk.agents import AGENTS as AGENT_ROSTER, COMPANY_ID

paperclip_home = Path.home() / ".paperclip"
agents_map = {a.key: a.uuid for a in AGENT_ROSTER}
checks["paperclip_sync"] = check_paperclip_sync(
    agents=agents_map,
    paperclip_home=paperclip_home,
    company_id=COMPANY_ID,
)
```

- [ ] **Step 4.4: Verify PASS**

- [ ] **Step 4.5: Commit**

```bash
git add launcher_support/research_desk/alignment_scan.py tests/launcher/research_desk/test_alignment_scan.py
git commit -m "feat(research-desk): add paperclip_sync check to alignment scan"
```

---

### Task 5: Add `protected_files` check (TDD)

**Files:**
- Modify: `alignment_scan.py`
- Modify: `test_alignment_scan.py`

- [ ] **Step 5.1: Add failing tests**

```python
from launcher_support.research_desk.alignment_scan import check_protected_files


def test_check_protected_files_green_when_all_canonical_exist(tmp_path):
    # Create the canonical files
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "indicators.py").write_text("x = 1")
    (tmp_path / "core" / "signals.py").write_text("x = 1")
    (tmp_path / "core" / "portfolio.py").write_text("x = 1")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "params.py").write_text("x = 1")
    result = check_protected_files(
        canonical=[
            "core/indicators.py",
            "core/signals.py",
            "core/portfolio.py",
            "config/params.py",
        ],
        repo_root=tmp_path,
    )
    assert result.status == "green"


def test_check_protected_files_red_when_missing(tmp_path):
    result = check_protected_files(
        canonical=["core/indicators.py", "config/params.py"],
        repo_root=tmp_path,
    )
    assert result.status == "red"
    missing = {d["path"] for d in result.details}
    assert "core/indicators.py" in missing
    assert "config/params.py" in missing
```

- [ ] **Step 5.2: Verify FAIL**

- [ ] **Step 5.3: Implement check_protected_files**

```python
def check_protected_files(
    *,
    canonical: Iterable[str],
    repo_root: Path,
) -> CheckResult:
    """Verify each canonical protected file exists in the repo."""
    missing: list[dict] = []
    for rel in canonical:
        p = repo_root / rel
        if not p.exists():
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
```

Wire into `run_alignment_scan`:

```python
CANONICAL_PROTECTED = [
    "core/indicators.py",
    "core/signals.py",
    "core/portfolio.py",
    "config/params.py",
]
checks["protected_files"] = check_protected_files(
    canonical=CANONICAL_PROTECTED, repo_root=repo_root,
)
```

- [ ] **Step 5.4: Verify PASS**

- [ ] **Step 5.5: Commit**

```bash
git add launcher_support/research_desk/alignment_scan.py tests/launcher/research_desk/test_alignment_scan.py
git commit -m "feat(research-desk): add protected_files check to alignment scan"
```

---

### Task 6: `alignment_panel.py` — TkInter widget (TDD light — render only)

**Files:**
- Create: `launcher_support/research_desk/alignment_panel.py`
- Create: `tests/launcher/research_desk/test_alignment_panel.py`

- [ ] **Step 6.1: Add test**

Since TkInter unit testing is heavy, limit to structural test:

```python
"""Alignment panel — renders AlignmentReport into a Tk widget."""
import tkinter as tk
import pytest

from launcher_support.research_desk.alignment_panel import build_alignment_frame
from launcher_support.research_desk.alignment_scan import (
    AlignmentReport, CheckResult,
)


@pytest.fixture
def _tk_root():
    root = tk.Tk()
    root.withdraw()
    yield root
    try:
        root.destroy()
    except tk.TclError:
        pass


def test_build_alignment_frame_returns_frame(_tk_root):
    report = AlignmentReport(
        timestamp="2026-04-24T14:00:00Z",
        overall="green",
        checks={
            "engine_roster": CheckResult(status="green", summary="OK"),
        },
    )
    frame = build_alignment_frame(_tk_root, report, on_refresh=lambda: None)
    assert isinstance(frame, tk.Frame) or isinstance(frame, tk.Widget)
    # Must contain a label mentioning the timestamp
    descendants = frame.winfo_children()
    assert len(descendants) > 0
```

- [ ] **Step 6.2: Verify FAIL**

- [ ] **Step 6.3: Implement alignment_panel.py**

```python
"""Alignment panel — TkInter widget rendering an AlignmentReport.

Usage from the research_desk container:

    from launcher_support.research_desk.alignment_panel import build_alignment_frame
    from launcher_support.research_desk.alignment_scan import run_alignment_scan

    report = run_alignment_scan(repo_root=REPO_ROOT)
    frame = build_alignment_frame(parent, report, on_refresh=rebuild_callback)
    frame.pack(fill="both", expand=True)
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from launcher_support.research_desk.alignment_scan import AlignmentReport, CheckResult


_STATUS_GLYPH = {"green": "🟢", "yellow": "🟡", "red": "🔴"}
_STATUS_COLOR = {"green": "#22c55e", "yellow": "#eab308", "red": "#ef4444"}


def build_alignment_frame(
    parent: tk.Misc,
    report: AlignmentReport,
    *,
    on_refresh: Callable[[], None],
    on_export: Callable[[], None] | None = None,
) -> tk.Frame:
    """Build and return a Frame widget that renders the given report.
    Caller is responsible for pack/grid."""
    frame = tk.Frame(parent)

    # Header
    header = tk.Frame(frame)
    header.pack(fill="x", padx=8, pady=(8, 4))

    overall_glyph = _STATUS_GLYPH.get(report.overall, "?")
    overall_color = _STATUS_COLOR.get(report.overall, "#64748b")
    tk.Label(header, text=f"{overall_glyph} Alignment", font=("", 14, "bold"), fg=overall_color).pack(side="left")
    tk.Label(header, text=f"  last scan: {report.timestamp}", fg="#64748b").pack(side="left")
    tk.Button(header, text="↻ Refresh", command=on_refresh).pack(side="right", padx=2)
    if on_export is not None:
        tk.Button(header, text="Export audit →", command=on_export).pack(side="right", padx=2)

    # Rows
    for name, result in report.checks.items():
        _build_row(frame, name, result).pack(fill="x", padx=8, pady=2)

    return frame


def _build_row(parent: tk.Misc, name: str, result: CheckResult) -> tk.Frame:
    row = tk.Frame(parent, relief="solid", borderwidth=1)
    top = tk.Frame(row)
    top.pack(fill="x", padx=6, pady=4)

    glyph = _STATUS_GLYPH.get(result.status, "?")
    color = _STATUS_COLOR.get(result.status, "#64748b")
    tk.Label(top, text=glyph, font=("", 12), fg=color).pack(side="left")
    tk.Label(top, text=name.replace("_", " "), font=("", 11, "bold")).pack(side="left", padx=6)
    tk.Label(top, text=result.summary, fg="#475569").pack(side="left", padx=6)

    # Details expander (only if there are details)
    if result.details:
        detail_var = tk.BooleanVar(value=False)
        detail_frame = tk.Frame(row)

        def toggle():
            if detail_var.get():
                detail_frame.pack_forget()
                detail_var.set(False)
                toggle_btn.config(text="▸ details")
            else:
                detail_frame.pack(fill="x", padx=6, pady=(0, 4))
                detail_var.set(True)
                toggle_btn.config(text="▾ details")

        toggle_btn = tk.Button(top, text=f"▸ details ({len(result.details)})", command=toggle, relief="flat")
        toggle_btn.pack(side="right")

        for i, detail in enumerate(result.details[:20]):  # cap rendering
            line = ", ".join(f"{k}={v}" for k, v in detail.items())
            tk.Label(detail_frame, text=f"• {line}", anchor="w", justify="left", fg="#334155").pack(fill="x")
        if len(result.details) > 20:
            tk.Label(detail_frame, text=f"... and {len(result.details) - 20} more", fg="#94a3b8").pack(fill="x")

    return row
```

- [ ] **Step 6.4: Verify PASS**

Run: `pytest tests/launcher/research_desk/test_alignment_panel.py -v`

- [ ] **Step 6.5: Commit**

```bash
git add launcher_support/research_desk/alignment_panel.py tests/launcher/research_desk/test_alignment_panel.py
git commit -m "feat(research-desk): alignment_panel TkInter widget"
```

---

### Task 7: Wire alignment panel into research desk container + manual smoke

**Files:**
- Investigate + modify the research desk container. Candidates: `pipeline_panel.py`, `agent_view.py`, or entry via `engines_sidebar.py`.
- Add a button "Alignment" in the existing sidebar or header that opens a modal containing the panel.

- [ ] **Step 7.1: Identify the container**

Run: `grep -rn "research_desk\|RESEARCH DESK" C:/Users/Joao/projects/aurum.finance/launcher_support/ launcher.py | head -20`

Pick the file that builds the research desk tab/screen and is the natural home for the Alignment button.

- [ ] **Step 7.2: Add a button + modal**

Add in the chosen container:

```python
def _open_alignment_modal(self):
    from pathlib import Path
    import tkinter as tk
    from launcher_support.research_desk.alignment_scan import run_alignment_scan
    from launcher_support.research_desk.alignment_panel import build_alignment_frame

    modal = tk.Toplevel(self)
    modal.title("Alignment Status")
    modal.geometry("720x720")

    REPO_ROOT = Path(__file__).resolve().parents[2]

    def rebuild():
        for w in modal.winfo_children():
            w.destroy()
        report = run_alignment_scan(repo_root=REPO_ROOT)
        frame = build_alignment_frame(modal, report, on_refresh=rebuild)
        frame.pack(fill="both", expand=True)

    rebuild()
```

Wire this to a button in the sidebar/header of the research desk container.

- [ ] **Step 7.3: Manual smoke test**

```bash
python launcher.py
```

Navigate to the research desk, click Alignment. Expected:
- Modal opens 720x720
- Header shows overall status + timestamp + Refresh button
- 5 rows (engine_roster, path_existence, protected_files, staleness, paperclip_sync)
- On current repo state, most should be green; Refresh reloads.

- [ ] **Step 7.4: Commit**

```bash
git add <chosen container file>
git commit -m "feat(research-desk): wire alignment panel into launcher UI"
```

---

### Task 8: Final audit + export feature (optional, nice-to-have)

- [ ] **Step 8.1: Add `export_audit_markdown` function to alignment_scan.py**

Write a simple markdown serializer that turns an AlignmentReport into a `docs/audits/repo/YYYY-MM-DD_alignment.md` file.

- [ ] **Step 8.2: Wire `on_export` in the panel container**

- [ ] **Step 8.3: Commit**

---

## Self-review notes

- **Placeholder scan:** no TBDs or generic "add X" — all code is concrete.
- **Type consistency:** `CheckResult` and `AlignmentReport` dataclasses used consistently; `check_*` functions all return `CheckResult`.
- **Scope:** single feature (alignment panel) with one preliminary fix (Task 0: add ORACLE). Not mixing concerns.
- **Spec coverage:**
  - (A) Alignment status panel → all 5 checks implemented (Tasks 1-5)
  - TkInter widget → Task 6
  - UI integration → Task 7
  - Export → Task 8

Execution order is linear: Task 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8.
