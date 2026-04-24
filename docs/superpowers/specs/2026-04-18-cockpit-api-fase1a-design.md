# Aurum Cockpit API — Fase 1a Design

**Data:** 2026-04-18
**Branch de trabalho:** `feat/phi-engine` (ou nova `feat/cockpit-api`)
**Autor:** Claude (Opus 4.7), discussão com João
**Status:** Aprovado pelo João; aguarda revisão do spec escrito antes de gerar plano.

---

## Contexto

O MILLENNIUM shadow runner foi deployed no VPS (`vmi3200601`, `/srv/aurum.finance`)
em 2026-04-18 ~02:29 UTC. Tick 1 OK, ticks_fail=0, novel_total=625 (snapshot
inicial do backtest 360d).

**Problema:** o launcher TkInter (Windows) já tem um painel `SHADOW LOOP` na
aba MILLENNIUM — scaffolding em `launcher_support/engines_live_view.py`
(commit `f9199cf`, sessão 2200 de 2026-04-17). Esse painel lê
`data/millennium_shadow/<RUN_ID>/state/heartbeat.json` do **disco local** e
mostra "Nenhum shadow run encontrado" porque o shadow real está no VPS.

**Objetivo Fase 1a:** bridge VPS → launcher com arquitetura institucional
que:
1. Torne o shadow visível na UI do launcher hoje (valor imediato)
2. Seja a fundação reusável pra futuros runners (CITADEL paper, JUMP
   shadow, MILLENNIUM live quando chegar a hora) sem código novo no
   cockpit
3. Respeite separação de concerns (runner escreve, API lê, cockpit consome)
4. Read-only por padrão; operações destrutivas têm endpoint + scope
   separados

**Não-objetivo Fase 1a:** simular condições além do que o backtest já
simula (latência real de exchange, rejections, partial fills). O cost model
atual (SLIPPAGE + SPREAD + COMMISSION + FUNDING) já é aplicado pelo scan
via `_collect_operational_trades`. Adicionar realism extra seria Fase 2
e requer aprovação pra tocar em CORE.

---

## Arquitetura — 3 tiers

```
┌─ VPS (vmi3200601) ────────────────────────────────────┐
│                                                       │
│  Runner:   tools/millennium_shadow.py  (existente)    │
│            escreve: data/{engine}/{run_id}/state/*    │
│                                                       │
│  API:      tools/cockpit_api.py        (NOVO)         │
│            FastAPI read-only em localhost:8787        │
│            systemd: aurum_cockpit_api.service         │
│                                                       │
└────┬──────────────────────────────────────────────────┘
     │  SSH tunnel manual:
     │  ssh -N -L 8787:localhost:8787 root@vmi3200601
     │
┌────┴──────────────────────────────────────────────────┐
│  Cockpit (Windows launcher):                          │
│                                                       │
│  Client:   launcher_support/cockpit_client.py (NOVO)  │
│  View:     launcher_support/engines_live_view.py      │
│            (edit 1 linha no _find_latest_shadow_run)  │
│                                                       │
└───────────────────────────────────────────────────────┘
```

**Invariantes:**
- Runner nunca sabe quem lê. Continua escrevendo arquivos no mesmo local.
- API é stateless, read-only. Não mantém estado próprio; deriva de disco.
- Cockpit é dumb client. Não conhece layout de arquivos do VPS.

---

## Data contract

Todo run (shadow / paper / testnet / live / backtest) produz o mesmo
layout canônico:

```
data/{engine}/{run_id}/
├── state/
│   ├── manifest.json        ← NOVO arquivo Fase 1a
│   ├── heartbeat.json       ← existente
│   └── .kill                ← flag (existente)
├── trades.jsonl             ← existente
└── logs/
    └── *.log                ← existente
```

### manifest.json — novo arquivo

Escrito pelo runner no startup. Imutável durante o run.

