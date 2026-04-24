"""Tests do cost_summary — pure functions, sem Tk/DB."""
from __future__ import annotations

from launcher_support.research_desk.agents import AGENTS, RESEARCH
from launcher_support.research_desk.cost_summary import (
    LEVEL_ALERT,
    LEVEL_CRIT,
    LEVEL_GREEN,
    LEVEL_WARN,
    classify_level,
    format_cap_text,
    normalize_trend,
    shape_agent_cost,
    shape_cost_summary,
)
from launcher_support.research_desk.stats_db import StatRow


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


# ── classify_level ────────────────────────────────────────────────


def test_level_green_below_60() -> None:
    assert classify_level(0.0) == LEVEL_GREEN
    assert classify_level(0.59) == LEVEL_GREEN


def test_level_warn_60_to_79() -> None:
    assert classify_level(0.60) == LEVEL_WARN
    assert classify_level(0.79) == LEVEL_WARN


def test_level_alert_80_to_89() -> None:
    assert classify_level(0.80) == LEVEL_ALERT
    assert classify_level(0.89) == LEVEL_ALERT


def test_level_crit_90_plus() -> None:
    assert classify_level(0.90) == LEVEL_CRIT
    assert classify_level(1.5) == LEVEL_CRIT  # overrun


# ── shape_agent_cost ──────────────────────────────────────────────


def test_shape_agent_cost_basic() -> None:
    agent_dict = {
        "id": RESEARCH.uuid,
        "monthly_spent_cents": 500,
        "monthly_budget_cents": 1000,
    }
    view = shape_agent_cost(RESEARCH, agent_dict, [])
    assert view.agent_key == "RESEARCH"
    assert view.spent_cents == 500
    assert view.cap_cents == 1000
    assert view.pct == 0.5
    assert view.level == LEVEL_GREEN
    assert view.spent_text == "$5.00"


def test_shape_agent_cost_no_dict() -> None:
    view = shape_agent_cost(RESEARCH, None, [])
    assert view.spent_cents == 0
    assert view.cap_text == "—"
    assert view.level == LEVEL_GREEN


def test_shape_agent_cost_trend_from_history() -> None:
    rows = [
        _row(date="2026-04-18", spent_cents=100),
        _row(date="2026-04-20", spent_cents=300),
        _row(date="2026-04-19", spent_cents=200),
    ]
    view = shape_agent_cost(RESEARCH, None, rows)
    # ASC por data -> 100, 200, 300
    assert view.trend_cents == [100, 200, 300]


def test_shape_agent_cost_alert_level() -> None:
    view = shape_agent_cost(
        RESEARCH,
        {"monthly_spent_cents": 850, "monthly_budget_cents": 1000},
        [],
    )
    assert view.level == LEVEL_ALERT


def test_shape_agent_cost_crit_on_overrun() -> None:
    view = shape_agent_cost(
        RESEARCH,
        {"monthly_spent_cents": 1500, "monthly_budget_cents": 1000},
        [],
    )
    assert view.level == LEVEL_CRIT
    assert view.pct > 1.0


# ── shape_cost_summary ────────────────────────────────────────────


def test_shape_summary_aggregates_team() -> None:
    agents_raw = [
        {"id": a.uuid,
         "monthly_spent_cents": 100,
         "monthly_budget_cents": 500}
        for a in AGENTS
    ]
    summary = shape_cost_summary(agents_raw, {})
    assert summary.total_spent == 100 * len(AGENTS)
    assert summary.total_cap == 500 * len(AGENTS)
    assert summary.total_level == LEVEL_GREEN
    assert len(summary.by_agent) == len(AGENTS)


def test_shape_summary_includes_all_agents_even_if_missing() -> None:
    summary = shape_cost_summary([], {})
    keys = [v.agent_key for v in summary.by_agent]
    for agent in AGENTS:
        assert agent.key in keys


def test_shape_summary_over_alert_list() -> None:
    # Um agente em crit, outros ok
    agents_raw = []
    for i, a in enumerate(AGENTS):
        spent = 950 if i == 0 else 100
        agents_raw.append({
            "id": a.uuid,
            "monthly_spent_cents": spent,
            "monthly_budget_cents": 1000,
        })
    summary = shape_cost_summary(agents_raw, {})
    assert len(summary.agents_over_alert) == 1
    assert summary.agents_over_alert[0] == AGENTS[0].key


# ── normalize_trend ───────────────────────────────────────────────


def test_normalize_trend_pads_with_zeros_front() -> None:
    result = normalize_trend([50, 100], n_points=5)
    assert len(result) == 5
    assert result[:3] == [0.0, 0.0, 0.0]
    # Ultimos 2 pontos sao os reais: 50/100=0.5, 100/100=1.0
    assert result[-2] == 0.5
    assert result[-1] == 1.0


def test_normalize_trend_truncates_excess() -> None:
    values = list(range(50))
    result = normalize_trend(values, n_points=10)
    assert len(result) == 10
    # Os primeiros valores excluidos; ultimos 10 mantidos
    # Ultimo sempre 1.0 (max)
    assert result[-1] == 1.0


def test_normalize_trend_all_zeros() -> None:
    assert normalize_trend([0, 0, 0], n_points=5) == [0.0] * 5


def test_normalize_trend_empty() -> None:
    assert normalize_trend([], n_points=3) == [0.0, 0.0, 0.0]


def test_format_cap_text() -> None:
    assert format_cap_text(0.0) == "0%"
    assert format_cap_text(0.85) == "85%"
    assert format_cap_text(1.2) == "120%"
