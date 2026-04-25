"""Contract tests for the RESEARCH DESK <-> Paperclip API.

Two layers of contracts:

1. **Live API shape** (skip-if-offline) — validates that the running
   `npx paperclipai run` server (default :3100) returns the response
   shapes the cockpit assumes. Detects API drift between Paperclip
   server versions BEFORE the cockpit starts rendering garbage.

2. **Local invariants** (always run) — pin the static configuration
   in `launcher_support/research_desk/agents.py` so a copy-paste UUID
   collision or a missing HARD_BUDGETS_CENTS entry is caught at CI time.

Live tests skip when the server is offline; CI without Paperclip stays
green. Local tests have no network dependency.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from launcher_support.research_desk.agents import (
    AGENTS,
    BY_KEY,
    BY_UUID,
    COMPANY_ID,
    HARD_BUDGETS_CENTS,
    PAPERCLIP_BASE_URL,
    effective_budget_cents,
)


# ── Skip-if-offline gate ──────────────────────────────────────────


def _server_up() -> bool:
    try:
        with urllib.request.urlopen(
            f"{PAPERCLIP_BASE_URL}/api/health", timeout=1.5,
        ) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


_LIVE = pytest.mark.skipif(
    not _server_up(),
    reason="Paperclip server offline (expected in CI; run locally with `npx paperclipai run`)",
)


def _get_json(path: str) -> object:
    with urllib.request.urlopen(
        f"{PAPERCLIP_BASE_URL}{path}", timeout=3.0,
    ) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ── Live API contracts ───────────────────────────────────────────


@_LIVE
class TestApiHealth:
    """`is_online()` requires `status == 'ok'`. The server MUST emit
    this exact field — drift here breaks the cockpit's online detection
    silently (fallback to False)."""

    def test_health_returns_dict(self):
        data = _get_json("/api/health")
        assert isinstance(data, dict)

    def test_health_has_status_field(self):
        data = _get_json("/api/health")
        assert "status" in data, "missing 'status' field — is_online() will be False"

    def test_health_status_is_ok_when_healthy(self):
        data = _get_json("/api/health")
        assert data["status"] == "ok", (
            f"server reported status={data.get('status')} — "
            "is_online() will treat as offline"
        )

    def test_health_has_version_field(self):
        """Version field used in session log + telemetry."""
        data = _get_json("/api/health")
        assert "version" in data
        assert isinstance(data["version"], str)


@_LIVE
class TestApiAgents:
    """The 5 RESEARCH DESK agents (RESEARCH/REVIEW/BUILD/CURATE/AUDIT)
    must be present in the company config, with the UUIDs declared in
    `agents.py`. Drift here means cards point to the wrong agent."""

    def test_returns_list(self):
        data = _get_json(f"/api/companies/{COMPANY_ID}/agents")
        # Tolerant — server may return list or {agents: [...]}
        if isinstance(data, dict):
            data = data.get("agents", [])
        assert isinstance(data, list)

    def test_returns_exactly_five_agents(self):
        data = _get_json(f"/api/companies/{COMPANY_ID}/agents")
        if isinstance(data, dict):
            data = data.get("agents", [])
        assert len(data) == 5, f"expected 5 agents, got {len(data)}"

    def test_each_agent_has_id_name_status(self):
        data = _get_json(f"/api/companies/{COMPANY_ID}/agents")
        if isinstance(data, dict):
            data = data.get("agents", [])
        for a in data:
            assert "id" in a, f"agent missing id: {a}"
            assert "name" in a, f"agent missing name: {a}"
            assert "status" in a, f"agent missing status: {a}"

    def test_uuids_match_agents_py(self):
        data = _get_json(f"/api/companies/{COMPANY_ID}/agents")
        if isinstance(data, dict):
            data = data.get("agents", [])
        live_uuids = {a["id"] for a in data}
        local_uuids = {a.uuid for a in AGENTS}
        assert live_uuids == local_uuids, (
            f"UUID drift: live={live_uuids - local_uuids} only / "
            f"local={local_uuids - live_uuids} only"
        )

    def test_names_match_agents_py(self):
        data = _get_json(f"/api/companies/{COMPANY_ID}/agents")
        if isinstance(data, dict):
            data = data.get("agents", [])
        live_names = {a["name"] for a in data}
        local_names = {a.key for a in AGENTS}
        assert live_names == local_names, (
            f"name drift: live={live_names} vs local={local_names}"
        )


@_LIVE
class TestApiIssues:
    """Issue list shape — fields the pipeline_panel + activity_feed
    consume. Tolerant of unknown extra fields, strict on required ones."""

    def test_returns_list(self):
        data = _get_json(f"/api/companies/{COMPANY_ID}/issues")
        if isinstance(data, dict):
            data = data.get("issues", [])
        assert isinstance(data, list)

    def test_each_issue_has_id_title_status(self):
        data = _get_json(f"/api/companies/{COMPANY_ID}/issues")
        if isinstance(data, dict):
            data = data.get("issues", [])
        # If server has 0 issues, this passes vacuously — that's intended
        for i in data[:20]:
            assert "id" in i
            assert "title" in i
            assert "status" in i

    def test_status_values_in_known_set(self):
        """Cockpit groups issues by status — must catch new status
        values appearing on server side before they crash the pipeline.
        """
        known = {"backlog", "todo", "in_progress", "review", "done", "closed",
                 "completed", "cancelled", "open"}
        data = _get_json(f"/api/companies/{COMPANY_ID}/issues")
        if isinstance(data, dict):
            data = data.get("issues", [])
        observed = {(i.get("status") or "").lower() for i in data}
        unknown = observed - known
        assert not unknown, (
            f"unknown issue statuses: {unknown} — cockpit may render incorrectly"
        )


# ── Local invariants (no network) ─────────────────────────────────


class TestAgentIdentityInvariants:
    """Defensive pins on agents.py: copy-paste UUID collisions, dropped
    keys, or empty critical fields would silently route Paperclip data
    to wrong agent without these."""

    def test_exactly_five_agents(self):
        assert len(AGENTS) == 5

    def test_uuids_are_unique(self):
        uuids = [a.uuid for a in AGENTS]
        assert len(set(uuids)) == 5, (
            f"UUID collision: duplicate ids in AGENTS = "
            f"{[u for u in uuids if uuids.count(u) > 1]}"
        )

    def test_keys_are_unique(self):
        keys = [a.key for a in AGENTS]
        assert len(set(keys)) == 5

    def test_keys_are_uppercase(self):
        for a in AGENTS:
            assert a.key.isupper(), f"agent key {a.key!r} should be uppercase"

    def test_by_key_is_exhaustive(self):
        assert len(BY_KEY) == 5
        for a in AGENTS:
            assert BY_KEY[a.key] is a

    def test_by_uuid_is_exhaustive(self):
        assert len(BY_UUID) == 5
        for a in AGENTS:
            assert BY_UUID[a.uuid] is a

    def test_canonical_keys_present(self):
        expected = {"RESEARCH", "REVIEW", "BUILD", "CURATE", "AUDIT"}
        actual = {a.key for a in AGENTS}
        assert actual == expected

    def test_artifact_dirs_set_for_scanned_agents(self):
        """RESEARCH/REVIEW/CURATE/AUDIT need artifact_dir; BUILD uses git
        branches so empty is intentional."""
        artifact_required = {"RESEARCH", "REVIEW", "CURATE", "AUDIT"}
        for a in AGENTS:
            if a.key in artifact_required:
                assert a.artifact_dir, (
                    f"{a.key} needs artifact_dir for scanner — empty would "
                    f"silently miss its specs/reviews/audits"
                )


class TestHardBudgets:
    """Hard cap fallback must cover all 5 agents — without coverage,
    `effective_budget_cents` returns 0 when server returns 0 and the
    enforcer can't auto-pause."""

    def test_all_agents_have_hard_budget(self):
        for a in AGENTS:
            assert a.key in HARD_BUDGETS_CENTS, (
                f"{a.key} missing from HARD_BUDGETS_CENTS — auto-pause won't fire"
            )

    def test_all_budgets_positive(self):
        for key, cents in HARD_BUDGETS_CENTS.items():
            assert cents > 0, f"{key} hard budget is {cents} — must be positive"

    def test_budgets_match_spec(self):
        """AGENTS.md §4 spec: $80/$100/$250/$50/$80 in USD."""
        assert HARD_BUDGETS_CENTS["RESEARCH"] == 8000
        assert HARD_BUDGETS_CENTS["REVIEW"] == 10000
        assert HARD_BUDGETS_CENTS["BUILD"] == 25000
        assert HARD_BUDGETS_CENTS["CURATE"] == 5000
        assert HARD_BUDGETS_CENTS["AUDIT"] == 8000