```json
{
  "run_id": "2026-04-18_0229",
  "engine": "millennium",
  "mode": "shadow",
  "started_at": "2026-04-18T02:29:38.754671+00:00",
  "commit": "3fa328b",
  "branch": "feat/phi-engine",
  "config_hash": "sha256:abc...",
  "host": "vmi3200601",
  "python_version": "3.14.0",
  "process": {
    "pid": 597417,
    "systemd_unit": "millennium_shadow.service"
  }
}
```

**Por quê:** qualquer consumidor consegue responder *"que commit produziu
esses números, com que config?"* sem precisar de logs. É o que um risk
officer pediria primeiro.

**`config_hash`** é SHA-256 dos valores de `config/params.py` materialmente
relevantes (OMEGA_WEIGHTS, SCORE_THRESHOLD, custos, sizing, cooldowns).
Estabiliza entre runs com a mesma config, muda quando algo foi tuned.

### heartbeat.json — sem mudança

Já escrito pelo shadow runner. Contract atual:
```json
{
  "run_id": "...", "status": "running", "started_at": "...",
  "tick_sec": 900, "run_hours": 0.0,
  "ticks_ok": N, "ticks_fail": M,
  "novel_total": K, "last_tick_at": "...", "last_error": null
}
```

### trades.jsonl — sem mudança

Já escrito pelo shadow runner. `pd.read_json(trades.jsonl, lines=True)`
dá um DataFrame. Schema preservado; a única tag adicionada pelo shadow é
`shadow_run_id` e `shadow_observed_at`.

---

## API surface

Base path: `/v1/` (reserva espaço pra breaking changes futuras).

### Endpoints

```
GET  /v1/healthz
     → {"status":"ok","version":"1.0.0","started_at":"..."}
     Sem auth. Usado pra probe de tunnel/serviço.

GET  /v1/runs
     → [{"run_id":"...","engine":"millennium","mode":"shadow",
         "status":"running","started_at":"...","last_tick_at":"..."}]
     Auth: Bearer read_token.
     Lista todos runs encontrados em data/*/*/state/manifest.json.
     Ordenado por started_at DESC.

GET  /v1/runs/{run_id}
     → {"manifest": {...}, "heartbeat": {...}, "summary": {...}}
     Auth: Bearer read_token.
     summary: derivado de trades.jsonl (n_trades, last_trade_at, pnl_cum).

GET  /v1/runs/{run_id}/heartbeat
     → Heartbeat model direto.
     Auth: Bearer read_token.
     Endpoint rápido pra polling 5s (< 1KB).

GET  /v1/runs/{run_id}/trades?limit=50&since=<iso_ts>
     → {"trades": [...], "count": N, "run_id": "..."}
     Auth: Bearer read_token.
     Últimos N trades (default 50, max 500).
     `since` opcional: retorna só trades com timestamp > since.

POST /v1/runs/{run_id}/kill
     → {"status":"kill_flag_dropped","run_id":"..."}
     Auth: Bearer admin_token (scope diferente de read).
     Drop `.kill` flag no state/ do run. Runner sai no próximo tick.
```

### Schemas (pydantic)

```python
class Manifest(BaseModel):
    run_id: str
    engine: str
    mode: Literal["shadow","paper","testnet","live","backtest"]
    started_at: datetime
    commit: str
    branch: str
    config_hash: str
    host: str

class Heartbeat(BaseModel):
    run_id: str
    status: Literal["running","stopped","failed"]
    ticks_ok: int
    ticks_fail: int
    novel_total: int
    last_tick_at: datetime | None
    last_error: str | None
    tick_sec: int

class RunSummary(BaseModel):
    run_id: str
    engine: str
    mode: str
    status: str
    started_at: datetime
    last_tick_at: datetime | None

class TradeRecord(BaseModel):
    # schema existente do engine — permissivo com campos extras
    timestamp: datetime
    symbol: str
    strategy: str
    direction: Literal["LONG","SHORT"]
    entry: float
    exit: float | None
    pnl: float | None
    shadow_observed_at: datetime | None
    model_config = ConfigDict(extra="allow")
```

