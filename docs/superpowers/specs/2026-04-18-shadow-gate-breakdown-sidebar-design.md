# Shadow Gate Breakdown + Sidebar Institucional — Fase 2a+2b Design

**Data:** 2026-04-18
**Branch de trabalho:** `feat/phi-engine` (ou nova `feat/shadow-gate-sidebar`)
**Autor:** Claude (Opus 4.7), discussão com João
**Status:** Aprovado pelo João; aguarda revisão do spec escrito antes de gerar plano.
**Pré-requisitos:** Fase 1a (cockpit API read-only) e Fase 1b (auto-tunnel + last signals) já entregues nas sessões 2026-04-18_0940 e 2026-04-18_1044.

---

## Contexto

O MILLENNIUM shadow roda no VPS (`vmi3200601`) desde 2026-04-18 02:29 UTC.
O launcher Windows lê heartbeat + últimos 10 trades via SSH tunnel →
cockpit API FastAPI → disco. Painel SHADOW mostra ticks_ok, novel_total,
uptime, e tabela com `timestamp/symbol/direction/entry` dos trades.

**Problema identificado pelo João (sessão 2026-04-18 cockpit funcional):**

1. **"Mais dados se entra trade"** — a tabela mostra sinais detectados
   mas não deixa claro se o sinal **teria sido executado** (passou todos
   os gates de filtro + portfolio + sizing) ou foi **filtrado** (e por
   qual gate). Shadow não executa — mas precisa discriminar "decisão
   positiva de entrar" vs "sinal cru detectado". Sem isso, `novel_total=625`
   é uma contagem de ruído misturado com sinal executável.

2. **"Deixar mais simples com múltiplas engines"** — hoje só MILLENNIUM
   tem shadow runner. Quando CITADEL/JUMP ganharem runners, o painel
   atual (single engine full-width) não escala. O slug list
   `_shadow_active_slugs` já é dinâmico (commit `9c1b877`), mas a
   estrutura visual assume 1 engine.

3. **Estética institucional** — alinhamento com aesthetic AURUM
   (Bloomberg-terminal TkInter). Dense, monospace, pouca chrome, layout
   master-detail.

**Objetivo Fase 2a+2b:** resolver 1+2+3 num único ciclo spec→plan→code,
estabelecendo a fundação de dados + layout pro resto do roadmap VPS
(Fases 3a-3d).

**Não-objetivo:**
- Editor de VPS settings (Fase 3a)
- Start/stop remoto de runners (Fase 3b)
- Editor de asset basket (Fase 3c)
- Multi-engine orchestrator (Fase 3d)
- Migrar gates pra `core/gates.py` genérico (deferido pra Fase 3
  quando CITADEL/JUMP precisarem — YAGNI agora)
- Alterar `core/indicators.py`, `core/signals.py`, `core/portfolio.py`,
  `config/params.py` (PROTEGIDOS — ver CLAUDE.md)

---

## Arquitetura

```
┌─ VPS (vmi3200601) ────────────────────────────────────────┐
│                                                            │
│  tools/millennium_shadow.py          (MODIFICADO)          │
│    └─ loop: detect → build_trade_record_with_gates()       │
│                                                            │
│          Reaproveita:                                      │
│            core/signals.py  (decide_direction, filtros)    │
│            core/portfolio.py (portfolio_allows, size)      │
│                                                            │
│          Emite TradeRecord com:                            │
│            - would_enter: bool                             │
│            - gate_breakdown: list[GateOutcome]             │
│            - filter_reason: str | None                     │
│                                                            │
│    └─ atomic_append → state/trades.jsonl                   │
│                                                            │
│  tools/cockpit_api.py                (INALTERADO)          │
│    └─ /trades → pydantic extra='allow' passa novos campos  │
│                                                            │
└─────────────┬──────────────────────────────────────────────┘
              │ SSH tunnel gerenciado pelo launcher
              │ localhost:8787
┌─────────────┴──────────────────────────────────────────────┐
│  Launcher (Windows)                                         │
│                                                             │
│  core/shadow_contract.py             (EXTENDIDO)            │
│    └─ GateOutcome (NOVO modelo)                             │
│    └─ TradeRecord (campos opcionais novos)                  │
│                                                             │
│  launcher_support/shadow_poller.py   (INALTERADO)           │
│    └─ cachea /trades via cockpit_client                     │
│                                                             │
│  launcher_support/engines_sidebar.py (NOVO)                 │
│    └─ render_sidebar(parent, engines, selected) → list fixa │
│    └─ render_detail(parent, run_info) → painel flex         │
│       ├─ health_section(hb)                                 │
│       ├─ run_info_section(manifest)                         │
│       ├─ signals_table(trades) ← coluna status renderiza    │
│       │                           would_enter / filter_reason│
│       └─ actions_row()                                      │
│                                                             │
│  launcher_support/engines_live_view.py (REFATORADO)         │
│    └─ _render_detail_shadow delega pra engines_sidebar      │
│    └─ Mesmo sidebar aplicado aos modos paper/demo/testnet/  │
│       live (source muda: _PROCS_CACHE em vez de shadow      │
│       poller, mas componente é o mesmo)                     │
└─────────────────────────────────────────────────────────────┘
```

