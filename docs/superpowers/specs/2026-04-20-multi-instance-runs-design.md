# Multi-instance Runs — Design Spec

Data: 2026-04-20
Autor: Claude Opus 4.7 (1M)
Status: DRAFT — aguardando aprovação do Joao

## Problema

Hoje cada par `(engine, mode)` suporta **um único run ativo** por vez.

- `tools/operations/millennium_paper.py` cria `RUN_ID` baseado em
  `datetime.now().strftime("%Y-%m-%d_%H%M")` no import. Granularidade
  de 1 minuto → duas instâncias startadas no mesmo minuto colidem.
- Idem `tools/maintenance/millennium_shadow.py`.
- systemd units `millennium_paper.service` e `millennium_shadow.service`
  são single-slot (não template).
- Sidebar do launcher chama `CockpitClient.latest_run(engine, mode)` →
  retorna SÓ o mais recente.
- Tabela `runs` do banco tem `run_id` PK + `engine` mas não distingue
  instâncias por outro atributo (só pelo timestamp do run_id).

Resultado: operador não consegue rodar 2 configs de MILLENNIUM paper
em paralelo pra comparar edge (ex: Kelly=5 vs Kelly=10), nem monitorar
as duas no launcher.

## Decisão

**Local-first, label-based, DB column `label`.**

Escolhas aprovadas pelo Joao (2026-04-20):
- **Q1 — local ou VPS?** Local primeiro. VPS fica num segundo passo
  (requer systemd template units + deploy).
- **Q2 — como diferenciar instâncias?** Label nominal que o operador
  escolhe ao startar. Exemplos: `kelly5-10k`, `kelly10-25k`,
  `bridgewater-only`.
- **Q3 — schema do DB?** Adicionar coluna `label VARCHAR` na tabela
  `runs`. Sem `config_hash` nem `parent_run_id` por enquanto — se
  virar necessidade, adiciona depois.

## Target Architecture

### RUN_ID

Antes: `2026-04-20_1654`
Depois:
- Sem label: `2026-04-20_165432` (adiciona segundos pra garantir
  uniqueness quando 2 instâncias startam no mesmo minuto)
- Com label: `2026-04-20_165432_kelly5-10k`

Label sanitizado no startup: lowercase, só `[a-z0-9-]`, max 40 chars.
Resto substituído por `-`. Trim de `-` nas pontas.

### Paper runner (tools/operations/millennium_paper.py)

CLI:
```
python -m tools.operations.millennium_paper \
    --label kelly5-10k \
    --account-size 10000 \
    --tick-sec 900
```

Env vars (para systemd):
```
AURUM_PAPER_LABEL=kelly5-10k
AURUM_PAPER_ACCOUNT_SIZE=10000
```

Manifest (data/millennium_paper/<RUN_ID>/state/manifest.json) ganha:
```json
{
  "run_id": "2026-04-20_165432_kelly5-10k",
  "engine": "millennium",
  "mode": "paper",
  "label": "kelly5-10k",
  "started_at": "2026-04-20T16:54:32Z",
  ...
}
```

### Shadow runner

Igual paper: `--label` CLI + `AURUM_SHADOW_LABEL` env + `label` no
manifest.

### Cockpit API

Nenhuma mudança necessária — `Manifest` pydantic model tem
`ConfigDict(extra="allow")`, então o campo `label` passa pro JSON
response automático. Só adicionar o campo no `RunSummary` também pra
listar sem fetch do detail:

```python
class RunSummary(BaseModel):
    run_id: str
    engine: str
    mode: RunMode
    status: RunStatus
    started_at: datetime
    last_tick_at: datetime | None = None
    novel_total: int = 0
    label: str | None = None  # NEW
```

### Launcher — master list

Antes: um row por `(engine, mode)`.
Depois: **um row por run ATIVO**.

- Sidebar mostra: `MILLENNIUM · kelly5-10k · 17t` (engine + label + ticks)
- Se label vazio: fallback `MILLENNIUM · #165432` (timestamp curto)
- Seleção do master passa a usar `run_id` em vez de `slug+bucket`.
- State: `state["selected_run_id"]` em vez de `state["selected_slug"]`

### DB schema

