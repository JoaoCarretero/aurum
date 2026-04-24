# Research Desk — Per-Agent Tabs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganizar a Research Desk screen em tab strip de 6 (OVERVIEW + 5 agents), cada aba per-agent com full bio (header/linked work/live runs/persona stats).

**Architecture:** Refactor `agent_detail.py` (extrair 7 `_build_*` methods → 4 fns module-level agrupadas). Novo `tab_strip.py` (custom Tk nav). Novo `agent_tab.py` (compõe os 4 builders). Estende `screens/research_desk.py` (tab strip + frame management + dispatch de poll).

**Tech Stack:** Python 3.11, TkInter, pytest. Stdlib only.

**Spec:** `docs/superpowers/specs/2026-04-24-research-desk-per-agent-tabs-design.md`

---

## File structure

| Arquivo | Ação | Responsabilidade |
|---|---|---|
| `launcher_support/research_desk/agent_detail.py` | REFACTOR | Extrai 7 `_build_*` → 4 fns module-level (`build_agent_header`, `build_linked_work`, `build_live_runs`, `build_persona_stats`). Modal vira wrapper fino. API externa inalterada. |
| `launcher_support/research_desk/tab_strip.py` | CREATE | `TabStrip(tk.Frame)` widget com labels clicáveis, hover, active state. |
| `launcher_support/research_desk/agent_tab.py` | CREATE | `AgentTab(tk.Frame)` compõe os 4 builders + `update()` filtrando inputs pro agent. |
| `launcher_support/screens/research_desk.py` | MODIFY | Adiciona tab strip + `_tab_container` + `_switch_tab` + dispatch poll pra tabs. |
| `tests/launcher/research_desk/test_tab_strip.py` | CREATE | 3 unit tests: click, active, initial. |
| `tests/launcher/research_desk/test_agent_tab.py` | CREATE | 3 unit tests: filter tickets/runs + smoke build. |
| `tests/launcher/research_desk/test_research_desk_tabs.py` | CREATE | Integration: screen monta + troca tab sem crash. |

---

## Task 1: Refactor agent_detail.py — extract builders

**Files:**
- Modify: `launcher_support/research_desk/agent_detail.py`
- Test: `tests/launcher/research_desk/test_agent_stats.py` (já existe — usado como regressão)

Os 7 métodos `_build_*` de `AgentDetailModal` (linhas 224, 303, 353, 384, 453, 516, 596) são extraídos pra module-level fns agrupadas em 4 builders:

- `build_agent_header` = consolidação de `_build_hero` + `_build_statblock` + `_build_actions`
- `build_linked_work` = renomeia `_build_linked_work`
- `build_live_runs` = renomeia `_build_live_runs` + retorna handle com `stop()`
- `build_persona_stats` = consolidação de `_build_ratios` + `_build_recent_work` + preserva `_open_persona_editor` acessível

### - [ ] Step 1: Criar helper dataclass pra handles

Em `agent_detail.py`, logo após os imports:

```python
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class BuilderHandles:
    """Handles retornados pelos builders pra caller reatualizar o bloco
    sem rebuild. Cada widget relevante fica acessível por key."""
    widgets: dict = field(default_factory=dict)
    stop: Callable[[], None] | None = None  # só build_live_runs usa

    def refresh(self, **kwargs) -> None:
        """Callback de update. Override por-builder via closure."""
        pass
```

### - [ ] Step 2: Extrair `build_agent_header` (module-level)

Mover `_build_hero` + `_build_statblock` + `_build_actions` pra uma fn consolidada. Assinatura:

```python
def build_agent_header(
    parent: tk.Frame, *,
    agent: AgentIdentity,
    agent_dict: dict,
    stats: StatsView,
    on_toggle_pause: Callable[[AgentIdentity, bool], None],
) -> BuilderHandles:
    """Monta hero (sigil+nome) + statblock (budget/tokens/custo) +
    actions (pause/resume). Retorna handles pra refresh posterior.
    
    parent: frame pai onde tudo é packed
    agent_dict: dict retornado por shape_agents_by_uuid (status/paused/budget)
    stats: StatsView com counters de runs/tokens
    on_toggle_pause: callback(agent, was_paused) quando user clica pause/resume
    """
    # Preserve o body existente dos 3 métodos — só substitui:
    #   self.agent → agent
    #   self.top → parent
    #   self._on_toggle_pause → on_toggle_pause
    # Usa um Frame interno pra cada subsecção; grava refs em handles.widgets
    ...
```

