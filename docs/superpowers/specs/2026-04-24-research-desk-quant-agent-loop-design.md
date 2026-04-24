# Research Desk — Fechar o Loop Quant ↔ Agent ↔ Quant

**Data:** 2026-04-24
**Sub-spec:** 3 (Agents no launcher) — primeira de 3 sub-specs da série "Terminal do Launcher como cockpit de fábrica quant"
**Escopo:** extensão in-place de `launcher_support/research_desk/` + screen; 1 módulo novo

---

## 1. Arquitetura

O spec fecha a feedback-loop **quant → agent → quant** na Research Desk reutilizando o que já existe. Não introduz packages, não move código, não toca `paperclip_client` (transport já cobre tudo).

**5 fixes de loop (A1-A5) + 4 de observability (B):**

- **A1** — `IssueDetailModal` (módulo novo)
- **A2** — `run_id` em `TicketDraft`
- **A3** — `STATUS_STALE` em `live_runs`
- **A4** — backtest scan em `artifact_scanner` + `LinkedChain.backtest_run_id` + `origin` tag
- **A5** — persona editor acessível direto do card (CONFIGURE)
- **B** — 4 silenciadores (`except Exception: pass`) viram feedback explícito

**Boundary respected:** `issue_view.py` continua puro (shape/classify, no Tk). Tk modals ficam em módulos sibling (`ticket_form.py`, `agent_detail.py`, novo `issue_detail.py`). `paperclip_client` permanece transport-only. `artifact_scanner` continua puro-filesystem.

**Non-functional requirement (NFR1) — per-agent separation:** cada peça que renderiza ou persiste info de agent mantém o agent atribuído visualmente proeminente (sigil + cor da paleta) e logicamente isolado (chain, stale, origin tag são por-agent). Princípio pra checar em review: "se eu olho isso 2 segundos, consigo dizer de qual agent é?". Reorg da tela em colunas per-agent fica pra sub-spec 4 futura se desejado.

**Caminho do usuário pós-mudança:**
1. Backtest produz `data/<engine>/<run_id>/` — `artifact_scanner` enxerga e tagueia origin=agent/human.
2. User abre Research Desk → clica NOVO TICKET → escolhe `run_id` (autocomplete dos runs recentes) → assignee → submit.
3. Ticket criado com `run_id` no body + label. Pipeline panel mostra em `todo`; agent pega.
4. User clica ticket no pipeline/activity → `IssueDetailModal`: title/body/status/assignee, comments streaming, breadcrumb de lineage.
5. Se agent setou `startedAt` mas nunca escreveu `executionRunId` (AUR-12 failure mode), card pinta STALE em laranja dentro de 15 min.
6. CONFIGURE no card abre editor da `AGENTS.md` do agent (persona) direto.

---

## 2. Components

### Novo: `launcher_support/research_desk/issue_detail.py`

`IssueDetailModal(tk.Toplevel)` — API pública `open_issue_detail(parent, client, issue_id, on_close)`.

Render (top → bottom):
- Header: title + id + status pill + priority badge + assignee sigil (NFR1)
- Lineage breadcrumb (se parseável): `← AUR-7 (BUILD SHIP) → AUR-N (este) → ?`
- Body (description) em `tk.Text` readonly, markdown raw
- Comments list: timestamp · author sigil · body (lista vertical; usa `palette.AGENT_COLORS`)
- Footer: "FECHAR" + indicador offline se `CircuitOpen`

Polling: `self.after(5000, self._poll)` enquanto aberto; `after_cancel` no close.

Tamanho: 180-220 linhas.

### Extensão: `launcher_support/research_desk/ticket_form.py`

- `TicketDraft` ganha `run_id: str | None = None`
- `validate_draft` aceita `run_id` opcional; se presente, `re.match(r"^[a-zA-Z0-9_/-]{3,}$", run_id)`
- `NewTicketModal`: combobox "RUN ID (optional)" acima do description; `values=list_backtest_runs(root)[:30]`
- `draft_to_api_payload`: se run_id presente, prefixa `**run_id:** <id>\n\n` no description; adiciona label `run:<id>` (Paperclip `labels` field se suportado, senão ignorado)

### Extensão: `launcher_support/research_desk/live_runs.py`

- Novo: `STATUS_STALE = "stale"`, `STALE_THRESHOLD_SEC = 900`
- `_classify_status`: se `started_at` presente + `ended_at` vazio + `now - started > STALE_THRESHOLD_SEC` → `STATUS_STALE`
- `RunView.status_icon`: mapping pra STALE (`"⏸"` + cor laranja)

### Extensão: `launcher_support/research_desk/artifact_scanner.py`