**Decisões chave:**

- **Gates ficam em `millennium_shadow.py` por ora.** Não migra pra
  `core/gates.py` porque (a) só 1 engine precisa agora, (b) abstração
  prematura viola YAGNI, (c) `core/` é protegido — adicionar arquivo
  novo exige reconciliação com política do CLAUDE.md.
- **`GateOutcome` é `list`, não `dict`.** Ordem importa pra debug
  ("qual gate barrou primeiro"). Dict perde ordem cross-platform.
- **`would_enter` é `bool | None`.** `None` = trade record legacy sem
  breakdown; UI renderiza `—`. Retrocompatibilidade obrigatória.
- **Sidebar é componente reutilizável.** Fase 2b aplica o MESMO sidebar
  ao modo SHADOW e aos modos paper/demo/testnet/live. Source data
  diferente, component layer idêntico.

---

## Contrato de dados — `core/shadow_contract.py`

### Modelo novo: `GateOutcome`

```python
class GateOutcome(BaseModel):
    """Resultado atômico de um gate.

    Gates são avaliados em ordem determinística pelo runner. A lista de
    GateOutcome em TradeRecord.gate_breakdown preserva essa ordem, o
    que permite ao client identificar "qual foi o primeiro filtro a
    barrar" sem scan completo.
    """
    name: str                  # ex: "regime", "chop", "correlation", "max_positions", "size_ok"
    passed: bool
    reason: str | None = None  # null quando passed=True; texto curto (<80 chars) quando False
    value: float | None = None # valor numérico medido, opcional (ex: correlation=0.83, size=0.0)
```

### Modelo estendido: `TradeRecord`

```python
class TradeRecord(BaseModel):
    # Campos existentes (inalterados — retrocompat total)
    timestamp: datetime
    symbol: str
    strategy: str
    direction: str
    entry: float | None = None
    exit: float | None = None
    pnl: float | None = None
    shadow_observed_at: datetime | None = None

    # Campos novos — todos default-safe pra retrocompat com records no disco
    would_enter: bool | None = None          # True sse todos gates pass E size > min
    gate_breakdown: list[GateOutcome] = []   # vazia = não avaliado (record legacy)
    filter_reason: str | None = None         # summary = primeiro gate.reason onde passed=False

    model_config = ConfigDict(extra="allow")
```

### Invariantes

| Invariante | Regra |
|-----------|-------|
| Consistência | `would_enter == True` ⇔ `all(g.passed for g in gate_breakdown)` |
| Razão de filtro | `filter_reason` == primeiro `g.reason` onde `g.passed is False`; `None` se `would_enter=True` |
| Retrocompat | Record sem campos novos deserializa OK (defaults kickam in) |
| Ordem | `gate_breakdown` preserva ordem de avaliação do runner |

Invariantes são verificadas em unit tests — se violadas, pydantic não
levanta mas o runner escreveu inconsistente. Teste dedicado
`test_trade_record_invariants` fecha esse hole.

---

## Runner — `tools/millennium_shadow.py`

### Nova função: `build_trade_record_with_gates()`

Wrapea a lógica de decisão existente. **Não toca em `core/*` protegido** —
apenas chama as funções que já existem (`core/signals.decide_direction`,
`core/portfolio.portfolio_allows`, `core/portfolio.position_size`) e
estrutura os retornos como `GateOutcome`.

