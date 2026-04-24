# Research Desk — Per-Agent Tabs Layout

**Data:** 2026-04-24
**Sub-spec:** 4 (reorganização visual — per-agent tabs estilo top nav)
**Precede:** sub-spec 3 (`docs/superpowers/specs/2026-04-24-research-desk-quant-agent-loop-design.md`) — já merged no feat/research-desk

---

## 1. Arquitetura

Research Desk passa a ter **tab strip de 6 labels** (OVERVIEW + 5 agent keys) abaixo do header, estilo visual do top nav do launcher (Label + hover AMBER_B + active AMBER + underline). Só uma tab visível por vez; outras ficam `grid_remove`adas, não destruídas.

**Reuso-primeiro:** `AgentDetailModal` já tem 95% do conteúdo da aba full-bio (header/linked_work/live_runs/persona_stats). Refatoramos 4 sub-builders pra fns module-level recebendo `parent: tk.Frame`. Modal passa a ser wrapper fino; tab chama os mesmos builders. Zero duplicação.

**Novo módulo** `agent_tab.py`: `AgentTab(tk.Frame)` compõe os 4 builders pro agent dado. Lazy-built (só existe após primeiro click).

**Entry point inalterado:** top nav `◎ AGENTS` continua → `screens.show("research_desk")`. Screen abre na OVERVIEW. Click num AgentCard da OVERVIEW passa a ser `_switch_tab(agent.key)` em vez de `open_modal`. Modal (`open_agent_detail`) continua acessível via tecla `i` ou botão "DETAIL" na tab — escape hatch pra edits em popup.

**Boundary respected:**
- Zero mudança: `paperclip_client`, `agents`, `issue_view`, `live_runs`, `artifact_scanner`, `artifact_linking`, `issue_detail`, `ticket_form`, `stats_db`, panels (`pipeline`, `artifacts`, `activity_feed`, `agent_card`, `agent_view`)
- Refactor interno: `agent_detail.py` (extração pra module-level; API pública preservada)
- Estende: `screens/research_desk.py` (tab strip + frame management + dispatch)
- Novo: `agent_tab.py`, `tab_strip.py`

## 2. Components

### Refactor `launcher_support/research_desk/agent_detail.py`

4 sub-builders viram module-level fns com parent explícito:

```python
def build_agent_header(parent, *, agent, agent_dict, on_toggle_pause) -> dict:
    """Sigil + nome + status pill + budget bar + pause/resume. Retorna handles dict."""

def build_linked_work(parent, *, agent, chains, root_path, client) -> dict:
    """Lista chains filtradas pelo agent; COPY CMD + OPEN buttons."""

def build_live_runs(parent, *, agent, client, interval_ms=3000) -> dict:
    """LIVE RUNS panel com polling heartbeat-runs do agent.
    Retorna handles + stop() fn pra cancelar polling."""

def build_persona_stats(parent, *, agent, stats_conn, root_path, toplevel) -> dict:
    """30d ratios + budget remaining + EDIT PERSONA button."""
```

`AgentDetailModal.__init__` chama as 4 fns em `self.top`. API externa (`open_agent_detail`) inalterada.

### Novo `launcher_support/research_desk/agent_tab.py`

```python
class AgentTab(tk.Frame):
    def __init__(
        self, parent, *,
        agent, client, root_path, fetch_ratios, app,
    ):
        super().__init__(parent, bg=BG)
        self._agent = agent
        self._client = client
        self._root_path = root_path
        self._fetch_ratios = fetch_ratios  # Callable[[AgentIdentity], RatiosView|None]
        self._app = app                     # screen parent — usado pra _flash_feedback / h_stat
        self._handles: dict = {}            # retornos dos 4 builders
        self._live_runs_stop = None
        self._build()
    
    def _build(self) -> None:
        # Layout vertical: header / linked_work / live_runs / persona_stats
        # Cada bloco chama o builder correspondente + grava handles
    
    def update(self, *, agents_state, issues_raw, full_scan) -> None:
        """Filtra inputs pro agent e injeta via handles."""
    
    def on_show(self) -> None:
        """Arranca live_runs polling."""
    
    def on_hide(self) -> None:
        """Pára live_runs polling (stop fn do builder)."""
```

### Novo `launcher_support/research_desk/tab_strip.py`

```python
class TabStrip(tk.Frame):
    def __init__(self, parent, *, tabs, on_select, initial_key):
        # tabs: list[tuple[key, label]]
        # ex: [("overview", "OVERVIEW"), ("RESEARCH", "RESEARCH"), ...]
        # Labels + binds <Button-1>/<Enter>/<Leave>; active fica AMBER + underline
    
    def set_active(self, key: str) -> None:
        """Atualiza visual; não dispara on_select (evita loop)."""
```

### Modificação `launcher_support/screens/research_desk.py`

- Imports novos: `AgentTab`, `TabStrip`
- `_build` monta: header → `TabStrip` → `self._tab_container` (Frame onde tabs empilham)
- Novo state:
  ```python
  self._active_tab: str = "overview"
  self._tab_frames: dict[str, tk.Frame] = {}
  self._overview_frame: tk.Frame | None = None
  ```