### Auth

Duas tokens em `config/keys.json` do VPS:
```json
"cockpit_api": {
  "read_token": "<32 bytes random>",
  "admin_token": "<32 bytes random>",
  "bind_host": "127.0.0.1",
  "bind_port": 8787
}
```

- `read_token` → GET tudo
- `admin_token` → GET tudo + POST /kill
- Rotacionável por edit + `systemctl restart aurum_cockpit_api`
- Mismatch → HTTP 401 com corpo JSON `{"error":"unauthorized"}`

Bind em `127.0.0.1` por default (SSH tunnel obrigatório pra acesso
externo). Mudar pra `0.0.0.0` seria decisão explícita pra futuro +
firewall + HTTPS.

---

## Cockpit integration

### launcher_support/cockpit_client.py (NOVO, ~180 linhas)

```python
@dataclass(frozen=True)
class CockpitConfig:
    base_url: str          # "http://localhost:8787"
    read_token: str
    admin_token: str | None
    timeout_sec: float = 5.0
    poll_interval_sec: float = 5.0

class CockpitClient:
    """Typed client com circuit breaker e cache local."""

    def __init__(self, cfg: CockpitConfig, cache_dir: Path): ...

    def healthz(self) -> dict: ...
    def list_runs(self) -> list[RunSummary]: ...
    def get_run(self, run_id: str) -> RunDetail: ...
    def get_heartbeat(self, run_id: str) -> Heartbeat: ...
    def get_trades(self, run_id: str, limit: int = 50) -> list[dict]: ...
    def drop_kill(self, run_id: str) -> bool: ...

    def latest_run(self, engine: str) -> tuple[Path, dict] | None:
        """Retorna (virtual_run_dir, heartbeat) compatível com o shim
        existente em _find_latest_shadow_run. Escreve snapshot local
        em cache_dir pra fallback offline."""
```

**Circuit breaker:**
- 3 falhas consecutivas → "open" por 300s (5min)
- Durante "open", retorna do cache local com tag `stale=True`
- Após 300s, tenta 1 request; sucesso fecha o circuito

**Cache local (`data/.cockpit_cache/`):**
- Último heartbeat/manifest/trades por run_id
- UI mostra badge "LAST SEEN 3min ago" em âmbar quando servindo do cache
- Gitignored (não é dado autoritativo)

**HTTP:** usa `urllib.request` da stdlib (zero deps novas). O projeto já
proíbe `pip install` (memory `project_python_env`).

### launcher_support/engines_live_view.py (EDIT)

Mudança cirúrgica no `_find_latest_shadow_run`:

```python
def _find_latest_shadow_run() -> tuple[Path, dict] | None:
    # Tenta cockpit API primeiro (remoto)
    client = _get_cockpit_client()  # lazy singleton
    if client:
        remote = client.latest_run(engine="millennium")
        if remote:
            return remote
    # Fallback: disco local (dev / shadow rodando na mesma máquina)
    ...existing logic...
```

Nenhuma outra mudança no painel. Status badges, STOP button,
auto-refresh 5s — tudo continua funcionando. STOP chama
`client.drop_kill(run_id)` em vez de escrever arquivo local quando run
é remoto.

### config/keys.json (cockpit side)

Adiciona bloco:
```json
"cockpit_api": {
  "base_url": "http://localhost:8787",
  "read_token": "<cópia do VPS>",
  "admin_token": "<opcional — só se quiser STOP funcionando>"
}
```

Ausente → launcher funciona normal (só mostra "Nenhum shadow run" se
disco local vazio também).

---

## Deploy

### VPS

