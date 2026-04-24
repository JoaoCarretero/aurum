"""Pure functions pro COST DASHBOARD — spend agg + alert levels + trend.

Nao renderiza nada. Recebe dicts crus + lista StatRow (stats_db), saida
AgentCostView + CostSummary frozen. Testavel sem Tk/DB.

Alert level thresholds (ratio spent/cap):
  GREEN     <60%
  WARN   60-79%
  ALERT  80-89%
  CRIT      >=90%
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from launcher_support.research_desk.agents import AGENTS, AgentIdentity
from launcher_support.research_desk.paperclip_client import (
    agent_budget_cents,
    agent_spent_cents,
    format_usd_from_cents,
)
from launcher_support.research_desk.stats_db import StatRow


LEVEL_GREEN = "ok"
LEVEL_WARN = "warn"
LEVEL_ALERT = "alert"
LEVEL_CRIT = "crit"

# Thresholds — escolhidos pra casar com spec (80% = alert, 90% = crit)
_T_WARN = 0.60
_T_ALERT = 0.80
_T_CRIT = 0.90


@dataclass(frozen=True)
class AgentCostView:
    """Per-agent: snapshot atual + trend 30d."""
    agent_key: str
    spent_cents: int
    cap_cents: int
    pct: float           # clamp [0, 1+] — pode estourar se overrun
    level: str           # ok/warn/alert/crit
    spent_text: str
    cap_text: str
    trend_cents: list[int]  # ate 30 pontos, cronologico ASC


@dataclass(frozen=True)
class CostSummary:
    """Agregado da equipe."""
    total_spent: int
    total_cap: int
    total_pct: float
    total_level: str
    total_spent_text: str
    total_cap_text: str
    by_agent: list[AgentCostView]
    agents_over_alert: list[str]  # keys com level in (alert, crit)


def classify_level(pct: float) -> str:
    """Categoriza pct (0..1+) em semantic label."""
    if pct >= _T_CRIT:
        return LEVEL_CRIT
    if pct >= _T_ALERT:
        return LEVEL_ALERT
    if pct >= _T_WARN:
        return LEVEL_WARN
    return LEVEL_GREEN


def shape_agent_cost(
    agent: AgentIdentity,
    agent_dict: dict | None,
    history: Iterable[StatRow],
) -> AgentCostView:
    """Compacta dados de um agente pra visualizacao.

    history: rows do stats_db (DESC por data). Convertemos pra ASC pro
    trend linear.
    """
    spent = agent_spent_cents(agent_dict) if agent_dict else 0
    cap = agent_budget_cents(agent_dict) if agent_dict else 0
    pct = (spent / cap) if cap > 0 else 0.0

    rows = list(history)
    rows_asc = sorted(rows, key=lambda r: r.date)
    trend = [r.spent_cents for r in rows_asc[-30:]]

    return AgentCostView(
        agent_key=agent.key,
        spent_cents=spent,
        cap_cents=cap,
        pct=pct,
        level=classify_level(pct),
        spent_text=format_usd_from_cents(spent),
        cap_text=format_usd_from_cents(cap) if cap > 0 else "—",
        trend_cents=trend,
    )


def shape_cost_summary(
    agents_raw: list[dict],
    history_by_agent: dict[str, list[StatRow]],
) -> CostSummary:
    """Agrega a equipe. agents_raw vem do /api/companies/:id/agents;
    history_by_agent e indexado por agent.key (stats_db query)."""
    by_uuid = {a.get("id"): a for a in agents_raw if a.get("id")}

    views: list[AgentCostView] = []
    total_spent = 0
    total_cap = 0
    for agent in AGENTS:
        a_dict = by_uuid.get(agent.uuid)
        history = history_by_agent.get(agent.key, [])
        view = shape_agent_cost(agent, a_dict, history)
        views.append(view)
        total_spent += view.spent_cents
        total_cap += view.cap_cents

    total_pct = (total_spent / total_cap) if total_cap > 0 else 0.0
    over_alert = [v.agent_key for v in views
                  if v.level in (LEVEL_ALERT, LEVEL_CRIT)]

    return CostSummary(
        total_spent=total_spent,
        total_cap=total_cap,
        total_pct=total_pct,
        total_level=classify_level(total_pct),
        total_spent_text=format_usd_from_cents(total_spent),
        total_cap_text=format_usd_from_cents(total_cap) if total_cap > 0 else "—",
        by_agent=views,
        agents_over_alert=over_alert,
    )


# ── Trend helpers (Canvas-friendly) ──────────────────────────────


def normalize_trend(values: list[int], n_points: int = 30) -> list[float]:
    """Retorna `n_points` pontos ∈ [0, 1] cronologicos.

    - Pads front com zeros se menos dados que n_points
    - Clampa valores entre 0 e max(values) (divisao segura se max=0)
    """
    vals = list(values)
    if len(vals) > n_points:
        vals = vals[-n_points:]
    # Pad com zeros no inicio pra historico curto aparecer alinhado a direita
    pad = n_points - len(vals)
    vals = [0] * pad + vals

    vmax = max(vals) if vals else 0
    if vmax <= 0:
        return [0.0] * n_points
    return [v / vmax for v in vals]


def format_cap_text(pct: float) -> str:
    """'80%' / '120%' (permite overrun visivel)."""
    return f"{int(round(pct * 100))}%"