```python
def build_trade_record_with_gates(
    signal_raw: dict,            # {ts, symbol, direction, entry, indicators}
    macro: str,                  # "BULL" | "BEAR" | "CHOP" (de detect_macro)
    portfolio_state: dict,       # {open_positions, correlations}
    params: dict,                # config.params
) -> TradeRecord:
    gates: list[GateOutcome] = []

    # 1. Regime (reaproveita config.params.SCORE_BY_REGIME)
    regime_allowed = signal_raw["direction"] in allowed_directions(macro, params)
    gates.append(GateOutcome(
        name="regime",
        passed=regime_allowed,
        reason=None if regime_allowed else f"regime={macro} veta {signal_raw['direction']}",
        value=None,
    ))

    # 2. Chop filter (usa score existente de decide_direction)
    chop_ok = signal_raw["indicators"].get("score_chop", 1.0) >= params["CHOP_THRESHOLD"]
    gates.append(GateOutcome(
        name="chop",
        passed=chop_ok,
        reason=None if chop_ok else "vol_regime=CHOP",
        value=signal_raw["indicators"].get("score_chop"),
    ))

    # 3. Correlation (via portfolio_allows, already-computed cross-correlation)
    corr_ok, corr_val = check_correlation(signal_raw["symbol"], portfolio_state, params)
    gates.append(GateOutcome(
        name="correlation",
        passed=corr_ok,
        reason=None if corr_ok else f"corr_max={corr_val:.2f}",
        value=corr_val,
    ))

    # 4. Max open positions
    n_open = len(portfolio_state.get("open_positions", []))
    max_ok = n_open < params["MAX_OPEN_POSITIONS"]
    gates.append(GateOutcome(
        name="max_positions",
        passed=max_ok,
        reason=None if max_ok else f"open={n_open}/{params['MAX_OPEN_POSITIONS']}",
        value=float(n_open),
    ))

    # 5. Size > min (Kelly × convex × dd_scale × omega_risk)
    size = compute_size(signal_raw, portfolio_state, params)   # função existente
    size_ok = size >= params["MIN_POSITION_SIZE_USD"]
    gates.append(GateOutcome(
        name="size_ok",
        passed=size_ok,
        reason=None if size_ok else f"size=${size:.2f} < min",
        value=size,
    ))

    # Derivados
    would_enter = all(g.passed for g in gates)
    first_fail = next((g for g in gates if not g.passed), None)

    return TradeRecord(
        timestamp=signal_raw["ts"],
        symbol=signal_raw["symbol"],
        strategy="MILLENNIUM",
        direction=signal_raw["direction"],
        entry=signal_raw["entry"],
        would_enter=would_enter,
        gate_breakdown=gates,
        filter_reason=first_fail.reason if first_fail else None,
        shadow_observed_at=datetime.now(timezone.utc),
    )
```

**Notas:**
- `allowed_directions`, `check_correlation`, `compute_size` são
  helpers LOCAIS em `millennium_shadow.py` que delegam pras funções
  protegidas em `core/`. Pureza do CORE preservada.
- Os nomes de gate acima (`regime`, `chop`, `correlation`,
  `max_positions`, `size_ok`) viram enum implícito consumido pelo
  cliente. Adicionar gate novo = append ao final; client tolera gates
  desconhecidos (lista é genérica).

### Call-site hook

No loop principal de `millennium_shadow.py`, onde hoje há
`detect_signals()` → `append_trade_record()`, substitui por:

```python
for signal in detect_signals(...):
    record = build_trade_record_with_gates(
        signal, macro, portfolio_state, params,
    )
    atomic_append_jsonl(trades_path, record.model_dump(mode="json"))
```

---

## Cockpit API — `tools/cockpit_api.py`

**Zero mudança de código.** `TradeRecord` com `ConfigDict(extra='allow')`
já serializa os campos novos. Validação pelo `GateOutcome` roda no
client-side deserialize.

**Smoke pós-deploy:** endpoint `/v1/runs/{id}/trades` retorna JSON com
`gate_breakdown: [{name, passed, reason, value}, ...]` — verificado em
`tests/test_cockpit_api.py::test_trades_preserves_gate_breakdown`.

---

## Launcher UI — `launcher_support/engines_sidebar.py` (NOVO)

### Componente: `render_sidebar()`

```python
def render_sidebar(
    parent: tk.Widget,
    engines: list[EngineRow],      # [(slug, display_name, status, summary), ...]
    selected_slug: str | None,
    on_select: Callable[[str], None],
) -> tk.Frame:
    """Sidebar lateral fixa (width=180). Lista engines registradas (do
    config/engines.py). Engine ativo = highlight AMBER_B. Engine sem
    run = DIM2 + placeholder '—'."""
```

**Linha de engine:**
```
  ▸ MILLENNIUM       ← selecionado, amber bg
    ✓ 41t · 625s     ← subline smaller, dim
  ○ CITADEL          ← não selecionado
    —                ← sem run ativo
  ○ JUMP
    —
```

