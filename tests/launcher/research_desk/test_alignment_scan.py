"""Alignment scan — drift checks between AURUM canon files and reality."""
from __future__ import annotations

from pathlib import Path

from launcher_support.research_desk.alignment_scan import (
    AlignmentReport,
    CheckResult,
    check_engine_roster,
    check_paperclip_sync,
    check_path_existence,
    check_protected_files,
    check_staleness,
    run_alignment_scan,
)


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_run_alignment_scan_returns_report() -> None:
    report = run_alignment_scan(repo_root=REPO_ROOT)
    assert isinstance(report, AlignmentReport)
    assert report.overall in {"green", "yellow", "red"}
    assert set(report.checks.keys()) >= {"engine_roster"}
    assert all(isinstance(v, CheckResult) for v in report.checks.values())


def test_check_engine_roster_green_when_bold_refs_valid(tmp_path: Path) -> None:
    """Bold engine refs that exist in the registry should pass."""
    canon = tmp_path / "AGENTS.md"
    canon.write_text(
        "The **CITADEL** and **JUMP** engines are validated. "
        "**JANE STREET** handles arbitrage."
    )
    result = check_engine_roster(
        [canon], registered_display_names={"CITADEL", "JUMP", "JANE STREET"}
    )
    assert result.status == "green"
    assert result.details == []


def test_check_engine_roster_red_when_ghost_bold_engine(tmp_path: Path) -> None:
    """Bold engine name NOT in registry should be flagged."""
    canon = tmp_path / "AGENTS.md"
    canon.write_text("Our engines are **AZOTH**, **HERMES**, and **CITADEL**.")
    result = check_engine_roster([canon], registered_display_names={"CITADEL"})
    assert result.status == "red"
    ghost_names = {d["engine"] for d in result.details}
    assert "AZOTH" in ghost_names
    assert "HERMES" in ghost_names
    assert "CITADEL" not in ghost_names


def test_check_engine_roster_ignores_non_bold_uppercase(tmp_path: Path) -> None:
    """Plain (non-bold) uppercase tokens are NOT engine-ref candidates."""
    canon = tmp_path / "AGENTS.md"
    canon.write_text(
        "AZOTH and HERMES used to exist but are gone. CORE files are PROTECTED."
    )
    result = check_engine_roster([canon], registered_display_names={"CITADEL"})
    # No bold — no flags.
    assert result.status == "green"
    assert result.details == []


def test_check_engine_roster_ignores_operatives(tmp_path: Path) -> None:
    """Operative names (SCRYER/ARBITER/...) in bold are not engine refs."""
    canon = tmp_path / "AGENTS.md"
    canon.write_text(
        "**SCRYER** produces specs; **ARBITER** reviews them; **ARTIFEX** codes."
    )
    result = check_engine_roster([canon], registered_display_names={"CITADEL"})
    assert result.status == "green"


def test_check_engine_roster_ignores_bold_prose_tokens(tmp_path: Path) -> None:
    """Known bold prose markers (NUNCA, MUST USE, etc) are not flagged."""
    canon = tmp_path / "AGENTS.md"
    canon.write_text("**NUNCA** modify CORE. This is **MUST USE**.")
    result = check_engine_roster([canon], registered_display_names={"CITADEL"})
    assert result.status == "green"


# ── check_path_existence ──────────────────────────────────────────
def test_check_path_existence_green_when_all_paths_exist(tmp_path: Path) -> None:
    existing = tmp_path / "engines" / "foo.py"
    existing.parent.mkdir(parents=True)
    existing.write_text("x = 1")
    canon = tmp_path / "AGENTS.md"
    canon.write_text("See `engines/foo.py` for the impl.")
    result = check_path_existence([canon], repo_root=tmp_path)
    assert result.status == "green"
    assert result.details == []


def test_check_path_existence_red_when_broken_ref(tmp_path: Path) -> None:
    canon = tmp_path / "AGENTS.md"
    canon.write_text("See `docs/nope.md` and `src/missing.py`.")
    result = check_path_existence([canon], repo_root=tmp_path)
    assert result.status == "red"
    missing = {d["path"] for d in result.details}
    assert "docs/nope.md" in missing
    assert "src/missing.py" in missing


