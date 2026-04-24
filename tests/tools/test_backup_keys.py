from __future__ import annotations

from datetime import datetime

from tools.maintenance.backup_keys import run_backup


def test_run_backup_creates_timestamped_copy(tmp_path):
    keys = tmp_path / "keys.json"
    backup_dir = tmp_path / "backups"
    keys.write_text('{"x":1}', encoding="utf-8")

    code, path, skipped = run_backup(
        keys_path=keys,
        backup_dir=backup_dir,
        keep=5,
        now=datetime(2026, 4, 20, 10, 0, 0),
    )

    assert code == 0
    assert skipped is False
    assert path == backup_dir / "keys.json.2026-04-20_100000.bak"
    assert path.read_text(encoding="utf-8") == '{"x":1}'


def test_run_backup_skips_when_identical_to_latest(tmp_path):
    keys = tmp_path / "keys.json"
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    keys.write_text('{"x":1}', encoding="utf-8")
    latest = backup_dir / "keys.json.2026-04-20_100000.bak"
    latest.write_text('{"x":1}', encoding="utf-8")

    code, path, skipped = run_backup(
        keys_path=keys,
        backup_dir=backup_dir,
        keep=5,
        now=datetime(2026, 4, 20, 10, 1, 0),
    )

    assert code == 0
    assert skipped is True
    assert path == latest
    assert len(list(backup_dir.glob("*.bak"))) == 1


def test_run_backup_rotates_old_backups(tmp_path):
    keys = tmp_path / "keys.json"
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    keys.write_text('{"x":2}', encoding="utf-8")
    for idx in range(3):
        path = backup_dir / f"keys.json.2026-04-20_10000{idx}.bak"
        path.write_text(f"old-{idx}", encoding="utf-8")

    code, path, skipped = run_backup(
        keys_path=keys,
        backup_dir=backup_dir,
        keep=2,
        now=datetime(2026, 4, 20, 10, 2, 0),
    )

    assert code == 0
    assert skipped is False
    assert path is not None and path.exists()
    backups = sorted(backup_dir.glob("*.bak"))
    assert len(backups) == 2


def test_run_backup_reports_missing_keys_file(tmp_path):
    code, path, skipped = run_backup(keys_path=tmp_path / "keys.json", backup_dir=tmp_path / "backups")

    assert code == 1
    assert path is None
    assert skipped is False


def test_run_backup_skip_path_still_applies_retention(tmp_path):
    keys = tmp_path / "keys.json"
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    keys.write_text('{"x":1}', encoding="utf-8")
    latest = backup_dir / "keys.json.2026-04-20_100002.bak"
    latest.write_text('{"x":1}', encoding="utf-8")
    (backup_dir / "keys.json.2026-04-20_100001.bak").write_text("older", encoding="utf-8")
    (backup_dir / "keys.json.2026-04-20_100000.bak").write_text("oldest", encoding="utf-8")

    code, path, skipped = run_backup(
        keys_path=keys,
        backup_dir=backup_dir,
        keep=2,
        now=datetime(2026, 4, 20, 10, 3, 0),
    )

    assert code == 0
    assert skipped is True
    assert path == latest
    backups = sorted(p.name for p in backup_dir.glob("*.bak"))
    assert backups == [
        "keys.json.2026-04-20_100001.bak",
        "keys.json.2026-04-20_100002.bak",
    ]