### Componente: `render_detail()`

```python
def render_detail(
    parent: tk.Widget,
    engine: str,
    mode: Mode,
    heartbeat: Heartbeat | None,
    manifest: Manifest | None,
    trades: list[TradeRecord],
) -> tk.Frame:
    """Painel detail flex (right). 4 seções: HEALTH, RUN INFO,
    LAST SIGNALS (expandida), ACTIONS."""
```

### Tabela LAST SIGNALS — coluna status expandida

| time   | sym  | dir  | entry    | status                  |
|--------|------|------|----------|-------------------------|
| 19:02  | BTC  | LONG | 65432.0  | ✓ would_enter           |
| 18:47  | ETH  | SHRT | 3210.5   | ✗ chop                  |
| 18:45  | LINK | LONG | 14.23    | ✗ correlation=0.83      |
| 18:30  | SOL  | LONG | 142.8    | —                       |

**Rules:**
- `would_enter == True` → `✓ would_enter` em GREEN
- `would_enter == False` → `✗ <short_reason>` em RED (truncado a 30 chars)
- `would_enter is None` → `—` em DIM (legacy record pre-upgrade)
- Reason vem de `filter_reason` pra evitar re-scan do `gate_breakdown`
- Row clicada expande tooltip/popup com `gate_breakdown` completo
  (deferido pra Fase 3 se escopo permitir — YAGNI agora, render linha
  única bast)

### Paleta

Reutiliza `core/ui_palette.py` — zero cor nova introduzida:
- `AMBER_B` — highlight selected row
- `GREEN` — would_enter ✓
- `RED` — filter_reason ✗
- `DIM2` — engine inactive, legacy ─
- `PANEL` + `BORDER` — sidebar bg

### Refactor em `engines_live_view.py`

`_render_detail_shadow` é extraído pra `engines_sidebar.render_detail`.
O render atual fica deprecated como fallback (comment-tagged
`# TODO remove pós Fase 2b stable`).

Aplicação aos outros modos: `_render_live_panel`, `_render_paper_panel`,
etc passam a usar `engines_sidebar.render_sidebar` + `render_detail`.
Source data muda (`_PROCS_CACHE` em vez de `shadow_poller.cache`), mas
component layer é idêntico — single source of truth visual.

---

## Testing

### Suite atual
- Baseline: `1223 passed, 7 skipped`
- Meta pós-feature: `≥1235 passed` (≥12 tests novos)

### Arquivos de teste

| Arquivo | Novo/Extend | Cenários cobertos |
|---------|-------------|-------------------|
| `tests/test_shadow_contract.py` | extend | TradeRecord com novos campos, sem novos campos (legacy), GateOutcome invariants (`passed=True ⇒ reason is None`), serialize/deserialize round-trip |
| `tests/test_millennium_shadow_gates.py` | NOVO | `build_trade_record_with_gates` em 6 cenários: all_pass, regime_fail, chop_fail, correlation_fail, max_pos_fail, size_fail. `filter_reason` sempre bate com o primeiro fail. Invariante `would_enter == all(passed)` sempre vale. |
| `tests/test_cockpit_api.py` | extend | `/v1/runs/{id}/trades` retorna `gate_breakdown` quando presente no disk; tolera trades legacy sem o campo |
| `tests/test_engines_sidebar.py` | NOVO | `render_sidebar` lista engines do registry, destaca selected, mostra `—` pra engines sem run; `render_detail` renderiza HEALTH/RUN INFO/LAST SIGNALS; signals table colore ✓/✗/—; trunca reason a 30 chars |
| `tests/test_engines_live_view_cockpit.py` | extend | Integration: engines_live_view usa engines_sidebar componente; mesma sidebar aparece em modo SHADOW e modo paper/demo/testnet/live |

### Smoke manual (pós-deploy)

1. `python launcher.py` → EXECUTE → ENGINES LIVE
2. Confirma sidebar à esquerda com 9 engines listadas, MILLENNIUM
   highlighted
3. Click em outra engine → sidebar marca selection, detail vazio (sem
   run ativo)
4. Click MILLENNIUM → detail populado com HEALTH/RUN INFO/LAST SIGNALS
5. Tabela LAST SIGNALS mostra misto de ✓ (verde) e ✗ (vermelho)
6. Mode cycle M → paper mode → mesma sidebar aparece, detail muda pra
   data local

### Regression

- `git diff feat/phi-engine -- core/indicators.py core/signals.py core/portfolio.py config/params.py`
  deve retornar vazio. Verificação automática no plano de execução.