def test_check_path_existence_ignores_urls(tmp_path: Path) -> None:
    canon = tmp_path / "AGENTS.md"
    canon.write_text(
        "Paper at `https://arxiv.org/abs/2101.foo.pdf` and `http://example.com/x.md`."
    )
    result = check_path_existence([canon], repo_root=tmp_path)
    assert result.status == "green"


def test_check_path_existence_ignores_absolute_paths(tmp_path: Path) -> None:
    canon = tmp_path / "AGENTS.md"
    canon.write_text("Secrets live at `/etc/secret.key` and `C:\\\\config\\\\keys.json`.")
    result = check_path_existence([canon], repo_root=tmp_path)
    # Absolute paths are out of scope — treat as green (not flagged).
    assert result.status == "green"


def test_check_path_existence_ignores_home_dir_refs(tmp_path: Path) -> None:
    """Paths starting with ~ are home-dir refs, out of repo scope."""
    canon = tmp_path / "AGENTS.md"
    canon.write_text(
        "Config in `~/.claude/keybindings.json` and `~/.paperclip/foo/bar.md`."
    )
    result = check_path_existence([canon], repo_root=tmp_path)
    assert result.status == "green"


def test_check_path_existence_ignores_bare_filenames(tmp_path: Path) -> None:
    """Bare filenames without a slash are prose, not real paths."""
    canon = tmp_path / "AGENTS.md"
    canon.write_text(
        "Each engine has a `grid.md` template. Also see `json.load` calls."
    )
    result = check_path_existence([canon], repo_root=tmp_path)
    assert result.status == "green"


def test_check_path_existence_ignores_template_placeholders(tmp_path: Path) -> None:
    """Paths with YYYY-MM-DD or <engine> placeholders are templates."""
    canon = tmp_path / "AGENTS.md"
    canon.write_text(
        "Session logs: `docs/sessions/YYYY-MM-DD_HHMM.md`\n"
        "Engine docs: `docs/engines/<engine>/hypothesis.md`"
    )
    result = check_path_existence([canon], repo_root=tmp_path)
    assert result.status == "green"


def test_run_alignment_scan_includes_path_existence() -> None:
    report = run_alignment_scan(repo_root=REPO_ROOT)
    assert "path_existence" in report.checks


# ── check_staleness ──────────────────────────────────────────────
def test_check_staleness_green_when_personas_fresher(tmp_path: Path) -> None:
    import os
    import time

    canon = tmp_path / "MEMORY.md"
    canon.write_text("canon")
    persona = tmp_path / "scryer.md"
    persona.write_text("persona")
    now = time.time()
    os.utime(canon, (now, now))
    os.utime(persona, (now - 10, now - 10))  # persona 10s older — within threshold
    result = check_staleness(personas=[persona], canon_files=[canon], max_age_days=14)
    assert result.status == "green"


def test_check_staleness_yellow_when_persona_older_than_threshold(tmp_path: Path) -> None:
    import os
    import time

    canon = tmp_path / "MEMORY.md"
    canon.write_text("canon")
    persona = tmp_path / "scryer.md"
    persona.write_text("persona")
    now = time.time()
    os.utime(canon, (now, now))
    os.utime(persona, (now - 20 * 86400, now - 20 * 86400))  # 20 days older
    result = check_staleness(personas=[persona], canon_files=[canon], max_age_days=14)
    assert result.status == "yellow"
    assert len(result.details) == 1
    assert result.details[0]["persona"] == "scryer.md"


def test_check_staleness_yellow_when_no_canon(tmp_path: Path) -> None:
    result = check_staleness(personas=[], canon_files=[], max_age_days=14)
    assert result.status == "yellow"


# ── check_paperclip_sync ─────────────────────────────────────────
def test_check_paperclip_sync_green_when_all_present(tmp_path: Path) -> None:
    company = "c2ccbb97-bda1-45db-ab53-5b2bb63962ee"
    base = tmp_path / ".paperclip" / "instances" / "default" / "companies" / company / "agents"
    agents_map = {
        "SCRYER": "c28d2218-9941-4c44-a318-6d9d2df129d2",
        "ORACLE": "2f790a10-55d1-4b4c-9a48-30db1e4cb73b",
    }
    for name, uid in agents_map.items():
        inst = base / uid / "instructions"
        inst.mkdir(parents=True)
        (inst / "AGENTS.md").write_text(f"# {name} - Title\n\nBody.", encoding="utf-8")
    result = check_paperclip_sync(
        agents=agents_map, paperclip_home=tmp_path / ".paperclip", company_id=company,
    )
    assert result.status == "green"


