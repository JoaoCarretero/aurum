"""AgentTab — full bio de um agent como tab content.

Compoe os 4 builders de agent_detail.py pra renderizar header + linked
work + live runs + persona stats. update() recebe inputs do screen pai
e filtra internamente pro agent.
"""
from __future__ import annotations

import logging
import tkinter as tk
from pathlib import Path
from typing import Any, Callable

from core.ui.ui_palette import BG, DIM
from launcher_support.research_desk.agent_detail import (
    build_agent_header,
    build_linked_work,
    build_live_runs,
    build_persona_stats,
)
from launcher_support.research_desk.agent_stats import shape_stats
from launcher_support.research_desk.agents import AgentIdentity
from launcher_support.research_desk.artifact_linking import (
    chains_for_agent,
    link_artifacts,
)
from launcher_support.research_desk.stats_db import RatiosView


_LOG = logging.getLogger("aurum.research_desk.agent_tab")


def filter_tickets_for_agent(
    issues_raw: list[dict], agent_uuid: str,
) -> list[dict]:
    """Filtra issues cujo assignee e o agent. Tolera 3 grafias de
    campo (assignedAgentId / assigneeAgentId / assigned_agent_id)."""
    out: list[dict] = []
    for i in issues_raw:
        aid = (
            i.get("assignedAgentId")
            or i.get("assigneeAgentId")
            or i.get("assigned_agent_id")
        )
        if aid == agent_uuid:
            out.append(i)
    return out


def filter_runs_for_agent(
    runs_raw: list[dict], agent_uuid: str,
) -> list[dict]:
    """Filtra heartbeat-runs pelo agent. Tolera agent_id / agentId."""
    out: list[dict] = []
    for r in runs_raw:
        aid = r.get("agent_id") or r.get("agentId")
        if aid == agent_uuid:
            out.append(r)
    return out


class AgentTab(tk.Frame):
    """Full bio tab pra um agent especifico."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        agent: AgentIdentity,
        fetch_runs: Callable[[AgentIdentity], list[dict]],
        root_path: Path,
        fetch_ratios: Callable[[AgentIdentity], "RatiosView | None"],
        on_toggle_pause: Callable[[AgentIdentity, bool], None],
        toplevel: tk.Misc,
    ):
        super().__init__(parent, bg=BG)
        self._agent = agent
        self._fetch_runs = fetch_runs
        self._root_path = root_path
        self._fetch_ratios = fetch_ratios
        self._on_toggle_pause = on_toggle_pause
        self._toplevel = toplevel
        self._header_handles = None
        self._linked_handles = None
        self._live_runs_handles = None
        self._stats_handles = None
        self._shown = False
        self._build()

    def _build(self) -> None:
        # Layout vertical: header / separator / linked / separator /
        # runs / separator / stats
        self._header_frame = tk.Frame(self, bg=BG)
        self._header_frame.pack(fill="x", pady=(0, 8))
        tk.Frame(self, bg=DIM, height=1).pack(fill="x")

        self._linked_frame = tk.Frame(self, bg=BG)
        self._linked_frame.pack(fill="x", pady=(8, 8))
        tk.Frame(self, bg=DIM, height=1).pack(fill="x")

        self._runs_frame = tk.Frame(self, bg=BG)
        self._runs_frame.pack(fill="x", pady=(8, 8))
        tk.Frame(self, bg=DIM, height=1).pack(fill="x")

        self._stats_frame = tk.Frame(self, bg=BG)
        self._stats_frame.pack(fill="x", pady=(8, 0))

    def update(
        self, *,
        agents_state: dict,
        issues_raw: list[dict],
        full_scan: list,
    ) -> None:
        """Recebe snapshot do poll, filtra pro agent, re-builda as
        seccoes (exceto runs que tem seu proprio polling por on_show)."""
        try:
            self._apply(agents_state, issues_raw, full_scan)
        except Exception as e:
            _LOG.exception("AgentTab %s update failed: %s", self._agent.key, e)

    def _apply(
        self, agents_state: dict, issues_raw: list[dict], full_scan: list,
    ) -> None:
        agent_dict = agents_state.get(self._agent.uuid) or {}
        my_issues = filter_tickets_for_agent(issues_raw, self._agent.uuid)
        chains = link_artifacts(full_scan)
        my_chains = chains_for_agent(chains, self._agent.key)
        ratios = self._fetch_ratios(self._agent)

        # Artifacts from full_scan for recent work in persona_stats
        artifacts_for_agent = [
            a for a in full_scan
            if getattr(a, "agent_key", "") == self._agent.key
        ]

        # Build StatsView via shape_stats (proper aggregation)
        stats = shape_stats(
            agent=self._agent,
            agent_dict=agent_dict or None,
            issues=my_issues,
            artifacts=artifacts_for_agent,
        )

        # Tear-down + rebuild header/linked/stats. runs is handled by on_show/on_hide.
        for frame in (
            self._header_frame, self._linked_frame, self._stats_frame,
        ):
            for child in frame.winfo_children():
                child.destroy()

        self._header_handles = build_agent_header(
            self._header_frame, agent=self._agent,
            agent_dict=agent_dict, stats=stats,
            on_toggle_pause=self._on_toggle_pause,
        )
        self._linked_handles = build_linked_work(
            self._linked_frame, agent=self._agent,
            chains=my_chains, root_path=self._root_path,
        )
        self._stats_handles = build_persona_stats(
            self._stats_frame, agent=self._agent,
            ratios=ratios, root_path=self._root_path,
            toplevel=self._toplevel,
            artifacts=artifacts_for_agent,
        )

    def on_show(self) -> None:
        """Arranca live_runs polling."""
        if self._shown:
            return
        self._shown = True
        for child in self._runs_frame.winfo_children():
            child.destroy()
        self._live_runs_handles = build_live_runs(
            self._runs_frame, agent=self._agent, client=self._fetch_runs,
        )

    def on_hide(self) -> None:
        """Para live_runs polling."""
        if not self._shown:
            return
        self._shown = False
        if self._live_runs_handles and self._live_runs_handles.stop:
            try:
                self._live_runs_handles.stop()
            except Exception as e:
                _LOG.debug("live_runs stop failed: %s", e)
        self._live_runs_handles = None