- Re-rodar `pytest tests/test_millennium_shadow.py` existente garante
  que o runner continua emitindo trade records válidos.

---

## Rollout

### Fase 2a (dados) — implementar primeiro
1. `GateOutcome` + extensão `TradeRecord` em `core/shadow_contract.py`
2. Tests de contrato (`test_shadow_contract.py`)
3. `build_trade_record_with_gates` em `millennium_shadow.py`
4. Tests do runner (`test_millennium_shadow_gates.py`)
5. Deploy no VPS — novos trades começam a carregar breakdown.
   Trades antigos continuam deserializando com defaults.
6. Verificação: cockpit API `/trades` mostra campos novos.

### Fase 2b (UI) — depois de 2a estável
1. `engines_sidebar.py` (componente novo) + tests
2. Refactor `engines_live_view.py` pra usar o componente
3. Aplicar sidebar aos modos paper/demo/testnet/live (source muda)
4. Smoke manual + polish (cores, alinhamento, bordas)

### Deploy sequence
1. Merge `feat/shadow-gate-sidebar` → `feat/phi-engine`
2. Push
3. VPS: `git pull && sudo systemctl restart millennium_shadow.service`
4. Launcher local: reabre (pega novo `engines_sidebar.py`)
5. Observa 1h de trades novos no painel — gate_breakdown deve aparecer
   em 100% dos novos records

### Rollback (se algo der errado)
- Trade records novos convivem com legacy — só reverter o git
- `systemctl restart` volta ao runner anterior
- UI reverte com launcher reabrindo no commit anterior

---

## Backlog pós-Fase 2

Listar no session log final pra rastrear:

1. **Fase 3a — VPS settings UI** (host/port/tokens dentro do launcher)
2. **Fase 3b — Remote start/stop** (POST admin API)
3. **Fase 3c — Asset basket editor**
4. **Fase 3d — Multi-engine orchestrator** (N runners simultâneos)
5. **Fase 3e — VPN/tunnel hardening** (opcional — WireGuard vs SSH
   com rotação)
6. Migrar `build_trade_record_with_gates` pra `core/gates.py` quando
   CITADEL ou JUMP ganhar shadow runner (então 2+ engines precisam =
   justifica a abstração)
7. Tooltip expansível na row LAST SIGNALS com gate_breakdown completo
   (UX polish, deferido)
8. Column sort/filter na tabela LAST SIGNALS (UX polish, deferido)

---

## Questões abertas pro plano resolver

O design assume algumas APIs/símbolos sem ter lido 100% do código. O
plano de implementação deve resolver estas primeiro via leitura:

1. **Nome real do param de tamanho mínimo.** Chutei
   `MIN_POSITION_SIZE_USD` — verificar em `config/params.py` o nome
   atual. Se não existir, usar o threshold que já é aplicado em
   `core/portfolio.position_size`.
2. **Nome real do score de chop.** Chutei `score_chop` — verificar
   o campo retornado por `core/signals.decide_direction` ou
   `core/signals.score_chop` (se existir). Adaptar a chave do dict.
3. **Estrutura atual do loop em `tools/millennium_shadow.py`.** Plano
   deve ler o loop antes de decidir onde inserir
   `build_trade_record_with_gates`. Hook deve ser não-invasivo.
4. **Schema atual de `trades.jsonl`.** Verificar se já tem
   `shadow_observed_at` e outros campos — não duplicar.
5. **Helpers em `core/`** pra reaproveitar:
   `portfolio_allows`, `position_size`, `detect_macro`,
   `decide_direction`. Plano lista assinaturas reais antes de escrever
   o wrapper.

Estas são "unknowns" aceitáveis pra spec (não são decisões de design)
— são detalhes de implementação que o plano TDD naturalmente captura
no primeiro task de leitura.

---

## Regras seguidas

- ✅ Zero linha em `core/indicators.py`, `core/signals.py`,
  `core/portfolio.py`, `config/params.py` (CORE protegido — CLAUDE.md)
- ✅ Anti-overfit protocol: não aplicável (feature de observabilidade,
  não é tune de params)
- ✅ YAGNI: abstração `core/gates.py` deferida até 2+ engines precisarem
- ✅ Single source of truth: `engines_sidebar.py` reutilizado em todos
  modos (shadow, paper, demo, testnet, live)
- ✅ Testes caracterizam comportamento — sem modificar código pra
  teste passar
- ✅ Atomic writes preservados (trades.jsonl atomic_append)
- ✅ Retrocompat: trade records legacy deserializam com defaults
