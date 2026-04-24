"""Tests do artifact_scanner — usa tmp filesystem, sem git real."""
from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

from launcher_support.research_desk.artifact_scanner import (
    ArtifactEntry,
    _scan_experiment_branches,
    _scan_markdown_dir,
    relative_age,
    scan_artifacts,
)


def _write(path: Path, content: str = "# x\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_scan_markdown_dir_missing_returns_empty(tmp_path: Path) -> None:
    assert _scan_markdown_dir(
        root=tmp_path, rel_dir="docs/nonexistent",
        agent_key="RESEARCH", kind="spec",
    ) == []


def test_scan_markdown_dir_lists_nested(tmp_path: Path) -> None:
    _write(tmp_path / "docs/specs/a.md")
    _write(tmp_path / "docs/specs/sub/b.md")
    # Nao-md e ignorado
    _write(tmp_path / "docs/specs/c.txt", "x")

    out = _scan_markdown_dir(
        root=tmp_path, rel_dir="docs/specs",
        agent_key="RESEARCH", kind="spec",
    )
    titles = {e.title for e in out}
    assert titles == {"a", "b"}
    for e in out:
        assert e.agent_key == "RESEARCH"
        assert e.kind == "spec"
        assert e.is_markdown is True
        assert e.path.startswith("docs/specs/")


def test_scan_artifacts_aggregates_all_agents(tmp_path: Path) -> None:
    _write(tmp_path / "docs/specs/spec-one.md")
    _write(tmp_path / "docs/reviews/review-one.md")
    _write(tmp_path / "docs/audits/audit-one.md")
    # Sem git — branch scan retorna []
    with patch("subprocess.run") as run_mock:
        run_mock.return_value.returncode = 0
        run_mock.return_value.stdout = ""
        entries = scan_artifacts(tmp_path, limit=100)

    keys = {e.agent_key for e in entries}
    kinds = {e.kind for e in entries}
    assert keys == {"RESEARCH", "REVIEW", "CURATE"}
    assert kinds == {"spec", "review", "audit"}


def test_scan_respects_limit(tmp_path: Path) -> None:
    for i in range(10):
        _write(tmp_path / f"docs/specs/spec_{i}.md")
    with patch("subprocess.run") as run_mock:
        run_mock.return_value.returncode = 0
        run_mock.return_value.stdout = ""
        entries = scan_artifacts(tmp_path, limit=3)
    assert len(entries) == 3


def test_scan_sorts_by_mtime_desc(tmp_path: Path) -> None:
    oldish = tmp_path / "docs/specs/old.md"
    newish = tmp_path / "docs/specs/new.md"
    _write(oldish)
    _write(newish)
    # Forca timestamps distintos
    import os
    now = time.time()
    os.utime(oldish, (now - 1000, now - 1000))
    os.utime(newish, (now, now))

    with patch("subprocess.run") as run_mock:
        run_mock.return_value.returncode = 0
        run_mock.return_value.stdout = ""
        entries = scan_artifacts(tmp_path)

    names = [e.title for e in entries]
    assert names.index("new") < names.index("old")


def test_experiment_branches_parse_output(tmp_path: Path) -> None:
    fake_stdout = (
        "experiment/phi-fib|1700000000\n"
        "experiment/kepos-hawkes|1710000000\n"
    )
    with patch("subprocess.run") as run_mock:
        run_mock.return_value.returncode = 0
        run_mock.return_value.stdout = fake_stdout
        out = _scan_experiment_branches(root=tmp_path)

    titles = [e.title for e in out]
    assert titles == ["phi-fib", "kepos-hawkes"]
    for e in out:
        assert e.agent_key == "BUILD"
        assert e.kind == "branch"
        assert e.is_markdown is False


def test_experiment_branches_handles_timeout(tmp_path: Path) -> None:
    import subprocess

    with patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="git", timeout=3.0),
    ):
        assert _scan_experiment_branches(root=tmp_path) == []


def test_experiment_branches_handles_nonzero_exit(tmp_path: Path) -> None:
    with patch("subprocess.run") as run_mock:
        run_mock.return_value.returncode = 128
        run_mock.return_value.stdout = ""
        assert _scan_experiment_branches(root=tmp_path) == []


def test_relative_age_fresh() -> None:
    entry = ArtifactEntry(
        agent_key="RESEARCH", kind="spec", title="x", path="x.md",
        mtime_epoch=time.time() - 120, is_markdown=True,
    )
    age = relative_age(entry)
    assert "min" in age or "s" in age


def test_relative_age_zero_returns_dash() -> None:
    entry = ArtifactEntry(
        agent_key="RESEARCH", kind="spec", title="x", path="x.md",
        mtime_epoch=0, is_markdown=True,
    )
    assert relative_age(entry) == "—"


def test_relative_age_days() -> None:
    entry = ArtifactEntry(
        agent_key="RESEARCH", kind="spec", title="x", path="x.md",
        mtime_epoch=time.time() - 3 * 86400, is_markdown=True,
    )
    assert relative_age(entry).endswith("d atras")