- Novo método `_switch_tab(key)`: `grid_remove` atual, constrói target se preciso, `grid()`, chama `on_hide()/on_show()`, atualiza `TabStrip.set_active`
- OVERVIEW frame = todo o layout atual (5 AgentCards + pipeline + artifacts + activity) embrulhado em frame interno
- AgentCards `on_inspect` muda de "open modal" pra `_switch_tab(agent.key)`. Novo botão "DETAIL" no card (pequeno, canto) preserva acesso à modal
- `_apply_poll_result` distribui pra todas as tabs construídas:
  ```python
  self._overview_frame.update_from_poll(...)  # método novo no overview
  for key, tab in self._tab_frames.items():
      if key == "overview": continue
      try:
          tab.update(agents_state=..., issues_raw=..., full_scan=...)
      except Exception as e:
          _LOG.exception("tab %s update failed: %s", key, e)
  ```

### Arquivos **NÃO** tocados

`paperclip_client.py`, `agents.py`, `palette.py`, `sigils.py`, `typography.py`, `issue_view.py`, `live_runs.py`, `artifact_scanner.py`, `artifact_linking.py`, `stats_db.py`, `ticket_form.py`, `issue_detail.py`, `pipeline_panel.py`, `artifacts_panel.py`, `activity_feed.py`, `agent_card.py`, `agent_view.py`, `markdown_editor.py`, `markdown_viewer.py`, `cost_dashboard.py`, `cost_summary.py`, `alignment_panel.py`, `alignment_scan.py`.

## 3. Data flow

**Path 1 — Entry via top nav:** `◎ AGENTS` → `screens.show("research_desk")` → `on_enter` → `_switch_tab("overview")` → overview frame visible.

**Path 2 — Drill-in:** click AgentCard → `_switch_tab(agent.key)`. Lazy-builds `AgentTab` se ainda não existe. `on_show()` arranca live_runs polling.

**Path 3 — Poll distribution:** `_poll_state` thread → `container.after(0, _apply_poll_result)` → distribui `agents_state/issues_raw/full_scan` pra overview frame + todas as tabs instanciadas. Cada tab filtra internamente.

**Path 4 — AgentTab filtering (dentro de `update`):**
```python
agent_dict = agents_state.get(self._agent.uuid, {})
my_issues = [i for i in issues_raw if i.get("assignedAgentId") == self._agent.uuid]
my_chains = chains_for_agent(link_artifacts(full_scan), self._agent.key)
ratios = self._fetch_ratios(self._agent)  # mesmo callable-injecao que AgentDetailModal ja usa
# injeta via handles retornados pelos builders
```

**Path 5 — Live runs polling per-tab:** `on_show` arranca `after(3000, _tick)` separado do poll principal (heartbeat-runs é per-agent e só interessa pra tab visível). `on_hide` → `after_cancel`.

**Path 6 — Persistência de tab:** OUT OF SCOPE. `_active_tab` reseta pra "overview" cada vez que screen é mostrada. Sub-spec futura se quiserem lembrar.

## 4. Error handling

- **Tab init fail:** `_switch_tab` envolve construção em try/except; falha loga + `_flash_feedback("tab falhou")` + mantém tab atual.
- **Filtros vazios:** labels stub `"(sem tickets atribuídos)"` / `"(sem artifacts)"` / `"(sem live runs)"` — pattern já usado nos panels.
- **Live runs `CircuitOpen`:** catch inline dentro do `_tick`; renderiza "OFFLINE" na secção live runs daquela tab; retenta próximo tick.
- **`.update()` exception numa tab:** `_apply_poll_result` envolve cada call em try/except + `_LOG.exception`; outras tabs seguem.
- **Widget destruído durante switch:** `_switch_tab` checa `frame.winfo_exists()` antes de `grid_remove/grid`.

## 5. Testing

| Item | Teste | Tipo |
|---|---|---|
| TabStrip click dispara on_select | `test_tab_strip.py::test_click_fires_callback` | unit Tk mínimo |
| Active tab destacado visualmente | `test_tab_strip.py::test_active_highlighted` | unit |
| AgentTab filter tickets por assignee | `test_agent_tab.py::test_filter_tickets_by_assignee` | unit (pure fn extraída) |
| AgentTab filter live_runs por agent_uuid | `test_agent_tab.py::test_filter_runs_by_agent` | unit |
| agent_detail refactor preserva comportamento | suite existente (`test_agent_stats`, `test_artifact_linking`, `test_live_runs`) | regressão |
| Smoke: screen constrói 6 frames + troca sem crash | `test_research_desk_tab_smoke.py` | integração leve |

~150 linhas de tests estimadas.

## 6. Build sequence

1. **Refactor `agent_detail.py`** — extrai 4 sub-builders. Testes existentes devem passar sem mudança. (~1h)
2. **Novo `tab_strip.py`** + tests. (~30min)
3. **Novo `agent_tab.py`** + tests. Usa builders extraídos no passo 1. (~1h)
4. **Wire em `screens/research_desk.py`** — tab strip + frame management + dispatch de poll. (~1h)
5. **Smoke E2E** — roda launcher, click todos os tabs, roda suite completa. (~30min)

Total ~4h.

## 7. Out of scope

- Persistência de tab ativa entre sessões
- Drag-to-reorder tabs
- Tab "fechar" (ícone X) — todas as 6 tabs sempre existem
- Hot keys pra tabs (ex: `1-6` pulam direto) — nice-to-have futuro
- Activity feed filtrada per-agent dentro da tab (fica só em OVERVIEW)
- Cost dashboard per-agent na tab (já existe a modal global)

## 8. Dependências externas

- Paperclip local em 127.0.0.1:3100 (pré-requisito do launcher)
- Zero dep Python nova
- Depende da sub-spec 3 já mergeada (IssueDetailModal, builders de agent_detail pós-Task 1 já terem o formato atual)
