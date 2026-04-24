"""Tests do live_runs shape layer — pure functions sem Tk."""
from __future__ import annotations

import datetime as dt
import time

from launcher_support.research_desk.live_runs import (
    STATUS_ERROR,
    STATUS_RUNNING,
    STATUS_SUCCESS,
    STATUS_UNKNOWN,
    shape_run,
    shape_runs,
)


def _iso_minus(seconds: int) -> str:
    when = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=seconds)
    return when.isoformat()


def test_shape_run_minimal() -> None:
    view = shape_run({"id": "r1"})
    assert view.id == "r1"
    assert view.status == STATUS_UNKNOWN
    assert view.cost_text == "—"
    assert view.tokens_text == "—"
    assert view.duration_text == "—"


def test_classify_running_when_started_no_end() -> None:
    view = shape_run({
        "id": "r1",
        "started_at": _iso_minus(30),
    })
    assert view.status == STATUS_RUNNING


def test_classify_success_by_exit_code_zero() -> None:
    view = shape_run({
        "id": "r1",
        "started_at": _iso_minus(100),
        "ended_at": _iso_minus(10),
        "exit_code": 0,
    })
    assert view.status == STATUS_SUCCESS


def test_classify_error_by_exit_code_nonzero() -> None:
    view = shape_run({
        "id": "r1",
        "started_at": _iso_minus(100),
        "ended_at": _iso_minus(10),
        "exit_code": 1,
    })
    assert view.status == STATUS_ERROR


def test_classify_explicit_status_wins() -> None:
    # status="error" vence exit_code=0
    view = shape_run({
        "id": "r1",
        "status": "error",
        "exit_code": 0,
    })
    assert view.status == STATUS_ERROR


def test_cost_text_from_cents() -> None:
    view = shape_run({"id": "r1", "cost_cents": 1234})
    assert view.cost_text == "$12.34"


def test_cost_text_from_usd_fallback() -> None:
    view = shape_run({"id": "r1", "cost_usd": 0.05})
    assert view.cost_text == "$0.05"


def test_tokens_text_compact() -> None:
    view = shape_run({
        "id": "r1",
        "tokens_in": 1500,
        "tokens_out": 450,
    })
    assert "1.5k" in view.tokens_text
    assert "450" in view.tokens_text


def test_tokens_text_dash_when_zero() -> None:
    view = shape_run({"id": "r1"})
    assert view.tokens_text == "—"


def test_duration_from_ms() -> None:
    view = shape_run({"id": "r1", "duration_ms": 14500})
    assert "14.5s" == view.duration_text


def test_duration_computed_from_iso() -> None:
    view = shape_run({
        "id": "r1",
        "started_at": _iso_minus(65),
        "ended_at": _iso_minus(5),
    })
    # Diferenca eh 60s -> "1.0min"
    assert "min" in view.duration_text


def test_duration_subsecond() -> None:
    view = shape_run({"id": "r1", "duration_ms": 250})
    assert view.duration_text == "250ms"


def test_duration_hours() -> None:
    # 3600000 ms = 60 min = 1h
    view = shape_run({"id": "r1", "duration_ms": 3_600_000})
    assert "h" in view.duration_text


def test_issue_title_nested() -> None:
    view = shape_run({
        "id": "r1",
        "issue": {"title": "Build feature X"},
    })
    assert view.issue_title == "Build feature X"


def test_issue_title_flat_fallback() -> None:
    view = shape_run({"id": "r1", "issue_title": "Flat title here"})
    assert view.issue_title == "Flat title here"


def test_issue_title_dash_if_missing() -> None:
    view = shape_run({"id": "r1"})
    assert view.issue_title == "—"


def test_issue_title_truncated() -> None:
    long = "x" * 200
    view = shape_run({"id": "r1", "issue_title": long})
    assert len(view.issue_title) == 60


def test_age_text_recent() -> None:
    view = shape_run({"id": "r1", "started_at": _iso_minus(30)})
    assert "s atras" in view.age_text or "min atras" in view.age_text


def test_shape_runs_orders_desc() -> None:
    raw = [
        {"id": "old", "started_at": _iso_minus(3600)},
        {"id": "new", "started_at": _iso_minus(10)},
        {"id": "mid", "started_at": _iso_minus(600)},
    ]
    runs = shape_runs(raw)
    assert [r.id for r in runs] == ["new", "mid", "old"]


def test_shape_runs_respects_limit() -> None:
    raw = [{"id": f"r{i}", "started_at": _iso_minus(i * 10)}
           for i in range(50)]
    runs = shape_runs(raw, limit=5)
    assert len(runs) == 5


def test_shape_runs_empty() -> None:
    assert shape_runs([]) == []


def test_status_icon_for_each_status() -> None:
    running = shape_run({"id": "r", "status": "running"})
    success = shape_run({"id": "r", "status": "success"})
    error = shape_run({"id": "r", "status": "error"})
    # Icons nao sao iguais entre estados distintos
    assert len({running.status_icon,
                success.status_icon,
                error.status_icon}) == 3


def test_classify_stale_when_started_long_ago_no_end() -> None:
    """AUR-12 failure mode: agent setou started mas nunca escreveu ended."""
    from launcher_support.research_desk.live_runs import STATUS_STALE
    view = shape_run({
        "id": "r1",
        "started_at": _iso_minus(1000),  # 16min atrás (>15min)
    })
    assert view.status == STATUS_STALE


def test_classify_running_when_started_recent_no_end() -> None:
    """Regressão: started recente ainda é RUNNING, não STALE."""
    view = shape_run({
        "id": "r1",
        "started_at": _iso_minus(300),  # 5min atrás (<15min)
    })
    assert view.status == STATUS_RUNNING


def test_classify_explicit_running_overrides_stale_heuristic() -> None:
    """status explícito 'running' vence heurística de timeout."""
    view = shape_run({
        "id": "r1",
        "status": "running",
        "started_at": _iso_minus(2000),
    })
    assert view.status == STATUS_RUNNING
