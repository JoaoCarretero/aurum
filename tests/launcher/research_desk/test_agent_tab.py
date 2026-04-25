"""Tests do AgentTab — pure filter fns."""
from __future__ import annotations

from launcher_support.research_desk.agent_tab import (
    filter_tickets_for_agent,
    filter_runs_for_agent,
)


def test_filter_tickets_by_assignee_uuid():
    agent_uuid = "aaaa-bbbb"
    issues = [
        {"id": "1", "assignedAgentId": "aaaa-bbbb", "title": "mine"},
        {"id": "2", "assignedAgentId": "cccc-dddd", "title": "theirs"},
        {"id": "3", "assignedAgentId": None, "title": "orphan"},
    ]
    mine = filter_tickets_for_agent(issues, agent_uuid)
    assert len(mine) == 1
    assert mine[0]["id"] == "1"


def test_filter_tickets_handles_alt_field_name():
    """Paperclip as vezes usa 'assigneeAgentId' ou 'assigned_agent_id'."""
    agent_uuid = "aaaa-bbbb"
    issues = [
        {"id": "1", "assigneeAgentId": "aaaa-bbbb"},
        {"id": "2", "assigned_agent_id": "aaaa-bbbb"},
        {"id": "3", "assignedAgentId": "cccc"},
    ]
    mine = filter_tickets_for_agent(issues, agent_uuid)
    assert {i["id"] for i in mine} == {"1", "2"}


def test_filter_runs_by_agent_uuid():
    agent_uuid = "aaaa-bbbb"
    runs = [
        {"id": "r1", "agent_id": "aaaa-bbbb"},
        {"id": "r2", "agent_id": "other"},
        {"id": "r3", "agentId": "aaaa-bbbb"},  # camelCase alt
    ]
    mine = filter_runs_for_agent(runs, agent_uuid)
    assert {r["id"] for r in mine} == {"r1", "r3"}