def test_check_paperclip_sync_handles_utf8_bom_from_paperclip(tmp_path: Path) -> None:
    """Paperclip (Node.js/Electron) may write files with UTF-8 BOM on Windows.
    The sync check must strip BOM or it would falsely flag every agent as
    header_mismatch on this platform.
    """
    company = "c2ccbb97-bda1-45db-ab53-5b2bb63962ee"
    base = tmp_path / ".paperclip" / "instances" / "default" / "companies" / company / "agents"
    agents_map = {"ORACLE": "2f790a10-9941-4c44-a318-6d9d2df129d2"}
    inst = base / "2f790a10-9941-4c44-a318-6d9d2df129d2" / "instructions"
    inst.mkdir(parents=True)
    # Write file WITH UTF-8 BOM prepended (simulates Electron/Node output)
    import codecs
    (inst / "AGENTS.md").write_bytes(
        codecs.BOM_UTF8 + b"# ORACLE - Integrity Auditor\n\nBody."
    )
    result = check_paperclip_sync(
        agents=agents_map, paperclip_home=tmp_path / ".paperclip", company_id=company,
    )
    assert result.status == "green", f"BOM should be stripped, got details: {result.details}"


def test_check_paperclip_sync_red_when_missing_or_header_mismatch(tmp_path: Path) -> None:
    company = "c2ccbb97-bda1-45db-ab53-5b2bb63962ee"
    base = tmp_path / ".paperclip" / "instances" / "default" / "companies" / company / "agents"
    agents_map = {
        "SCRYER": "aaa",  # file absent
        "ORACLE": "bbb",  # file present but wrong header
    }
    inst = base / "bbb" / "instructions"
    inst.mkdir(parents=True)
    (inst / "AGENTS.md").write_text("# WRONG", encoding="utf-8")
    result = check_paperclip_sync(
        agents=agents_map, paperclip_home=tmp_path / ".paperclip", company_id=company,
    )
    assert result.status == "red"
    issues = {d["agent"]: d for d in result.details}
    assert issues["SCRYER"]["reason"] == "missing"
    assert issues["ORACLE"]["reason"] == "header_mismatch"


# ── check_protected_files ────────────────────────────────────────
def test_check_protected_files_green_when_all_present(tmp_path: Path) -> None:
    (tmp_path / "core").mkdir()
    (tmp_path / "core" / "indicators.py").write_text("x = 1")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "params.py").write_text("x = 1")
    result = check_protected_files(
        canonical=["core/indicators.py", "config/params.py"], repo_root=tmp_path,
    )
    assert result.status == "green"


def test_check_protected_files_red_when_missing(tmp_path: Path) -> None:
    result = check_protected_files(
        canonical=["core/indicators.py", "config/params.py"], repo_root=tmp_path,
    )
    assert result.status == "red"
    missing = {d["path"] for d in result.details}
    assert "core/indicators.py" in missing
    assert "config/params.py" in missing


def test_run_alignment_scan_includes_all_five_checks() -> None:
    report = run_alignment_scan(repo_root=REPO_ROOT)
    assert set(report.checks.keys()) == {
        "engine_roster",
        "path_existence",
        "staleness",
        "paperclip_sync",
        "protected_files",
    }


def test_load_registered_engine_names_raises_when_config_missing(tmp_path: Path) -> None:
    """If config/engines.py is missing or broken, the scan must raise loudly
    instead of silently returning an empty set (which would greenwash the
    engine_roster check)."""
    import pytest
    from launcher_support.research_desk.alignment_scan import (
        EngineRegistryLoadError,
        _load_registered_engine_names,
    )

    with pytest.raises(EngineRegistryLoadError):
        _load_registered_engine_names(tmp_path)  # no config/engines.py here
