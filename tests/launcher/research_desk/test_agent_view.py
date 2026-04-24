"""Tests da funcao shape_agent — nao requer Tk."""
from __future__ import annotations

import datetime as dt

from launcher_support.research_desk.agent_view import (
    AgentView,
    offline_view,
    shape_agent,
    shape_agents_by_uuid,
)


def test_offline_view_constants() -> None:
    view = offline_view()
    assert view.is_offline is True
    assert view.status_color_key == "offline"
    assert view.budget_pct == 0.0


def test_shape_returns_offline_for_empty_input() -> None:
    assert shape_agent(None).is_offline
    assert shape_agent({}).is_offline


def test_shape_extracts_running_status() -> None:
    view = shape_agent({"status": "running"})
    assert view.status_color_key == "running"
    assert view.status_text == "running"


def test_paused_flag_overrides_status() -> None:
    view = shape_agent({"status": "running", "paused": True})
    assert view.status_color_key == "paused"


def test_unknown_status_string_preserved() -> None:
    view = shape_agent({"status": "spawning"})
    # nome preservado, mas color_key cai no fallback idle
    assert view.status_text == "spawning"
    assert view.status_color_key == "idle"


def test_error_status_gets_error_key() -> None:
    view = shape_agent({"status": "error"})
    assert view.status_color_key == "error"


def test_budget_formats_from_cents() -> None:
    view = shape_agent({
        "status": "idle",
        "monthly_spent_cents": 1234,
        "monthly_budget_cents": 5000,
    })
    assert view.budget_text == "$12.34 / $50.00"
    assert 0.24 < view.budget_pct < 0.25


def test_budget_zero_cap_safe() -> None:
    view = shape_agent({"monthly_spent_cents": 100, "monthly_budget_cents": 0})
    assert view.budget_pct == 0.0


def test_budget_pct_clamped_when_over() -> None:
    view = shape_agent({"monthly_spent_cents": 1500, "monthly_budget_cents": 1000})
    assert view.budget_pct == 1.0


def test_current_issue_title_extracted() -> None:
    view = shape_agent({"status": "running", "current_issue": {"title": "Spec Kepos"}})
    assert view.last_ticket == "Spec Kepos"


def test_last_issue_fallback() -> None:
    view = shape_agent({"last_issue": {"summary": "Review sobre X"}})
    assert view.last_ticket == "Review sobre X"


def test_current_issue_missing() -> None:
    view = shape_agent({"status": "idle"})
    assert view.last_ticket == "—"
    assert view.last_ticket_age == "—"


def test_title_truncated_to_60_chars() -> None:
    long = "x" * 200
    view = shape_agent({"current_issue": {"title": long}})
    assert len(view.last_ticket) == 60


def test_age_fresh_reads_minutes() -> None:
    now = dt.datetime.now(dt.timezone.utc)
    ten_min_ago = (now - dt.timedelta(minutes=10)).isoformat()
    view = shape_agent({"current_issue": {"title": "x", "updated_at": ten_min_ago}})
    assert view.last_ticket_age.endswith("atras")
    assert "min" in view.last_ticket_age


def test_age_invalid_iso() -> None:
    view = shape_agent({"current_issue": {"title": "x", "updated_at": "not-a-date"}})
    assert view.last_ticket_age == "—"


def test_age_handles_zulu_suffix() -> None:
    # ISO com Z (como Paperclip pode devolver)
    iso_z = "2026-04-23T18:00:00Z"
    view = shape_agent({"current_issue": {"title": "x", "updated_at": iso_z}})
    # nao deve explodir, qualquer formato de resposta serve
    assert isinstance(view.last_ticket_age, str)


def test_shape_agents_by_uuid_indexes() -> None:
    agents = [
        {"id": "u1", "status": "running", "monthly_spent_cents": 100, "monthly_budget_cents": 1000},
        {"id": "u2", "status": "paused"},
    ]
    out = shape_agents_by_uuid(agents)
    assert set(out.keys()) == {"u1", "u2"}
    assert out["u1"].status_color_key == "running"
    assert out["u2"].status_color_key == "paused"


def test_shape_agents_by_uuid_skips_missing_id() -> None:
    agents = [{"status": "idle"}]  # sem id
    out = shape_agents_by_uuid(agents)
    assert out == {}


def test_agentview_is_frozen() -> None:
    view = offline_view()
    try:
        view.status_text = "hacked"  # type: ignore[misc]
    except AttributeError:
        return  # esperado (frozen dataclass)
    raise AssertionError("AgentView deveria ser frozen")
