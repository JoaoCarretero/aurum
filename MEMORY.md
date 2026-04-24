# MEMORY.md — O que o AURUM nunca esquece

> **Propósito:** fatos permanentes e regras invioláveis. Lido em toda
> sessão antes de encostar em código. Se a sessão tiver 20 minutos,
> leia isto e o CLAUDE.md — dá pra operar.

---

## 1. ⚠️ CORE DE TRADING PROTEGIDO

**Estes 4 arquivos exigem aprovação explícita do Joao antes de qualquer edit:**

| Arquivo | Contém |
|---|---|
| `core/indicators.py` | EMA, RSI, ATR, BB, swing_structure, omega |
| `core/signals.py` | decide_direction, calc_levels, label_trade |
| `core/portfolio.py` | Kelly, position_size, check_aggregate_notional |
| `config/params.py` | SLIPPAGE, COMMISSION, SIZE_MULT, thresholds |

**Por quê:** backtests walk-forward calibrados dependem do comportamento exato desses módulos. Mudar a fórmula do RSI, o detector de pivots, ou os custos **invalida todas as calibrações** — CITADEL/BRIDGEWATER/DE SHAW/JUMP tiveram Sharpe +31% a +114% em re-calibrações, nenhuma dessas é trocável.

**Regra de ouro:** se teste sintético não reproduz comportamento esperado, **ajuste o teste** (threshold, fixture, skip com reason). Nunca o código. Isso é circular e destrutivo.

**Protegido estaticamente** em `pyproject.toml` via `[tool.ruff.lint.per-file-ignores]` pra esses 4 paths.

---

## 2. 🔐 config/keys.json — INTOCÁVEL

**NUNCA** sobrescreva `config/keys.json`. Nunca, por razão nenhuma:
- Nunca via `Write`, `Edit`, ou script de "setup que restaura template"
- Nunca commite (gitignored + pre-commit hook)
- Pra ler valores: `core.risk.key_store.load_runtime_keys` (não `json.load` direto)

**Se abrir e ver placeholders `COLE_AQUI_...` → alerte Joao imediatamente.** É incidente de wipe de secrets, não teu trabalho corrigir.

**Protocolo antes de mexer em `config/`:**
```bash
python tools/maintenance/verify_keys_intact.py
```
Exit code 1 = abort tudo, notificar Joao.

**Recuperação após wipe:**
1. OneDrive version history (File Explorer → right-click → Version history)
2. `~/.aurum-backups/keys/keys.json.<stamp>.bak` (backups locais, 20 mais recentes)
3. VPS `/srv/aurum.finance/config/keys.json` (telegram + connections)
4. VPS `/etc/aurum/cockpit_api.env` (tokens read/admin)
5. Password manager (Binance API, FRED, NewsAPI)

**Backup manual após mudança autorizada:**
```bash
python tools/maintenance/backup_keys.py
```

---

## 3. Incidentes fundadores (nunca mais)

### 2026-04-15 — Tentativa de wipe do CORE
Codex tentou trocar RSI (EWM→rolling+tanh) e swing_structure (backward→centered pivots) pra fazer asserts de contract tests passarem. Claude detectou e reverteu. **Regra fundada:** nenhum agente modifica código real pra fazer teste passar — ajusta o teste.

### 2026-04-19 — Wipe de keys.json
Um agente (Codex ou script de setup) executou "criar keys.json do template" sem checar se existia um populado. Resultado: cockpit sem dados, VPS unreachable, launcher bugado. **Regra fundada:** protocolo INTOCÁVEL da seção 2.

---

## 4. Status das engines (referência OOS 2026-04-17 atualizado)

| Engine | Verdict | Obs |
|---|---|---|
| **CITADEL** | ✅ EDGE_DE_REGIME | Validated; decay em 180d recent (investigar) |
| **JUMP** | ✅ EDGE_REAL | DSR ~1.0 em 3 janelas, 6/6 passed |
| **RENAISSANCE** | ⚠️ inflado 2× | Real ~2.4 Sharpe |
| **BRIDGEWATER** | ⚠️ episódico (quarentena) | Cascade harvester confirmado WF 10d×8 janelas (W3 +5.08, W6 +23.90). Aguarda cache OI/LS ≥90d (ETA 2026-06-19) pra re-abrir grid formal |
| **PHI** | 🆕 em overfit_audit | stagec_like displaced Sharpe ~9.1 |
| **DE SHAW** | 🗑️ DELETADO 2026-04-23 (Fase 1) | NO_EDGE — arquivo fonte removido |
| **KEPOS** | 🗑️ DELETADO 2026-04-23 (Fase 1) | INSUFFICIENT_SAMPLE — arquivo fonte removido |
| **MEDALLION** | 🗑️ DELETADO 2026-04-23 (Fase 1) | NO_EDGE — arquivo fonte removido |
| **ORNSTEIN** | 🗑️ DELETADO 2026-04-23 (Fase 1) | Mean-reversion — arquivo fonte removido |
| **GRAHAM** | 🗄️ experimental (stage registry) | Overfit honesto 4h value — ainda existe em `engines/graham.py` mas flag = archived informalmente |
| **JANE STREET** | ⚪ arb live | Scanner, não direcional |
| **MILLENNIUM/TWO SIGMA/AQR/WINTON** | orquestradores | meta-engines, não testados standalone |

