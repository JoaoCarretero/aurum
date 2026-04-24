"""Tests do stats_db — SQLite persistence + pure aggregations."""
from __future__ import annotations

from pathlib import Path

from launcher_support.research_desk.stats_db import (
    StatRow,
    compute_ratios,
    connect,
    list_days,
    record_snapshot,
    today_utc,
    total_spent_last_n_days,
)


def test_today_utc_format() -> None:
    date = today_utc()
    assert len(date) == 10
    assert date[4] == "-" and date[7] == "-"


def test_connect_creates_schema(tmp_path: Path) -> None:
    conn = connect(tmp_path / "stats.db")
    cur = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name='research_desk_stats'"
    )
    assert cur.fetchone() is not None


def test_connect_creates_parent_dir(tmp_path: Path) -> None:
    nested = tmp_path / "research_desk" / "stats.db"
    conn = connect(nested)
    assert nested.exists()
    conn.close()


def test_record_snapshot_inserts(tmp_path: Path) -> None:
    conn = connect(tmp_path / "stats.db")
    record_snapshot(
        conn, agent_key="RESEARCH", date="2026-04-20",
        tickets_done=5, artifacts_total=12, spent_cents=1234,
    )
    rows = list_days(conn, "RESEARCH")
    assert len(rows) == 1
    assert rows[0].tickets_done == 5
    assert rows[0].spent_cents == 1234


def test_record_snapshot_upserts_same_day(tmp_path: Path) -> None:
    conn = connect(tmp_path / "stats.db")
    record_snapshot(
        conn, agent_key="RESEARCH", date="2026-04-20",
        tickets_done=5, artifacts_total=12,
    )
    # Mesmo dia, valores atualizados
    record_snapshot(
        conn, agent_key="RESEARCH", date="2026-04-20",
        tickets_done=7, artifacts_total=15,
    )
    rows = list_days(conn, "RESEARCH")
    assert len(rows) == 1
    assert rows[0].tickets_done == 7
    assert rows[0].artifacts_total == 15


def test_list_days_orders_desc_by_date(tmp_path: Path) -> None:
    conn = connect(tmp_path / "stats.db")
    for date in ("2026-04-18", "2026-04-20", "2026-04-19"):
        record_snapshot(conn, agent_key="RESEARCH", date=date)
    rows = list_days(conn, "RESEARCH")
    assert [r.date for r in rows] == ["2026-04-20", "2026-04-19", "2026-04-18"]


def test_list_days_respects_limit(tmp_path: Path) -> None:
    conn = connect(tmp_path / "stats.db")
    for i in range(20):
        record_snapshot(
            conn, agent_key="RESEARCH",
            date=f"2026-04-{i + 1:02d}",
        )
    rows = list_days(conn, "RESEARCH", days=5)
    assert len(rows) == 5


def test_list_days_filters_by_agent(tmp_path: Path) -> None:
    conn = connect(tmp_path / "stats.db")
    record_snapshot(conn, agent_key="RESEARCH", date="2026-04-20")
    record_snapshot(conn, agent_key="REVIEW", date="2026-04-20")
    scryer_rows = list_days(conn, "RESEARCH")
    arbiter_rows = list_days(conn, "REVIEW")
    assert len(scryer_rows) == 1
    assert scryer_rows[0].agent_key == "RESEARCH"
    assert len(arbiter_rows) == 1
    assert arbiter_rows[0].agent_key == "REVIEW"


# ── Pure compute_ratios ───────────────────────────────────────────


def _row(**kw) -> StatRow:
    defaults = {
        "agent_key": "RESEARCH",
        "date": "2026-04-20",
        "tickets_done": 0,
        "tickets_active": 0,
        "artifacts_total": 0,
        "spent_cents": 0,
        "runs_total": 0,
        "runs_success": 0,
        "runs_error": 0,
    }
    defaults.update(kw)
    return StatRow(**defaults)


def test_compute_ratios_empty() -> None:
    ratios = compute_ratios([])
    assert ratios.total == 0
    assert ratios.ship == 0
    assert ratios.ship_pct == 0.0


def test_compute_ratios_single_row_no_delta() -> None:
    ratios = compute_ratios([_row(tickets_done=5, runs_error=2)])
    # 1 row nao tem delta; ship/iterate zeros, kill somavel
    assert ratios.ship == 0
    assert ratios.iterate == 0
    assert ratios.kill == 2


def test_compute_ratios_delta_across_days() -> None:
    rows = [
        _row(date="2026-04-20", tickets_done=10, artifacts_total=25),
        _row(date="2026-04-10", tickets_done=2, artifacts_total=10),
    ]
    ratios = compute_ratios(rows)
    # ship = 10 - 2 = 8
    assert ratios.ship == 8
    # artifact_delta = 25 - 10 = 15; iterate = 15 - 8 = 7
    assert ratios.iterate == 7
    assert ratios.total == 15  # 8 + 7 + 0


def test_compute_ratios_kill_sums_errors() -> None:
    rows = [
        _row(date="2026-04-20", runs_error=3),
        _row(date="2026-04-19", runs_error=2),
        _row(date="2026-04-18", runs_error=1),
    ]
    ratios = compute_ratios(rows)
    assert ratios.kill == 6


def test_compute_ratios_negative_delta_clamped_to_zero() -> None:
    # Pode acontecer se reset da conta. Clamp pra 0, nao negativo.
    rows = [
        _row(date="2026-04-20", tickets_done=1),
        _row(date="2026-04-10", tickets_done=5),
    ]
    ratios = compute_ratios(rows)
    assert ratios.ship == 0


def test_compute_ratios_pct_sums_to_one_when_non_empty() -> None:
    rows = [
        _row(date="2026-04-20", tickets_done=4, artifacts_total=10),
        _row(date="2026-04-10", tickets_done=0, artifacts_total=0, runs_error=2),
    ]
    ratios = compute_ratios(rows)
    pct_sum = ratios.ship_pct + ratios.iterate_pct + ratios.kill_pct
    assert abs(pct_sum - 1.0) < 1e-9


def test_total_spent_respects_window() -> None:
    rows = [
        _row(date="2026-04-20", spent_cents=100),
        _row(date="2026-04-19", spent_cents=200),
        _row(date="2026-04-18", spent_cents=400),
        _row(date="2026-04-17", spent_cents=800),
    ]
    assert total_spent_last_n_days(rows, 2) == 300   # 100 + 200
    assert total_spent_last_n_days(rows, 4) == 1500  # todos
    assert total_spent_last_n_days(rows, 10) == 1500  # cap na lista
    assert total_spent_last_n_days(rows, 0) == 0
