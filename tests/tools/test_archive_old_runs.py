"""Unit tests for archive_old_runs retention."""
from __future__ import annotations

import zipfile
from datetime import datetime
from pathlib import Path


from tools.maintenance.archive_old_runs import select_to_archive, archive_and_remove


def _mkrun(parent: Path, name: str, age_days: int) -> Path:
    run = parent / name
    run.mkdir(parents=True)
    (run / "state").mkdir()
    (run / "state" / "x.json").write_text("{}")
    ts = datetime.now().timestamp() - age_days * 86400
    import os
    os.utime(run, (ts, ts))
    return run


def test_select_to_archive_keeps_last_n(tmp_path: Path):
    parent = tmp_path / "engine"
    parent.mkdir()
    for i in range(15):
        _mkrun(parent, f"2026-04-{i+1:02d}_0000", age_days=30 - i)
    runs_all = sorted(parent.iterdir())
    keep, archive = select_to_archive(parent, keep_last=10)
    assert len(keep) == 10
    assert len(archive) == 5
    keep_names = {p.name for p in keep}
    newest_10 = {p.name for p in sorted(runs_all, key=lambda p: p.stat().st_mtime)[-10:]}
    assert keep_names == newest_10


def test_select_to_archive_fewer_than_keep_is_noop(tmp_path: Path):
    parent = tmp_path / "engine"
    parent.mkdir()
    for i in range(3):
        _mkrun(parent, f"2026-04-{i+1:02d}_0000", age_days=1)
    keep, archive = select_to_archive(parent, keep_last=10)
    assert len(keep) == 3
    assert len(archive) == 0


def test_archive_and_remove_zips_then_deletes(tmp_path: Path):
    parent = tmp_path / "engine"
    parent.mkdir()
    old = _mkrun(parent, "2026-01-01_0000", age_days=100)
    new = _mkrun(parent, "2026-04-19_0000", age_days=1)
    archive_zip = tmp_path / "archive.zip"
    removed = archive_and_remove(
        to_archive=[old], archive_zip=archive_zip
    )
    assert removed == 1
    assert archive_zip.exists()
    assert not old.exists()
    assert new.exists()
    with zipfile.ZipFile(archive_zip) as zf:
        assert any(old.name in n for n in zf.namelist())