**Engines vivos no repo (2026-04-23 após Fase 1 cleanup):** 12 (de 16). Lista canônica: `config/engines.py`.

---

## 5. Protocolo Anti-Overfit (5 princípios — não opcional)

Arquivo completo: `docs/methodology/anti_overfit_protocol.md`.

1. **Mecanismo > Iteração.** Hipótese escrita em 1 parágrafo **antes** de abrir código. Sem mecanismo defensável → arquiva.
2. **Split antes de código.** Datas train/test/holdout hardcoded no topo do engine. Não mudam.
3. **Grid fechado.** Lista de N configs pré-registrada em `docs/engines/<engine>/grid.md`. Commit antes de rodar.
4. **DSR obrigatório.** Sharpe reportado sem haircut por `n_trials` é mentira disfarçada.
5. **Regra de parada honra.** Falhou numa etapa → **arquiva**. Sem "reformular universo", sem "mais um iter".

**Nuance 2026-04-23** (memory `feedback_pushback_on_quick_archive.md`): antes de invocar "falhou → arquiva", questionar se o split foi válido pro tipo de edge. Pra edges **episódicos** (ex: BRIDGEWATER cascade), walk-forward deslizante é obrigatório — single split pode falsamente arquivar edge real. Joao pushback sobre isto: "desistir" não é automático quando split é ruim.

**Mas:** promoção/arquivamento (state `stage`, `EXPERIMENTAL_SLUGS`) sempre pede aprovação explícita do Joao. Quarentena é estado estável enquanto validação formal cozinha.

**Meta-regra:** 3 engines consecutivos arquivados → **pausa e revisa método**.

**Anti-patterns a rejeitar:**
- Comentários `iter_N WINNER` em `config/params.py` (trocar por `tuned_on=[...], oos_sharpe=X`)
- "Reformular até achar edge" (fishing expedition)
- Mesmo histórico pra tune e report
- Cherry-pick de symbol ou regime

---

## 6. Artifact locations canônicos

| Artefato | Path |
|---|---|
| **Pre-registered validation** | `docs/engines/<engine>/hypothesis.md`, `grid.md`, `checklist.md` |
| **Audits pontuais** | `docs/audits/YYYY-MM-DD_<topic>.md` |
| **Veredictos OOS** | `docs/audits/2026-04-16_oos_verdict.md` (base), superseded por arquivos `*_final_verdict.md` |
| **Run manifests** | `data/anti_overfit/<engine>/<timestamp>/manifest.json` + `results.csv` + `logs/` |
| **Runs individuais** | `data/<engine>/YYYY-MM-DD_HHMMSS_xxxxxx/` com `summary.json` (root), `trades.json`, `config.json`, `logs/<engine>.log` |
| **Índice canônico** | `data/index.json` (reconciled via `python -m tools.reconcile_runs`) |
| **Session logs** | `docs/sessions/YYYY-MM-DD_HHMM.md` |
| **Daily logs** | `docs/days/YYYY-MM-DD.md` |
| **Planos mestres** | `docs/superpowers/plans/YYYY-MM-DD-<slug>.md` |

---

## 7. Custos C1+C2 (backtest sem isso é mentira)

`config/params.py`:
- `SLIPPAGE` (entrada)
- `SPREAD` (saída)
- `COMMISSION` (por lado, Binance futures)
- `FUNDING_PER_8H` (carry em perpetuo)

Qualquer backtest que não aplica esses 4 não conta. Ver `docs/audits/backtest-physics-core-2026-04-10.md`.

---

## 8. Session log & Daily log (obrigatórios)

Ao fim de cada sessão (usuário diz "para", "commit final", "encerra", "session log", ou contexto acabando):

1. **Session log:** `docs/sessions/YYYY-MM-DD_HHMM.md` — formato exato no CLAUDE.md
2. **Daily log:** `docs/days/YYYY-MM-DD.md` — incrementa se já existe, cria se não
3. Commitar ambos junto com o último commit de trabalho

Se houve mudança em lógica de trading (sinais, custos, sizing, risco): destacar **ATENÇÃO:** no markdown.

---

## 9. Convenções inegociáveis

- Imports: engines importam de `core.*` e `config.params` — **nunca entre engines** (exceção documentada: `multistrategy` importa `engines/backtest.py`)
- `from config.params import *` no topo de cada engine
- Run dirs: `data/{engine}/{YYYY-MM-DD_HHMM}/` com `logs/`, `reports/`, `state/`
- Docs em PT-BR, engines/código em EN
- UTF-8 sempre. Windows-first (OneDrive, PyInstaller)
- Commits atômicos com subject + body
- Mudanças destrutivas: confirmar com Joao antes

---

## 10. Comandos diários

```bash
python smoke_test.py --quiet       # 156-178/178 esperado
python tools/maintenance/verify_keys_intact.py   # antes de mexer em config/
python -m tools.reconcile_runs     # reconciliar data/index.json
pytest -n 6                        # paralelo opt-in (26s vs 55s sequential)
```