1. `git pull` no `/srv/aurum.finance`
2. `bash deploy/install_cockpit_api_vps.sh /srv/aurum.finance root`
3. Installer faz:
   - smoke: `python3 tools/cockpit_api.py --help`
   - instala `/etc/systemd/system/aurum_cockpit_api.service`
   - reload + enable + start
   - sleep 3 + status check
   - reporta `curl -H "Authorization: Bearer $TOKEN" localhost:8787/v1/healthz`

### Cockpit (Windows)

1. `git pull` + reinicia launcher
2. Edita `config/keys.json` local com bloco `cockpit_api`
3. Abre terminal SSH separado:
   ```
   ssh -N -L 8787:localhost:8787 root@vmi3200601
   ```
4. Reabre aba MILLENNIUM no launcher → painel mostra run real do VPS

### Rollback

- Remover bloco `cockpit_api` de `config/keys.json` → launcher volta a
  ler só disco local
- `systemctl stop aurum_cockpit_api` no VPS → shadow continua rodando
  normalmente (API é read-only sobre os arquivos do runner)

---

## Segurança

| Vetor | Mitigação |
|---|---|
| API pública exposta | Bind 127.0.0.1 only; acesso via SSH tunnel |
| Token leak | Rotacionável; escopo mínimo (read/admin); arquivo 0600 |
| Runner corruption via API | API é read-only exceto `/kill` que só escreve 1 arquivo vazio |
| Token em keys.json commitado | `.gitignore` já cobre `config/keys.json` |
| SSH tunnel hijack | Usa SSH key auth existente; responsabilidade do SSH |

**Não endereçado nesta fase:**
- HTTPS (não necessário com tunnel; adicionar Caddy seria Fase 2)
- Rate limiting (API é local-bound; baixo risco de abuse)
- mTLS (overkill pro threat model atual)

---

## Extensibilidade

Pra adicionar um novo runner (ex: CITADEL shadow) no futuro:

1. Runner passa a escrever `manifest.json` + heartbeat.json + trades.jsonl
   em `data/citadel/{run_id}/state/` seguindo o mesmo contract
2. **Nenhuma mudança em cockpit_api.py nem cockpit_client.py** — API
   descobre via glob, cliente aceita qualquer `engine` string
3. Se quiser painel dedicado no launcher, é só reusar
   `_render_shadow_panel` parametrizado por slug

Esse é o teste de "organizou direito": adicionar engine = 0 linhas na
API/cockpit, só conformidade com layout canônico.

---

## Out of scope (Fase 1b+)

- **Tabela "últimos 10 sinais"** no painel MILLENNIUM (Fase 1b, +1h)
- **`tools/shadow_audit.py`** — loader de trades.jsonl pra DF com
  stats comparando shadow vs backtest (Fase 1c, +1h)
- **Auto-tunnel** — launcher gerencia `ssh -N -L` em background thread
  com reconnect (Fase 1b, +1h)
- **HTTPS público + Caddy + IP whitelist** (Fase 2)
- **Prometheus `/metrics`** (Fase 2)
- **Role-based auth além de read/admin** (Fase 2+)
- **Mudanças de realism no runner** (latência exchange, rejections,
  partial fills) — Fase 2+; CORE-adjacent, aprovação explícita.

---

## Acceptance criteria

Fase 1a é considerada completa quando:

1. ✅ `tools/cockpit_api.py` responde `/v1/healthz` no VPS após deploy
2. ✅ `curl -H "Authorization: Bearer $READ" localhost:8787/v1/runs`
   retorna o run shadow atual com `engine=millennium`, `mode=shadow`,
   `status=running`
3. ✅ Launcher na máquina Windows, com tunnel ativo, abre aba MILLENNIUM
   e mostra painel `SHADOW LOOP` com:
   - Status RUNNING (badge verde)
   - ticks_ok / ticks_fail / signals / tick_sec coerentes com VPS
   - Auto-refresh 5s reflete novo tick do VPS dentro de 20s
4. ✅ Tunnel caído → painel mostra "LAST SEEN Xmin ago" em âmbar,
   não crasha