No `AgentDetailModal.__init__`, substitui as 3 chamadas por:
```python
self._header_handles = build_agent_header(
    self.top, agent=self.agent, agent_dict=self.agent_dict,
    stats=self.stats, on_toggle_pause=self._on_toggle_pause,
)
```

### - [ ] Step 3: Extrair `build_linked_work` (module-level)

Rename `_build_linked_work` (line 224) pra fn module-level:

```python
def build_linked_work(
    parent: tk.Frame, *,
    agent: AgentIdentity,
    chains: list[LinkedChain],
    root_path: Path,
    client: Any,
) -> BuilderHandles:
    """Lista chains filtradas do agent. COPY CMD + OPEN buttons.
    Se chains vazia → label stub '(sem artifacts deste agent)'."""
    # body igual, substituindo self.* por params
    ...
```

### - [ ] Step 4: Extrair `build_live_runs` (module-level)

```python
def build_live_runs(
    parent: tk.Frame, *,
    agent: AgentIdentity,
    client: Any,
    interval_ms: int = 3000,
) -> BuilderHandles:
    """LIVE RUNS panel. Arranca polling interno via parent.after().
    Retorna handles com stop() pra cancelar o polling."""
    # ...implementacao...
    handles = BuilderHandles()
    after_id = [None]
    
    def _tick():
        if not parent.winfo_exists():
            return
        try:
            runs = client.list_heartbeat_runs_cached(agent.uuid, limit=10)
            # renderiza runs no widget guardado em handles.widgets["runs_frame"]
        except Exception:
            # pinta OFFLINE inline
            pass
        after_id[0] = parent.after(interval_ms, _tick)
    
    def _stop():
        if after_id[0] is not None:
            try:
                parent.after_cancel(after_id[0])
            except Exception:
                pass
            after_id[0] = None
    
    handles.stop = _stop
    _tick()  # fetch inicial
    return handles
```

### - [ ] Step 5: Extrair `build_persona_stats` (module-level)

Consolida `_build_ratios` + `_build_recent_work` + expõe persona editor:

```python
def build_persona_stats(
    parent: tk.Frame, *,
    agent: AgentIdentity,
    ratios: "RatiosView | None",
    root_path: Path,
    toplevel: tk.Misc,   # pra modal do editor
) -> BuilderHandles:
    """30d ratios panel + recent work summary + EDIT PERSONA button.
    toplevel = widget pai pro markdown_editor Toplevel (pode ser
    self.top da modal ou o screen root pra tab)."""
    ...
    handles = BuilderHandles()
    # EDIT PERSONA button:
    btn = tk.Label(parent, text="  EDIT PERSONA  ", ...)
    btn.bind(
        "<Button-1>",
        lambda _e: _open_persona_editor(toplevel, agent=agent, root_path=root_path),
    )
    handles.widgets["edit_btn"] = btn
    return handles


def _open_persona_editor(
    toplevel: tk.Misc, *, agent: AgentIdentity, root_path: Path,
) -> None:
    """Abre markdown_editor sobre AGENTS.md do agent. Renomeado de
    AgentDetailModal._open_persona_editor pra standalone."""
    from launcher_support.research_desk.markdown_editor import (
        open_markdown_editor, persona_path,
    )
    target = persona_path(agent.key, root_path)
    open_markdown_editor(
        toplevel, path=target,
        title_hint=f"{agent.key} persona · {target.name}",
    )
```

### - [ ] Step 6: Refatorar AgentDetailModal.__init__ pra chamar os 4 builders

Substituir as chamadas aos `_build_*` antigos por chamadas aos 4 novos builders:

