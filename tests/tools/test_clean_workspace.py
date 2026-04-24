from __future__ import annotations

from pathlib import Path

from tools.maintenance.clean_workspace import clean, iter_targets


def test_iter_targets_collects_known_cache_dirs(tmp_path: Path):
    pycache = tmp_path / "pkg" / "__pycache__"
    pytest_tmp = tmp_path / ".pytest_tmp_abc"
    tests_tmp = tmp_path / "tests" / "_tmp"
    pycache.mkdir(parents=True)
    pytest_tmp.mkdir()
    tests_tmp.mkdir(parents=True)

    targets = iter_targets(root=tmp_path)

    assert pycache in targets
    assert pytest_tmp in targets
    assert tests_tmp in targets


def test_clean_dry_run_does_not_remove_targets(tmp_path: Path, capsys):
    target = tmp_path / ".pytest_cache"
    target.mkdir()

    removed, skipped = clean(root=tmp_path, apply=False)

    assert removed == 0
    assert skipped == 1
    assert target.exists()
    assert "would remove .pytest_cache" in capsys.readouterr().out


def test_clean_apply_removes_targets(tmp_path: Path):
    target = tmp_path / "tests" / "_tmp"
    child = target / "artifact.txt"
    target.mkdir(parents=True)
    child.write_text("x", encoding="utf-8")

    removed, skipped = clean(root=tmp_path, apply=True)

    assert removed == 1
    assert skipped == 0
    assert not target.exists()
