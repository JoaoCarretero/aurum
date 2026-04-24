# Safety Contract Tests — `engines/live.py` & `engines/janestreet.py`

**Data:** 2026-04-17
**Branch alvo:** feat/phi-engine (ou nova branch dedicada)
**Origem:** audit estrutural 2026-04-17 — 7 engines em production sem teste; `live` e `janestreet` movem dinheiro real.

---

## Objetivo

Adicionar **9 safety-contract tests** distribuídos em 2 novos arquivos (`tests/test_live_contracts.py` e `tests/test_janestreet_contracts.py`) cobrindo invariantes cuja violação causa dano real (perda financeira, exposure descontrolada, exchange call não autorizada).

**Não-objetivo:** cobertura completa, testes E2E, mocks completos de exchange, cobertura dos outros 5 engines descobertos (jump, renaissance, twosigma, aqr, medallion — viram backlog).

---

## Escopo dos arquivos

### `tests/test_live_contracts.py` (5 testes, ~150 linhas)

| Teste | Função alvo | Invariante |
|---|---|---|
| `test_paper_mode_refuses_real_keys` | `engines.live._load_keys` | Modo `"paper"` nunca lê `config/keys.json` real; retorna dummy/empty |
| `test_guard_real_money_gates_blocks_live_without_config` | `engines.live._guard_real_money_gates` | `("live", degraded_cfg)` raise/aborta; nunca passa silenciosamente |
| `test_kill_switch_dispara_em_drawdown_limite` | `engines.live.KillSwitch` | Trajetória de PnL excedendo limite dispara `triggered=True` |
| `test_kill_switch_nao_dispara_dentro_do_limite` | `engines.live.KillSwitch` | Caso negativo — falso-positivo seria caro (interrompe trading válido) |
| `test_order_manager_paper_mode_zero_external_calls` | `engines.live.OrderManager` | Monkeypatch `requests.post`/Binance client; OrderManager paper executa N ordens com 0 chamadas externas |

### `tests/test_janestreet_contracts.py` (4 testes, ~120 linhas)

| Teste | Função alvo | Invariante |
|---|---|---|
| `test_parse_mode_default_is_paper` | `engines.janestreet._parse_mode` | Sem `--mode` flag retorna `"paper"`; nunca `"live"` por default |
| `test_hedge_monitor_detecta_delta_drift` | `engines.janestreet.HedgeMonitor` | Long+Short de mesmo notional = delta 0; quebrar perna → `monitor` reporta drift |
| `test_omega_score_penaliza_spread_negativo` | `engines.janestreet.omega_score` | `spread<0` retorna score abaixo do baseline (não recompensa arb perdedor) |
| `test_risk_gate_config_loads_per_mode` | `engines.janestreet._load_risk_gate_config` | `("live")` retorna gates strictly mais rígidos que `("paper")` |

---

## Princípios de design

1. **Anti-happy-path.** Cada teste verifica o que NÃO pode acontecer. O happy path já é exercido por smoke + uso real.
2. **Inline, sem fixtures compartilhadas.** Padrão `test_deshaw_contracts.py` — monkeypatch local, sem conftest novo.
3. **Monkeypatch params globais.** Custos (SLIPPAGE, COMMISSION, FUNDING_PER_8H, LEVERAGE) zerados por teste pra isolar comportamento.
4. **Nunca rodar `_launch()` ou `Engine().run()` inteiro.** Só superfícies isoladas (`_guard_real_money_gates`, `KillSwitch`, `HedgeMonitor`, `omega_score`, `_load_keys`, `_parse_mode`, `_load_risk_gate_config`, `OrderManager`).
5. **Sem mock de exchange completo.** Apenas `monkeypatch` em `requests.post`, `requests.get`, e clientes HTTP de venue. Suficiente pra provar "0 chamadas externas em paper".

---

## Regra anti-pattern (CLAUDE.md) respeitada

> "Se um teste sintético não reproduz o comportamento esperado, AJUSTE o teste. NÃO ajuste o código real pra fazer teste passar."

Se algum dos 9 testes falhar contra o código atual, a primeira hipótese é que o teste está errado (threshold, fixture, assumption). Só após investigação documentada é que se reporta como bug real.

---

## Riscos e mitigação

| Risco | Mitigação |
|---|---|
| `engines/live.py` cria diretórios no import (`LIVE_DIR = Path(...)`) | `Path()` não cria — só path object. Confirmado por inspeção (linha 187). Se `_setup_logging` for chamado no import, importar via `importlib` com monkeypatch antes. |
| `engines/janestreet.py` venue classes conectam no import via `build_venues()` | Inspecionar antes de implementar. Se sim, monkeypatch `requests.Session` antes do import. |
| Side effects em `LIVE_RUN_ID = f"{_LIVE_DATE}_{datetime.now()...}"` | Inofensivo (só string). |
| Testes acessam `KillSwitch` interno que pode mudar API | Aceito — contract test é exatamente isso (caracterização da API atual). Se KillSwitch refatorar, teste re-escrito. |
| Suite tempo (já tem ~70 arquivos) | 9 testes inline sem I/O — adiciona <1s. |

---

## Estrutura final

```
tests/
├── test_live_contracts.py           ← NOVO (5 testes, ~150 linhas)
├── test_janestreet_contracts.py     ← NOVO (4 testes, ~120 linhas)
└── conftest.py                       ← sem mudança
```

Total: 2 arquivos novos, ~270 linhas, 9 testes, 0 mudanças em código de produção.

---

## Critério de aceitação

1. `pytest tests/test_live_contracts.py tests/test_janestreet_contracts.py -v` → 9 passed.
2. Suite completa (`smoke_test.py --quiet`) continua verde.
3. Nenhum arquivo em `engines/`, `core/`, `config/` modificado.
4. Cada teste tem assertion substantiva (nada de `assert True`, nada de `assert obj is not None` solo).
5. Cada teste documenta no docstring **qual cenário do mundo real** ele protege contra.

---

## Backlog deixado pra próxima rodada

- Contract tests pra `jump` (validated OOS — travar comportamento atual)
- Contract tests pra `renaissance` (audit indicou inflado 2× — testar caracteriza)
- Contract tests pra `twosigma`, `aqr`, `medallion` (research — prioridade baixa)
- E2E test pra `live --mode paper` rodando 1 candle e desligando limpo
- Property-based tests (hypothesis) pra `omega_score` e `position_size`