```python
# Dentro de AgentDetailModal.__init__ ou _build_content:
self._header_handles = build_agent_header(
    header_frame, agent=self.agent, agent_dict=self.agent_dict,
    stats=self.stats, on_toggle_pause=self._on_toggle_pause,
)
self._linked_handles = build_linked_work(
    linked_frame, agent=self.agent, chains=self.chains,
    root_path=self.root_path, client=self.client,
)
self._live_runs_handles = build_live_runs(
    runs_frame, agent=self.agent, client=self.client,
)
self._stats_handles = build_persona_stats(
    stats_frame, agent=self.agent, ratios=self.ratios,
    root_path=self.root_path, toplevel=self.top,
)

# Em close() / destroy handler, chama stop do live_runs:
if self._live_runs_handles.stop:
    self._live_runs_handles.stop()
```

Os 7 métodos `_build_*` antigos viram **deletados** depois que as chamadas foram migradas.

### - [ ] Step 7: Rodar suite completa — zero regressão

```bash
cd C:/Users/Joao/projects/aurum.finance
python -m pytest tests/launcher/research_desk/ -v 2>&1 | tail -10
```

Expected: 285+ PASS (conta anterior preservada). Se algum test falha, o refactor quebrou comportamento — investigar + fix.

### - [ ] Step 8: Smoke import

```bash
python -c "
from launcher_support.research_desk.agent_detail import (
    build_agent_header, build_linked_work, build_live_runs,
    build_persona_stats, open_agent_detail,
)
print('ok')
"
```
Expected: `ok`.

### - [ ] Step 9: Commit

```bash
git add launcher_support/research_desk/agent_detail.py
git commit -m "refactor(research-desk): agent_detail builders -> module-level fns

7 _build_* methods viram 4 fns module-level agrupadas:
  build_agent_header (hero + statblock + actions)
  build_linked_work
  build_live_runs (retorna stop() callable)
  build_persona_stats (ratios + recent_work + EDIT PERSONA btn)

AgentDetailModal vira wrapper fino. open_agent_detail API publica
inalterada — quem usa nao sente diferenca. Prerequisito pro sub-spec 4
(per-agent tabs).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: TabStrip widget

**Files:**
- Create: `launcher_support/research_desk/tab_strip.py`
- Create: `tests/launcher/research_desk/test_tab_strip.py`

### - [ ] Step 1: Escrever tests falhando

```python
"""Tests do TabStrip widget."""
from __future__ import annotations
import tkinter as tk

from launcher_support.research_desk.tab_strip import TabStrip


def test_tab_strip_click_fires_callback():
    root = tk.Tk()
    try:
        selected = []
        strip = TabStrip(
            root,
            tabs=[("overview", "OVERVIEW"), ("RESEARCH", "RESEARCH")],
            on_select=lambda k: selected.append(k),
            initial_key="overview",
        )
        # Simula click no label do "RESEARCH"
        label = strip._labels["RESEARCH"]
        label.event_generate("<Button-1>")
        assert selected == ["RESEARCH"]
    finally:
        root.destroy()


def test_tab_strip_set_active_updates_visual_without_firing_callback():
    root = tk.Tk()
    try:
        selected = []
        strip = TabStrip(
            root,
            tabs=[("overview", "OVERVIEW"), ("BUILD", "BUILD")],
            on_select=lambda k: selected.append(k),
            initial_key="overview",
        )
        strip.set_active("BUILD")
        assert selected == []  # Programático não dispara callback
        assert strip._active == "BUILD"
    finally:
        root.destroy()


def test_tab_strip_initial_key_is_active():
    root = tk.Tk()
    try:
        strip = TabStrip(
            root, tabs=[("a", "A"), ("b", "B")],
            on_select=lambda _k: None, initial_key="b",
        )
        assert strip._active == "b"
    finally:
        root.destroy()
```

### - [ ] Step 2: Rodar — deve falhar

```bash
python -m pytest tests/launcher/research_desk/test_tab_strip.py -v
```
Expected: `ModuleNotFoundError`.

### - [ ] Step 3: Criar `tab_strip.py`

```python
"""TabStrip — barra de tabs customizada no estilo do top nav do launcher.

Labels clicáveis com hover AMBER_B, tab ativa fica AMBER + underline.
Não usa ttk pra preservar paleta Bloomberg.
"""
from __future__ import annotations

import tkinter as tk
from typing import Callable

from core.ui.ui_palette import AMBER, AMBER_B, AMBER_D, BG, BG2, DIM, FONT, WHITE