- `ArtifactEntry` ganha `engine: str = ""`, `run_id: str = ""`, `origin: str = ""` (`"agent" | "human" | ""`)
- Nova fn `_scan_backtests(root, limit)` — varre `data/*/` por subdirs match `r"\d{4}-\d{2}-\d{2}_\d{4}"`; cada entry: `kind="backtest"`, `agent_key=""`, `engine=<dirname>`, `run_id=<subdir>`, `mtime_epoch=stat.st_mtime`
- `_detect_origin(root, engine, run_id, paperclip_issues) -> str`:
  - Se existe issue em `paperclip_issues` com label `run:<engine>/<run_id>` → `"agent"`
  - Senão, se `.git/logs/HEAD` tem checkout pra `experiment/*` no intervalo de mtime ± 1h → `"agent"`
  - Senão → `"human"`
- `scan_artifacts(root, limit)` concatena resultado de `_scan_backtests`
- Nova fn pública `list_backtest_runs(root, limit=50) -> list[tuple[str, str, float]]` (engine, run_id, mtime)

### Extensão: `launcher_support/research_desk/artifact_linking.py`

- `LinkedChain` ganha `backtest_run_id: str = ""` (default pra compat)
- Função que popula chain (ou caller que monta): lê issue labels/description por padrão `run:<engine>/<run_id>` ou `**run_id:** <id>`, popula slot

### Extensão: `launcher_support/screens/research_desk.py`

- Import: `from launcher_support.research_desk.issue_detail import open_issue_detail`
- `_on_issue_click(issue_id)` (linha ~436): substitui stub → `open_issue_detail(self, self._client, issue_id, on_close=self._refresh_pipeline)`
- `_on_activity_click` issue path (linha ~503): mesmo
- `_stub_action("configure")` (linha 245) substitui → `_on_configure_click(agent)` que resolve path `~/.paperclip/instances/default/companies/<cid>/agents/<uuid>/instructions/AGENTS.md` e abre via `open_markdown_editor(path)` (mesma fn que EDIT PERSONA usa em `agent_detail.py`)
- 4 silenciadores (B) — detalhes em §4

### NÃO tocados

`paperclip_client.py`, `agents.py`, `stats_db.py`, `activity_feed.py`, `pipeline_panel.py` (só consome, não renderiza issue detail), `sigils.py`, `typography.py`, `palette.py`, `markdown_editor.py`, `markdown_viewer.py`.

---

## 3. Data flow

**Path 1 — Backtest aparece no autocomplete:**
```
engine roda → data/<engine>/<YYYY-MM-DD_HHMM>/
  → _scan_backtests(root) (chamado por _apply_artifacts, poll 5s)
  → list_backtest_runs(root) → [(engine, run_id, mtime), ...]
  → NewTicketModal combobox.configure(values=[...])
```

**Path 2 — Criar ticket linkado:**
```
user preenche + escolhe run_id
  → validate_draft(..., run_id="phi/2026-04-23_1403") → TicketDraft
  → draft_to_api_payload(draft) → {title, description: "**run_id:** phi/2026-04-23_1403\n\n<body>",
       priority, assigned_agent_id, labels: ["run:phi/2026-04-23_1403"]}
  → paperclip_client.create_issue(payload)
  → on success: modal fecha + screen._refresh_pipeline()
```

**Path 3 — Clicar issue abre modal:**
```
user clica row no pipeline_panel OU activity_feed
  → _on_issue_click(issue_id)
  → open_issue_detail(self, self._client, issue_id, on_close=self._refresh_pipeline)
  → modal __init__: get_issue(id) + list_comments(id) → render
  → self.after(5000, self._poll) → re-fetch/re-render se status/count mudou
  → user fecha → after_cancel; on_close() refresh pipeline no parent
```

**Path 4 — Stale detection:**
```
Paperclip retorna heartbeat_run started_at=<15min atrás>, ended_at=null
  → live_runs.shape_runs(raw_runs)
  → _classify_status(raw) → now - started > 900s → STATUS_STALE
  → RunView.status_icon = "⏸" laranja
  → agent_card + agent_detail pintam laranja
```

**Circuit breaker interplay:** modal aberto + breaker abre → poll falha silently dentro do client, banner "OFFLINE" aparece, snapshot permanece. Create ticket c/ breaker aberto → `CircuitOpen` → modal mostra "PAPERCLIP OFFLINE" inline, não fecha.

**Consistência polling:** screen polla 5s; modal polla 5s; `after()` é single-threaded no mainloop. Mesmo `PaperclipClient` compartilhado via `self._client`.

---

## 4. Error handling

**Silenciadores B — `except Exception: pass` → feedback explícito:**

| Site | Hoje | Depois |
|---|---|---|
| `_ensure_stats_db` (screen:305) | `except: self._stats_db_conn = None` silent | `except Exception as e: _log + _flash_feedback(ok=False, msg=f"stats_db: {e.__class__.__name__}")` uma vez na primeira falha |
| `_toggle_agent_pause` (screen:384) | `except Exception: pass  # cai no próximo poll` | `except CircuitOpen: flash("paperclip offline")` / `except Exception as e: _log(e) + flash("pause falhou: {code}")` |
| `_apply_artifacts` (screen:626-638) | 2x bare except engolem scan + merge | `except Exception as e: _log + flash("scan falhou")` — panels mantêm snapshot anterior |
| `_poll_state` (screen:571) | Catch-all: offline e erro Python = `online=False` | Split: `except (CircuitOpen, URLError, TimeoutError): online=False` (connectivity) / `except Exception as e: online=False + _log(e, traceback) + flash("poll error: {type}")`. Pill amarelo DEGRADED pra Python err vs RED pra offline |