Migration:
```sql
ALTER TABLE runs ADD COLUMN label TEXT DEFAULT NULL;
CREATE INDEX idx_runs_engine_label ON runs(engine, label);
```

Ingestor (`tools/data_center/ingest_runs.py` ou similar): lê
`manifest.label` e popula a coluna.

Views / queries futuras filtram por label:
```sql
SELECT * FROM runs
WHERE engine = 'millennium' AND mode = 'paper'
  AND label = 'kelly5-10k'
ORDER BY started_at DESC;
```

## Faseamento

### Fase 1 — Backend runners aceitam label (local)

1. `millennium_paper.py`: `--label` CLI + `AURUM_PAPER_LABEL` env
2. `millennium_shadow.py`: idem
3. RUN_ID com segundos + label slug
4. Manifest popula campo `label`
5. Testes unit: sanitização do label + RUN_ID com/sem label

**Deliverable:** posso startar 2 paper runs locais em paralelo
(terminais separados), cada um com label diferente, sem colisão de dir.

### Fase 2 — Cockpit API expõe label

1. `RunSummary` ganha `label: str | None`
2. `_summarize_run` lê `manifest.label` ou `heartbeat.label` (fallback)
3. Testes: endpoint `/v1/runs` retorna label

**Deliverable:** `curl /v1/runs` mostra label por run.

### Fase 3 — Launcher sidebar mostra N instâncias

1. `_render_master_list` não deduplica por `(engine, mode)`.
   Mostra um row por run ativo no bucket LIVE.
2. Row label inclui `· <label>` se presente.
3. Seleção por `run_id`.
4. Detail pane renderiza o run selecionado (não o latest_run).

**Deliverable:** launcher mostra N MILLENNIUM paper runs rodando lado a
lado, cada um clicável com detail próprio.

### Fase 4 — DB schema + ingestor

1. Migration `ALTER TABLE runs ADD COLUMN label`.
2. Ingestor popula label do manifest.
3. Tests: nova coluna aparece nas queries.

**Deliverable:** coluna existe + populada pra runs novos. Runs
existentes ficam com label=NULL (OK).

### Fase 5 — UI pra startar instância com label (opcional)

1. Botão "+ NEW INSTANCE" no cockpit.
2. Dialog: engine, mode, label, account_size.
3. Spawn local subprocess ou POST pro cockpit admin endpoint.

### Fase 6 — VPS multi-instance (futuro)

1. systemd template unit: `millennium_paper@<slot>.service`
2. Env por-slot: `/etc/aurum/paper-<slot>.env` com `AURUM_PAPER_LABEL=<slot>`
3. Cockpit API admin endpoint: `/v1/instances/start?engine=millennium&mode=paper&label=<label>&account_size=<n>`
4. Install script: `deploy/install_paper_multi_vps.sh` instala template unit.

## Questions Não Resolvidas

1. **Same label, 2 runs ao mesmo tempo?** Ex: startar 2 pods com
   `--label kelly5`. Permitir (cada um ganha timestamp diferente) ou
   recusar (label é primary-key dentro de engine+mode ativos)?
   **Proposta:** permitir, não é PK. Label é só metadata humana.

2. **Quando 2 instâncias competem por recursos**, como saldo paper
   compartilhado? **Resposta atual:** cada instância tem seu próprio
   PaperAccount em memória e em disco. São independentes.

3. **WSPriceFeed singleton vs per-instance?** Hoje o WS feed é
   singleton global no processo do paper runner. Com 2 instâncias
   em PROCESSOS separados, cada uma sobe seu próprio WS feed — OK,
   não compete. Binance rate-limit de 300 conexões WS permite muitas.

## Riscos

1. Janela de collision ainda existe se 2 instâncias startam no MESMO
   segundo. Mitigação: adicionar UUID curto (4 chars) como fallback.
2. Backward compat: runs antigos não têm `label` — ingestor precisa
   tratar como NULL sem quebrar. OK se coluna aceitar NULL.
3. Systemd template unit não é trivial — usuário precisa saber
   `millennium_paper@kelly5.service` vs `.service`. Mitigação: UI
   esconde isso na fase 5+6.

## Approval

- [ ] Joao aprovou design
- [ ] Pronto pra iniciar Fase 1
