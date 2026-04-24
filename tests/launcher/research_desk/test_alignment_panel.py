"""Alignment panel — smoke tests for the TkInter modal.

Heavy UI wiring is exercised manually (Task 7 manual smoke). These tests
only verify basic constructability + markdown serialization.
"""
from __future__ import annotations

import tkinter as tk

import pytest

from launcher_support.research_desk.alignment_panel import (
    AlignmentModal,
    _format_detail,
    _render_markdown,
    open_alignment_modal,
)
from launcher_support.research_desk.alignment_scan import (
    AlignmentReport,
    CheckResult,
)


@pytest.fixture(scope="module")
def _tk_root():
    """Module-scoped Tk root — mirrors test_sigils.py pattern. Per-test
    Tk() creation exhausts Windows Tk state in large suites, causing
    spurious skips downstream (test_sigils saw this in pre-review runs)."""
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("No display available for Tk.")
        return  # type: ignore[return-value]
    root.withdraw()
    yield root
    try:
        root.destroy()
    except tk.TclError:
        pass


def test_open_alignment_modal_builds(_tk_root, tmp_path) -> None:
    """Opening the modal against a tmp_path repo should actually render
    widgets — not just construct an empty shell with exceptions swallowed."""
    # Minimal fake repo: just need config/engines.py + docs/agents/ to avoid
    # exceptions in run_alignment_scan.
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "engines.py").write_text(
        "ENGINES = {}\nENGINE_NAMES = {}\n", encoding="utf-8",
    )
    (tmp_path / "docs" / "agents").mkdir(parents=True)
    modal = open_alignment_modal(_tk_root, root_path=tmp_path)

    assert isinstance(modal, AlignmentModal)
    assert not modal._closed
    # Body frame must exist AND have children rendered (one per check).
    # Without this, a silent scan failure would leave an empty body and
    # still pass the test.
    assert modal._body_frame is not None
    assert len(modal._body_frame.winfo_children()) > 0
    # _last_report must be populated — proves _refresh() completed.
    assert modal._last_report is not None
    assert set(modal._last_report.checks.keys()) == {
        "engine_roster",
        "path_existence",
        "staleness",
        "paperclip_sync",
        "protected_files",
    }

    modal._close()
    assert modal._closed


def test_format_detail_engine() -> None:
    out = _format_detail({"engine": "AZOTH", "files": ["AGENTS.md", "MEMORY.md"]})
    assert "AZOTH" in out
    assert "AGENTS.md" in out


def test_format_detail_path() -> None:
    out = _format_detail({"path": "engines/ghost.py", "cited_in": ["CLAUDE.md"]})
    assert "engines/ghost.py" in out
    assert "CLAUDE.md" in out


def test_format_detail_agent() -> None:
    out = _format_detail({"agent": "SCRYER", "reason": "missing"})
    assert "SCRYER" in out
    assert "missing" in out


def test_format_detail_persona() -> None:
    out = _format_detail({"persona": "scryer.md", "days_behind_canon": 5.2})
    assert "scryer.md" in out
    assert "5.2" in out


def test_render_markdown_has_sections() -> None:
    report = AlignmentReport(
        timestamp="2026-04-24T14:00:00Z",
        overall="yellow",
        checks={
            "engine_roster": CheckResult(
                status="green", summary="Todas as refs batem.", details=[],
            ),
            "staleness": CheckResult(
                status="yellow",
                summary="1 persona stale.",
                details=[{"persona": "scryer.md", "days_behind_canon": 20.0}],
            ),
        },
    )
    md = _render_markdown(report)
    assert "# Alignment audit" in md
    assert "YELLOW" in md
    assert "engine roster" in md
    assert "staleness" in md
    assert "scryer.md" in md