class TabStrip(tk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        *,
        tabs: list[tuple[str, str]],   # [(key, label), ...]
        on_select: Callable[[str], None],
        initial_key: str,
    ):
        super().__init__(parent, bg=BG)
        self._on_select = on_select
        self._tabs = tabs
        self._active = initial_key
        self._labels: dict[str, tk.Label] = {}
        self._build()

    def _build(self) -> None:
        for key, label_text in self._tabs:
            lbl = tk.Label(
                self, text=f"  {label_text}  ",
                font=(FONT, 9, "bold"),
                fg=WHITE, bg=BG2, cursor="hand2",
                padx=4, pady=6,
            )
            lbl.pack(side="left", padx=(0, 2))
            lbl.bind("<Button-1>", lambda _e, k=key: self._on_click(k))
            lbl.bind("<Enter>", lambda _e, k=key: self._on_hover(k, True))
            lbl.bind("<Leave>", lambda _e, k=key: self._on_hover(k, False))
            self._labels[key] = lbl
        self._repaint()
        # Underline amber abaixo do strip
        tk.Frame(self, bg=DIM, height=1).pack(side="bottom", fill="x")

    def _on_click(self, key: str) -> None:
        if key == self._active:
            return
        self._active = key
        self._repaint()
        self._on_select(key)

    def _on_hover(self, key: str, entered: bool) -> None:
        if key == self._active:
            return  # Ativa não hover-muda
        lbl = self._labels[key]
        lbl.configure(fg=AMBER_B if entered else WHITE)

    def _repaint(self) -> None:
        for key, lbl in self._labels.items():
            if key == self._active:
                lbl.configure(fg=AMBER, bg=BG, font=(FONT, 9, "bold"))
            else:
                lbl.configure(fg=WHITE, bg=BG2, font=(FONT, 9, "bold"))

    def set_active(self, key: str) -> None:
        """Muda tab ativa SEM disparar on_select (evita loop na
        integração com screen parent)."""
        if key not in self._labels:
            return
        self._active = key
        self._repaint()
```

### - [ ] Step 4: Rodar tests — verdes

```bash
python -m pytest tests/launcher/research_desk/test_tab_strip.py -v
```
Expected: 3 PASS.

### - [ ] Step 5: Commit

```bash
git add launcher_support/research_desk/tab_strip.py \
        tests/launcher/research_desk/test_tab_strip.py
git commit -m "feat(research-desk): TabStrip widget — nav custom estilo top nav

Labels clicaveis com hover AMBER_B + active AMBER + underline DIM.
Sem ttk. API: TabStrip(parent, tabs, on_select, initial_key);
set_active(key) pra update visual sem disparar callback.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: AgentTab widget

**Files:**
- Create: `launcher_support/research_desk/agent_tab.py`
- Create: `tests/launcher/research_desk/test_agent_tab.py`

### - [ ] Step 1: Escrever tests (pure filter fns)

```python
"""Tests do AgentTab — pure filter fns + smoke build."""
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
    """Paperclip às vezes usa 'assigneeAgentId' ou 'assigned_agent_id'."""
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
```

### - [ ] Step 2: Rodar — falha

```bash
python -m pytest tests/launcher/research_desk/test_agent_tab.py -v
```
Expected: `ModuleNotFoundError`.

### - [ ] Step 3: Criar `agent_tab.py`

