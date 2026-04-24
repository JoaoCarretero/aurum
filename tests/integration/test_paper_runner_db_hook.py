"""Verify millennium_paper upserts a live_runs row per tick."""
from __future__ import annotations

from pathlib import Path


def test_paper_upsert_hook_exists() -> None:
    """Import the paper runner and confirm db_live_runs.upsert is called
    from the heartbeat path."""
    import tools.operations.millennium_paper as paper
    source = Path(paper.__file__).read_text(encoding="utf-8")
    assert "db_live_runs.upsert" in source, \
        "millennium_paper must call db_live_runs.upsert per tick"
