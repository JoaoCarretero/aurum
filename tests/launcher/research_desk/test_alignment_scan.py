"""Alignment scan — drift checks between AURUM canon files and reality."""
from __future__ import annotations

from pathlib import Path

import pytest

from launcher_support.research_desk.alignment_scan import (
    AlignmentReport,
    CheckResult,
    check_engine_roster,
    check_path_existence,
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