```python
"""AgentTab — full bio de um agent como tab content.

Compõe os 4 builders de agent_detail.py pra renderizar header + linked
work + live runs + persona stats. update() recebe inputs do screen pai
e filtra internamente pro agent.
"""
from __future__ import annotations

import logging
import tkinter as tk
from pathlib import Path
from typing import Any, Callable

from core.ui.ui_palette import BG, BG2, DIM, FONT
from launcher_support.research_desk.agent_detail import (
    build_agent_header,
    build_linked_work,
    build_live_runs,
    build_persona_stats,
)
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
    """Filtra issues cujo assignee é o agent. Tolera 3 grafias de
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
        client: Any,
        root_path: Path,
        fetch_ratios: Callable[[AgentIdentity], RatiosView | None],
        on_toggle_pause: Callable[[AgentIdentity, bool], None],
        toplevel: tk.Misc,
    ):
        super().__init__(parent, bg=BG)
        self._agent = agent
        self._client = client
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
        # Layout vertical: header / linked / runs / stats
        header_frame = tk.Frame(self, bg=BG)
        header_frame.pack(fill="x", pady=(0, 8))
        tk.Frame(self, bg=DIM, height=1).pack(fill="x")

        linked_frame = tk.Frame(self, bg=BG)
        linked_frame.pack(fill="x", pady=(8, 8))
        tk.Frame(self, bg=DIM, height=1).pack(fill="x")

        runs_frame = tk.Frame(self, bg=BG)
        runs_frame.pack(fill="x", pady=(8, 8))
        tk.Frame(self, bg=DIM, height=1).pack(fill="x")

        stats_frame = tk.Frame(self, bg=BG)
        stats_frame.pack(fill="x", pady=(8, 0))

        # Builds iniciais vazios; update() re-popula
        self._header_frame = header_frame
        self._linked_frame = linked_frame
        self._runs_frame = runs_frame
        self._stats_frame = stats_frame

    def update(
        self, *,
        agents_state: dict,
        issues_raw: list[dict],
        full_scan: list,
    ) -> None:
        """Recebe snapshot do poll, filtra pro agent, re-builda as
        secções. Versão simples: tear-down + rebuild (pattern ok pra
        poll 5s com ≤20 items)."""
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

        # Tear-down + rebuild (pattern ja usado em outros panels)
        for frame in (
            self._header_frame, self._linked_frame, self._stats_frame,
        ):
            for child in frame.winfo_children():
                child.destroy()

        # Stats derivados de issues + runs se necessário — caller passa None se não tem
        from launcher_support.research_desk.agent_view import StatsView
        stats = StatsView(
            agent_key=self._agent.key,
            active_issues=len(my_issues),
            closed_issues=0,
            tokens_total=0,
            cost_cents_total=0,
        )

        self._header_handles = build_agent_header(
            self._header_frame, agent=self._agent,
            agent_dict=agent_dict, stats=stats,
            on_toggle_pause=self._on_toggle_pause,
        )
        self._linked_handles = build_linked_work(
            self._linked_frame, agent=self._agent,
            chains=my_chains, root_path=self._root_path,
            client=self._client,
        )
        self._stats_handles = build_persona_stats(
            self._stats_frame, agent=self._agent,
            ratios=ratios, root_path=self._root_path,
            toplevel=self._toplevel,
        )

    def on_show(self) -> None:
        """Arranca live_runs polling."""
        if self._shown:
            return
        self._shown = True
        # Tear-down runs_frame por segurança
        for child in self._runs_frame.winfo_children():
            child.destroy()
        self._live_runs_handles = build_live_runs(
            self._runs_frame, agent=self._agent, client=self._client,
        )

    def on_hide(self) -> None:
        """Pára live_runs polling."""
        if not self._shown:
            return
        self._shown = False
        if self._live_runs_handles and self._live_runs_handles.stop:
            try:
                self._live_runs_handles.stop()
            except Exception as e:
                _LOG.debug("live_runs stop failed: %s", e)
        self._live_runs_handles = None
```

### - [ ] Step 4: Rodar filter tests — verdes

```bash
python -m pytest tests/launcher/research_desk/test_agent_tab.py -v
```
Expected: 3 PASS.

### - [ ] Step 5: Commit