class TestEffectiveBudgetCents:
    """`effective_budget_cents(agent, server_cap)` is the keystone of
    auto-pause: server cap wins if non-zero, hard fallback otherwise."""

    def test_prefers_server_value_when_positive(self):
        agent = BY_KEY["RESEARCH"]
        assert effective_budget_cents(agent, 12000) == 12000

    def test_falls_back_to_hard_when_server_zero(self):
        agent = BY_KEY["RESEARCH"]
        assert effective_budget_cents(agent, 0) == HARD_BUDGETS_CENTS["RESEARCH"]

    def test_returns_zero_for_unknown_key_with_zero_server(self):
        """If a future agent isn't in HARD_BUDGETS_CENTS and server
        returns 0, we get 0 — enforcer treats as 'no cap, can't enforce'.
        """
        from launcher_support.research_desk.agents import AgentIdentity
        unknown = AgentIdentity(
            key="GHOST", uuid="00000000-0000-0000-0000-000000000000",
            role="x", archetype="x", stone="x", tagline="x",
            typeface="x", artifact_dir="",
        )
        assert effective_budget_cents(unknown, 0) == 0

    def test_negative_server_cap_falls_back(self):
        """Defensive: negative is treated like zero (sentinel value)."""
        agent = BY_KEY["BUILD"]
        # server_cap > 0 is the gate; -1 falls through to fallback
        assert effective_budget_cents(agent, -1) == HARD_BUDGETS_CENTS["BUILD"]
