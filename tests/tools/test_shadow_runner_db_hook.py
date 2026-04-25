"""Verify millennium_shadow upserts a live_runs row per tick."""
from pathlib import Path


def test_shadow_upsert_hook_exists() -> None:
    import tools.maintenance.millennium_shadow as shadow
    source = Path(shadow.__file__).read_text(encoding="utf-8")
    assert "db_live_runs.upsert" in source, \
        "millennium_shadow must call db_live_runs.upsert per tick"


def test_shadow_signal_upsert_hook_exists() -> None:
    import tools.maintenance.millennium_shadow as shadow
    source = Path(shadow.__file__).read_text(encoding="utf-8")
    assert "_persist_signal_to_db(record)" in source
    assert "upsert_signal(conn, RUN_ID, record)" in source