```bash
git add launcher_support/research_desk/agent_tab.py \
        tests/launcher/research_desk/test_agent_tab.py
git commit -m "feat(research-desk): AgentTab full-bio widget

Tk Frame que compoe os 4 builders de agent_detail pro agent dado.
update() recebe snapshot do poll + filtra via filter_tickets_for_agent
+ filter_runs_for_agent (pure fns testaveis). on_show/on_hide arrancam/
param o live_runs polling interno (via build_live_runs.stop()).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Wire tabs in screens/research_desk.py

**Files:**
- Modify: `launcher_support/screens/research_desk.py`

### - [ ] Step 1: Adicionar imports novos

No topo do arquivo (com os outros `from launcher_support.research_desk...`):

```python
from launcher_support.research_desk.agent_tab import AgentTab
from launcher_support.research_desk.tab_strip import TabStrip
```

### - [ ] Step 2: Adicionar state na classe

Dentro de `ResearchDeskScreen.__init__` (ou `_init_state` se existir):

```python
self._active_tab: str = "overview"
self._tab_frames: dict[str, tk.Frame] = {}
self._tab_strip: TabStrip | None = None
self._tab_container: tk.Frame | None = None
self._overview_frame: tk.Frame | None = None
```

### - [ ] Step 3: Modificar `_build` — inserir tab strip + container

Localizar onde o content principal é montado (procurar `self._build_header` ou equivalente). Depois do header, inserir:

```bash
grep -n "def _build\|self\\._build_header\|self\\._build_agents_strip" launcher_support/screens/research_desk.py | head
```

Substituir a montagem atual por (pseudocódigo):

```python
# Header (inalterado)
self._build_header(...)

# NOVO: Tab strip
tabs = [("overview", "OVERVIEW")] + [
    (a.key, a.key) for a in AGENTS
]
self._tab_strip = TabStrip(
    self.container, tabs=tabs,
    on_select=self._switch_tab,
    initial_key="overview",
)
self._tab_strip.grid(row=1, column=0, sticky="ew", pady=(8, 0))

# NOVO: Tab container
self._tab_container = tk.Frame(self.container, bg=BG)
self._tab_container.grid(row=2, column=0, sticky="nsew")
self.container.grid_rowconfigure(2, weight=1)
self.container.grid_columnconfigure(0, weight=1)

# OVERVIEW frame = todo o layout atual (cards + pipeline + artifacts + activity)
# embrulhado num frame interno, assignado a self._tab_frames["overview"]
self._overview_frame = tk.Frame(self._tab_container, bg=BG)
self._overview_frame.grid(row=0, column=0, sticky="nsew")
self._build_overview_content(self._overview_frame)
self._tab_frames["overview"] = self._overview_frame
```

**Importante:** o método atual que monta cards/pipeline/artifacts/activity passa a ser renomeado pra `_build_overview_content(self, parent)` e recebe explicitamente o parent frame. Todo `self.container`/`self.main`/etc dentro dele que refere ao root do content passa a usar `parent`.

### - [ ] Step 4: Implementar `_switch_tab`

Adicionar método na classe:

```python
def _switch_tab(self, key: str) -> None:
    """Troca tab ativa. Lazy-builds AgentTab se ainda não existe.
    on_show/on_hide ciclam polling live_runs."""
    if key == self._active_tab:
        return
    # Hide current
    current = self._tab_frames.get(self._active_tab)
    if current is not None and current.winfo_exists():
        current.grid_remove()
        if hasattr(current, "on_hide"):
            try:
                current.on_hide()
            except Exception as e:
                _LOG.exception("tab on_hide failed: %s", e)
    # Show / build target
    if key not in self._tab_frames:
        try:
            self._tab_frames[key] = self._build_agent_tab(key)
        except Exception as e:
            _LOG.exception("build AgentTab %s failed: %s", key, e)
            self._flash_feedback(ok=False, msg=f"tab {key} falhou")
            # Mantém ativa corrente
            if current is not None and current.winfo_exists():
                current.grid()
            return
    target = self._tab_frames[key]
    target.grid(row=0, column=0, sticky="nsew")
    if hasattr(target, "on_show"):
        try:
            target.on_show()
        except Exception as e:
            _LOG.exception("tab on_show failed: %s", e)
    self._active_tab = key
    if self._tab_strip is not None:
        self._tab_strip.set_active(key)


def _build_agent_tab(self, agent_key: str) -> AgentTab:
    """Factory pra AgentTab. Encontra AgentIdentity pelo key."""
    from launcher_support.research_desk.agents import BY_KEY
    agent = BY_KEY[agent_key]
    return AgentTab(
        self._tab_container,
        agent=agent,
        client=self._client,
        root_path=self.root_path,
        fetch_ratios=self._fetch_ratios_for_agent,
        on_toggle_pause=self._toggle_agent_pause,
        toplevel=self.app,
    )