5. ✅ STOP SHADOW (com admin_token) cria `.kill` no VPS e runner para
   no próximo tick
6. ✅ `manifest.json` escrito pelo shadow runner no start tem commit
   hash correto
7. ✅ Suite pytest verde (1141+ passed)
8. ✅ Zero mudança em `core/` ou `config/params.py`

---

## Arquivos afetados

**Novos:**
- `tools/cockpit_api.py` (~350 linhas)
- `launcher_support/cockpit_client.py` (~180 linhas)
- `deploy/aurum_cockpit_api.service` (~30 linhas)
- `deploy/install_cockpit_api_vps.sh` (~60 linhas)
- `tests/test_cockpit_api.py` (~150 linhas — endpoints, auth, schemas)
- `tests/test_cockpit_client.py` (~100 linhas — circuit breaker, cache)

**Editados:**
- `tools/millennium_shadow.py` (+30 linhas) — escreve `manifest.json` no
  start; calcula `config_hash` dos params relevantes
- `launcher_support/engines_live_view.py` (+10 linhas) —
  `_find_latest_shadow_run` tenta client primeiro; STOP usa client
  quando run é remoto
- `config/params.py` (0 — intocado)
- `core/*` (0 — intocado)

**Total:** ~870 linhas novas, ~40 linhas editadas, 0 em CORE.

---

## Testes

### Unit tests (locais, sem VPS)

- `test_cockpit_api.py`:
  - healthz sem auth OK
  - list_runs com read_token OK
  - list_runs sem token → 401
  - list_runs com admin_token OK (admin herda read)
  - kill com read_token → 403
  - kill com admin_token OK → `.kill` criado no filesystem de teste
  - schema validation (manifest inválido → 500 com JSON error)

- `test_cockpit_client.py`:
  - circuit breaker: 3 fails → open, 5min depois tenta de novo
  - cache: request OK → grava em cache; API down → lê do cache com
    stale=True
  - urllib timeout handled corretamente

### Integration test (manual, após deploy)

- Sequence script:
  1. Deploy API no VPS
  2. Abre tunnel
  3. Python REPL local: `from launcher_support.cockpit_client import CockpitClient; c = CockpitClient(...); print(c.list_runs())`
  4. Verifica run shadow listado
  5. Verifica heartbeat atualiza entre chamadas
  6. Drop kill, espera 1 tick, verifica status=stopped

### Smoke no launcher

- Abrir launcher com tunnel ativo → painel SHADOW LOOP mostra dados
  remotos
- Fechar tunnel → painel passa pra âmbar em até 30s (poll + timeout)
- Reabrir tunnel → painel volta a verde em até 10s

---

## Riscos & unknowns

| Risco | Mitigação |
|---|---|
| FastAPI não tá no python do VPS | Installer checa `pip list` na Fase 1a — se falhar, instrui `apt install python3-fastapi python3-uvicorn` (Ubuntu 22.04+) ou fallback pra `http.server` puro (pior DX) |
| Tunnel SSH precisa ficar aberto manualmente | Documentar claramente; Fase 1b automatiza |
| Windows launcher sem `urllib` issues de cert | `urllib.request` da stdlib aceita HTTP plain; tunnel já é localhost → sem cert |
| Token leak em chat durante dev | Documentar: sempre gerar tokens NO VPS via `python3 -c 'import secrets; print(secrets.token_hex(32))'` e copiar manualmente |

FastAPI vs http.server: FastAPI é o padrão fund-grade (types, OpenAPI,
pydantic). Se não tiver no VPS, vale 1 `apt install`. Não quero degradar
pra stdlib só pra economizar 1 dep — o custo de código manual em cima do
`http.server` é alto e frágil.

---

## Next step

Após revisão do João: invocar `superpowers:writing-plans` pra quebrar
Fase 1a em tasks executáveis com checkpoints.