**Log destino:** `data/.paperclip_cache/research_desk.log` (append-only, stdlib logging, simples).

**Modal novo (A1):**
- Fetch inicial falha: header="erro: <msg>" + retry button; modal não fecha.
- Poll tick `CircuitOpen`: banner "PAPERCLIP OFFLINE", snapshot permanece.
- Poll tick outra exception: banner amarelo "erro no refresh: <type>", conteúdo estático, próximo tick retenta.
- Close durante fetch: `self._closing=True` flag; callback checa antes de render.

**NovoTicket (A2) submit erro:**
- `CircuitOpen`: banner "paperclip offline", modal aberto.
- Outra: banner mensagem, modal aberto, user retenta.

**A3 stale:** fn pura, sem I/O.

**A4 scan:** `_scan_backtests` retorna `[]` em falha (pattern existente). Se `data/` existe mas permissão falha: flash warning uma vez.

---

## 5. Testing

Padrão `tests/launcher/research_desk/` — pytest puro, sem Tk real (modais testados por API pura).

| Item | Teste | Tipo |
|---|---|---|
| A1 IssueDetailModal | `test_issue_detail.py` — poll lifecycle, offline banner, parse de comments, close cancel | integration |
| A2 run_id ticket | estender `test_ticket_form.py` — validate c/ run_id válido/inválido/vazio; payload injeta body + label | unit |
| A3 stale | `test_live_runs.py::test_classify_status_stale` — started>15min sem ended → STALE; started<15min → RUNNING (regressão) | unit |
| A4 backtest scan + origin | `test_artifact_scanner.py::test_scan_backtests` — data/ subdirs válidos/ignorados; origin=agent via label, origin=human sem label | unit |
| A4 LinkedChain.backtest_run_id | estender `test_artifact_linking.py` — chain com run_id populado via label/description | unit |
| A5 configure wiring | `test_research_desk_actions.py` (novo leve) — `_on_configure_click(agent)` resolve path correto, chama editor mockado | unit |
| B silenciadores | sem teste novo — edits defensivos triviais + smoke manual | — |

**Smoke manual pré-commit:**
1. Launcher abre, Research Desk carrega, status online.
2. Criar ticket com run_id autocompletado → aparece no pipeline.
3. Clicar no ticket → modal abre → comments aparecem.
4. Matar Paperclip mid-modal → banner OFFLINE; restart → auto-recover.
5. Simular stale: manualmente inserir heartbeat_run stale → card laranja em <15 min.
6. Clicar CONFIGURE num card → editor persona abre.
7. `data/citadel/<recent>/` aparece nos artifacts com origin tag correto.

---

## 6. Build sequence

Ordem de implementação (cada bullet = commit atômico com TDD):

1. **A3 stale** — puro, isolado. `live_runs._classify_status` + test. (~30 min)
2. **A4.1 scan + origin** — `artifact_scanner._scan_backtests` + `_detect_origin` + `ArtifactEntry` slots + `list_backtest_runs` + test. (~60 min)
3. **A4.2 LinkedChain** — `artifact_linking.LinkedChain.backtest_run_id` + chain populator + test. (~30 min)
4. **A2 run_id ticket** — `TicketDraft.run_id` + `validate_draft` + `NewTicketModal` combobox + `draft_to_api_payload` label injection + test. (~60 min)
5. **A1 IssueDetailModal** — novo módulo completo + test. Wire em `screens/research_desk.py`. (~2h)
6. **A5 configure** — `_on_configure_click` + wire + test. (~20 min)
7. **B silenciadores** — 4 edits + logging setup. Smoke manual. (~30 min)
8. **Smoke manual completo** + commit final.

Total estimado: ~5h. Não é sessão única obrigatoriamente; cada commit é mergeable sozinho (testes verdes).

---

## 7. Out of scope

- **Sub-spec 4 futura** — reorg da Research Desk em colunas per-agent (a tela compactada estilo Paperclip localhost). NFR1 atual só garante per-agent proeminente; não move layout.
- **Issue status transitions** (write) — modal A1 é read-only nesta sub-spec. Transicionar status do ticket = sub-spec futura.
- **HISTORY card** — stub fica. Big item, próxima sub-spec.
- **Orquestração automática do chain** — vive nos `AGENTS.md` de cada Paperclip agent (instruction files), não no launcher. Fora de escopo de qualquer sub-spec do launcher.
- **arb-hub bug** — separado, tem seu próprio tracking.

---

## 8. Dependências externas

- Paperclip local rodando em `127.0.0.1:3100` (já é pré-requisito do launcher).
- `paperclip_client` já expõe tudo: `get_issue`, `list_comments`, `create_issue`, `list_heartbeat_runs` (A3), `list_agents`.
- Nenhuma dep Python nova.