def _fetch_ratios_for_agent(self, agent):
    """Bridge pra AgentTab — chama o mesmo helper que a modal usa.
    Se stats_db indisponível, retorna None."""
    try:
        from launcher_support.research_desk.stats_db import (
            compute_ratios, load_rows_for_agent,
        )
        if self._stats_db_conn is None:
            return None
        rows = load_rows_for_agent(self._stats_db_conn, agent.uuid)
        return compute_ratios(rows)
    except Exception as e:
        _LOG.debug("fetch_ratios for %s failed: %s", agent.key, e)
        return None
```

**Nota:** `load_rows_for_agent` pode ter nome ligeiramente diferente em `stats_db.py`. Grep primeiro:

```bash
grep -n "def load_rows\|def fetch_rows\|def query_rows\|load_agent" launcher_support/research_desk/stats_db.py
```

Adapta nome real conforme o que existir. Se a modal atual usa inline closure pra carregar rows, replica a mesma lógica.

### - [ ] Step 5: AgentCard `on_inspect` passa a trocar tab

Encontrar onde `AgentCard` é construído com callbacks. Procurar:

```bash
grep -n "on_inspect\|open_agent_detail\|AgentCard(" launcher_support/screens/research_desk.py | head
```

Substituir o callback `on_inspect` atual (que chama `open_agent_detail`) por:

```python
on_inspect=lambda a=agent: self._switch_tab(a.key),
```

Manter `open_agent_detail` ainda acessível via nova ação — adicionar um botão/binding "DETAIL" no card que chama `open_agent_detail(self.app, client=self._client, agent=a, ...)`. Se muito trabalho, deferir pra sub-spec futura.

### - [ ] Step 6: Distribuir poll pra tabs ativas em `_apply_poll_result`

Encontrar `_apply_poll_result`:

```bash
grep -n "_apply_poll_result\|_apply_pipeline\|_apply_artifacts" launcher_support/screens/research_desk.py | head
```

Depois de atualizar o overview (`_apply_pipeline`, `_apply_artifacts`, `_apply_agents`), adicionar loop:

```python
# Distribui pros agent tabs construídas
for key, tab in self._tab_frames.items():
    if key == "overview":
        continue
    if not isinstance(tab, AgentTab):
        continue
    try:
        tab.update(
            agents_state=agents_state_dict,
            issues_raw=issues_raw,
            full_scan=full_scan,
        )
    except Exception as e:
        _LOG.exception("tab %s update failed: %s", key, e)
```

Variáveis `agents_state_dict`, `issues_raw`, `full_scan` — adapta pros nomes reais no `_apply_poll_result` (provável: `shape_agents_by_uuid(...)` retorno, `self._last_issues_raw`, e resultado de `scan_artifacts`).

### - [ ] Step 7: Smoke — rodar launcher manual

```bash
python launcher.py
```

Verifica:
- [ ] ◎ AGENTS no top nav → abre Research Desk na tab OVERVIEW
- [ ] TabStrip visível com 6 labels
- [ ] Click num AgentCard → switch pra tab daquele agent
- [ ] Tab per-agent mostra header + linked + live runs + persona stats
- [ ] Voltar pra OVERVIEW pelo tab strip → cards + pipeline visíveis normal
- [ ] Trocar entre 2 agent tabs — live_runs polling arranca/pára

### - [ ] Step 8: Rodar suite — zero regressão

```bash
python -m pytest tests/launcher/research_desk/ -v 2>&1 | tail -5
```
Expected: todas PASS (285 base + 6 novos das tasks 2+3).

### - [ ] Step 9: Commit

```bash
git add launcher_support/screens/research_desk.py
git commit -m "feat(research-desk): wire TabStrip + per-agent tabs (sub-spec 4)

Screen ganha tab strip 6 labels (OVERVIEW + 5 agents) abaixo do header.
OVERVIEW preserva layout existente em _build_overview_content. Click
num AgentCard agora troca pra tab per-agent (full bio) via _switch_tab.
Modal open_agent_detail fica acessivel como drill-in secundario.

_apply_poll_result distribui agents_state/issues_raw/full_scan pras
tabs construidas. AgentTab.on_show/on_hide ciclam live_runs polling
por tab — evita N threads fetchando heartbeat-runs ao mesmo tempo.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Integration smoke test

