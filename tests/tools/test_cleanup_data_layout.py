"""Tests for cleanup_data_layout script.

Covers: dry-run default, --apply executes mv, idempotent re-run,
preserves dirs listed in data/index.json, audit/ never moved,
skip warns and preserves src, nexus.db sidecar timestamp consistency.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.maintenance import cleanup_data_layout as cd


@pytest.fixture
def fake_data_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    (tmp_path / "_bridgewater_compare" / "r1").mkdir(parents=True)
    (tmp_path / "anti_overfit" / "run").mkdir(parents=True)
    (tmp_path / "nexus.db").write_text("vazio")
    (tmp_path / "runs" / "citadel_2026-04-18_153116").mkdir(parents=True)
    (tmp_path / "citadel").mkdir()
    (tmp_path / "index.json").write_text(json.dumps([
        {"run_id": "citadel_123", "engine": "citadel"},
    ]))
    monkeypatch.setattr(cd, "DATA_ROOT", tmp_path)
    return tmp_path


def test_dry_run_moves_nothing(fake_data_root: Path) -> None:
    moves = cd.plan_moves()
    assert len(moves) > 0
    cd.run(dry_run=True)
    assert (fake_data_root / "_bridgewater_compare").exists()
    assert (fake_data_root / "nexus.db").exists()
    assert (fake_data_root / "runs" / "citadel_2026-04-18_153116").exists()


def test_apply_moves_research_dirs(fake_data_root: Path) -> None:
    cd.run(dry_run=False)
    assert not (fake_data_root / "_bridgewater_compare").exists()
    arch = fake_data_root / "_archive" / "research" / "_bridgewater_compare"
    assert arch.exists()


def test_apply_archives_nexus_db(fake_data_root: Path) -> None:
    cd.run(dry_run=False)
    assert not (fake_data_root / "nexus.db").exists()
    arch = fake_data_root / "_archive" / "db"
    snaps = list(arch.iterdir())
    assert len(snaps) == 1
    assert snaps[0].name.startswith("nexus.db.")


def test_apply_consolidates_legacy_runs_dir(fake_data_root: Path) -> None:
    cd.run(dry_run=False)
    # Moved to data/citadel/<timestamp-suffix>
    citadel = fake_data_root / "citadel"
    assert citadel.exists()
    moved = [p for p in citadel.iterdir() if p.is_dir()]
    assert any("2026-04-18_153116" in p.name for p in moved)


def test_apply_is_idempotent(fake_data_root: Path) -> None:
    cd.run(dry_run=False)
    cd.run(dry_run=False)  # second call is a no-op


def test_preserves_dirs_in_index_json(fake_data_root: Path) -> None:
    cd.run(dry_run=False)
    # engine dir `citadel` survives
    assert (fake_data_root / "citadel").exists()


def test_audit_dir_is_not_moved(fake_data_root: Path) -> None:
    """CRITICAL: data/audit/ holds live order trail — must NEVER be moved."""
    (fake_data_root / "audit" / "orders-2026-04.jsonl").parent.mkdir(
        parents=True, exist_ok=True
    )
    (fake_data_root / "audit" / "orders-2026-04.jsonl").write_text("{}")
    cd.run(dry_run=False)
    assert (fake_data_root / "audit").exists()
    assert (fake_data_root / "audit" / "orders-2026-04.jsonl").exists()


def test_skip_warns_and_preserves_src(
    fake_data_root: Path, capsys: pytest.CaptureFixture
) -> None:
    """If dst already exists, src must be preserved and user warned."""
    # Pre-create the destination
    (fake_data_root / "_archive" / "research" / "_bridgewater_compare").mkdir(
        parents=True
    )
    cd.run(dry_run=False)
    captured = capsys.readouterr()
    assert "[WARN]" in captured.out
    # Src still present because dst existed
    assert (fake_data_root / "_bridgewater_compare").exists()


def test_nexus_wal_sidecars_moved_with_same_timestamp(
    fake_data_root: Path,
) -> None:
    (fake_data_root / "nexus.db-wal").write_text("wal")
    (fake_data_root / "nexus.db-shm").write_text("shm")
    cd.run(dry_run=False)
    arch = fake_data_root / "_archive" / "db"
    names = sorted(p.name for p in arch.iterdir())
    # Expect 3 files — nexus.db.<stamp>, nexus.db.<stamp>-shm, nexus.db.<stamp>-wal
    assert len(names) == 3
    # All share the same timestamp prefix after "nexus.db."
    prefixes = {n.split("nexus.db.")[1][:17] for n in names}
    assert len(prefixes) == 1, f"timestamps differ: {names}"
