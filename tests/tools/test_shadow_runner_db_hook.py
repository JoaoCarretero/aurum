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


def test_per_engine_shadow_runner_persists_signals_to_db() -> None:
    """The standalone per-engine shadow runner (used by citadel/jump/
    renaissance shadows) must mirror millennium_shadow's signal-persistence
    behavior. Without this, live_signals stays empty for those engines —
    only millennium_shadow's slice ends up in the DB."""
    runner_path = (
        Path(__file__).resolve().parents[2]
        / "tools" / "maintenance" / "_shadow_runner.py"
    )
    source = runner_path.read_text(encoding="utf-8")
    assert "_persist_signal_to_db(record)" in source, (
        "_shadow_runner.py must call _persist_signal_to_db after _append_trade"
    )
    assert "upsert_signal(conn, RUN_ID, record)" in source, (
        "_shadow_runner.py must call upsert_signal so per-engine shadows "
        "land in live_signals"
    )