**Files:**
- Create: `tests/launcher/research_desk/test_research_desk_tabs.py`

### - [ ] Step 1: Test de smoke — construir screen + trocar tabs

```python
"""Integration smoke — screen monta + troca tabs sem crash."""
from __future__ import annotations
import tkinter as tk
from unittest.mock import MagicMock

import pytest


@pytest.mark.skipif(
    not __import__("os").environ.get("AURUM_TEST_GUI", ""),
    reason="Tk integration — só roda quando AURUM_TEST_GUI=1",
)
def test_screen_builds_and_switches_all_tabs():
    """Com Paperclip mockado, screen monta e _switch_tab pra cada key
    não crasha. Test só roda com AURUM_TEST_GUI=1 pra não quebrar CI
    headless sem display."""
    root = tk.Tk()
    try:
        app = MagicMock()
        app.h_stat = tk.Label(root)
        app.h_path = tk.Label(root)

        mock_client = MagicMock()
        mock_client.is_online.return_value = False  # evita network
        mock_client.list_agents_cached.return_value = []
        mock_client.list_issues_cached.return_value = []
        mock_client.list_heartbeat_runs_cached.return_value = []

        from launcher_support.screens.research_desk import ResearchDeskScreen
        from launcher_support.research_desk.agents import AGENTS

        screen = ResearchDeskScreen(parent=root, app=app)
        # Patch client
        screen._client = mock_client
        screen.build()

        assert screen._active_tab == "overview"

        for agent in AGENTS:
            screen._switch_tab(agent.key)
            assert screen._active_tab == agent.key
            assert agent.key in screen._tab_frames

        screen._switch_tab("overview")
        assert screen._active_tab == "overview"
    finally:
        root.destroy()
```

### - [ ] Step 2: Rodar

```bash
AURUM_TEST_GUI=1 python -m pytest tests/launcher/research_desk/test_research_desk_tabs.py -v
```
Expected: 1 PASS (ou SKIP se env var não setada).

Nota: no Windows PowerShell, `$env:AURUM_TEST_GUI=1; python -m pytest ...`.

### - [ ] Step 3: Commit

```bash
git add tests/launcher/research_desk/test_research_desk_tabs.py
git commit -m "test(research-desk): integration smoke pra tab switching

Monta screen com client mockado e percorre _switch_tab(agent.key) pras
5 agent tabs + volta pra overview. Ratcheia via AURUM_TEST_GUI=1 pra
nao quebrar CI headless (Tk exige display).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Push + update PR

### - [ ] Step 1: Push

```bash
cd C:/Users/Joao/projects/aurum.finance
git push 2>&1 | tail -5
```
Expected: push dos 5 commits pra origin/feat/research-desk. PR #3 auto-update.

### - [ ] Step 2: Smoke final

```bash
python launcher.py
```
Checklist completo:
- [ ] Abre na OVERVIEW
- [ ] Tab strip com 6 labels, active amber
- [ ] Click RESEARCH tab → full bio renderiza
- [ ] Click AUDIT tab → live runs arranca novo polling
- [ ] Click overview → voltou; AUDIT live runs parou
- [ ] Matar Paperclip mid-tab → live_runs da tab ativa mostra offline inline
- [ ] Regression: NOVO TICKET continua funcionando
- [ ] Regression: clicar ticket na OVERVIEW pipeline → IssueDetailModal abre (sub-spec 3 preserved)

---

## Resumo

| Task | Item | Tempo estimado |
|---|---|---|
| 1 | Refactor agent_detail builders | 1h |
| 2 | TabStrip widget + 3 tests | 30min |
| 3 | AgentTab widget + 3 tests | 1h |
| 4 | Wire em screens/research_desk.py | 1h |
| 5 | Integration smoke test | 20min |
| 6 | Push + smoke final | 20min |
| **Total** | | **~4h** |

Dependências: Task 1 → Task 3 (AgentTab usa builders extraídos); Task 2 + Task 3 → Task 4 (screen usa ambos); Task 4 → Task 5.

Branch continua `feat/research-desk`; push atualiza PR #3 com mais commits (squash ainda aglomera tudo num commit de release).
