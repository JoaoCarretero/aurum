"""Tests for cleanup_data_layout script.

Covers: dry-run default, --apply executes mv, idempotent re-run,
preserves dirs listed in data/index.json.
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
    (tmp_path / "audit" / "a1").mkdir(parents=True)
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
    (fake_data_root / "audit" / "run_citadel_123").mkdir()
    cd.run(dry_run=False)
    # engine dir `citadel` survives
    assert (fake_data_root / "citadel").exists()
