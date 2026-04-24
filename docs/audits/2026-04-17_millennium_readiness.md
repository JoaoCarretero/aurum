# Audit — MILLENNIUM readiness (grande dia)

**Data:** 2026-04-17
**Branch:** `feat/phi-engine`
**Contexto:** João vai rodar MILLENNIUM em um backtest "grande dia" hoje.
Audit completo em 4 lanes paralelas antes do GO.

---

## Veredito geral: **GO-COM-RESSALVAS**

> **Errata pós-fix (2026-04-17, fim do dia):**
> O core operacional atual do `MILLENNIUM` é `CITADEL + RENAISSANCE + JUMP`.
> `BRIDGEWATER` foi removida de `OPERATIONAL_ENGINES` depois deste audit,
> os pesos foram redistribuídos, e o caveat de `end_time_ms` ficou mitigado
> nos call-sites ativos do runner.

Sistema tá saudável e pode rodar. Três ressalvas operacionais pra atenção,
nenhuma bloqueadora.

| Lane | Veredito | Severidade máxima |
|------|----------|-------------------|
| 1. MILLENNIUM integrity | GO-COM-RESSALVAS | MED |
| 2. CORE + mudanças recentes | GO-COM-RESSALVAS | MED |
| 3. Tests + deps health | **GO** (limpo) | — |
| 4. Segurança + live/runtime | GO-COM-RESSALVAS | MED (deploy futuro) |

---

## ✅ O que tá saudável (evidências)

**Pesos recalibrados batem com código (snapshot 14:45)** — `engines/millennium.py:82-87`:
| Engine | Peso esperado | Peso no código | Match |
|--------|---------------|----------------|-------|
| JUMP | 0.30 | 0.30 | ✅ |
| BRIDGEWATER | 0.30 | 0.30 | ✅ |
| RENAISSANCE | 0.25 | 0.25 | ✅ |
| CITADEL | 0.15 | 0.15 | ✅ |
| Soma | 1.00 | 1.00 | ✅ |

**Suite de tests: full green**
- `smoke_test.py --quiet` → 178/178 passed
- `pytest tests/` → **1057 passed, 7 skipped** (os 7 são dívida de fixture antiga, não bloqueia)
- Contract tests novos do Codex (deshaw) → 15/15 passed
- `test_millennium_contracts.py` inclui `test_capital_weights_reflect_2026_04_17_calibration` que confirma JUMP>CITADEL, BW>CITADEL, cap CITADEL<=0.15, soma=1.0

**CORE protegido intacto** — `core/indicators.py`, `core/signals.py`,
`core/portfolio.py` não modificados hoje. `config/params.py` só teve
comentários atualizados (SLIPPAGE/SPREAD/COMMISSION/thresholds numéricos
inalterados).

**Imports sãos** — `engines.millennium / citadel / bridgewater / jump / deshaw / phi / renaissance` + `core.*` todos importam sem erro.

**Segurança baseline OK**:
- `keys.json` gitignored ✅
- `connections.json` runtime state sem credenciais ✅
- `core/risk_gates.py` funcional (8 gates implementados, não é scaffold)
- `core/audit_trail.py` funcional (JSONL append-only + hash chain SHA-256)
- `core/key_store.py` funcional (PBKDF2+Fernet)
- `core/proc.py` protege dupla instância (Fase 1)
- Exchange timeouts explícitos em `data.py`, `sentiment.py`, `exchange_api.py`

**MILLENNIUM é 100% backtest hoje** — não importa `engines/live.py`, não
carrega keys, não envia ordem. `config/engines.py:17` marca `live_ready: False`.

**Atomic writes backlog**: efetivamente FECHADO. Único watchpoint é
`janestreet.py:1582` (não afeta MILLENNIUM).

---

## ⚠️ Ressalvas operacionais (3 pra ficar de olho)

### R1 — Conflito de governança: FROZEN_ENGINES vs OPERATIONAL_ENGINES [MED, resolvido depois]

**Problema:** `config/params.py` lista `FROZEN_ENGINES = ["TWOSIGMA", "AQR", "RENAISSANCE"]` mas `engines/millennium.py:75` define `OPERATIONAL_ENGINES = ("CITADEL", "RENAISSANCE", "JUMP", "BRIDGEWATER")`. MILLENNIUM **não consulta** `FROZEN_ENGINES` — RENAISSANCE vai rodar mesmo marcada como congelada.

**Impacto:** Se João acha que a flag FROZEN bloqueia, vai ser surpreendido.
Se é esperado que RENAISSANCE rode (edge OOS 2.42 confirmado), a flag tá
decorativa e deveria ser limpa em breve.

**Ação:** confirmar intenção antes do GO. Se quiser rodar sem RENAISSANCE,
remover de `OPERATIONAL_ENGINES` temporariamente. Memory `project_backlog_aurum_2026_04_15` já menciona "Remover RENAISSANCE de FROZEN_ENGINES" como backlog.

### R2 — Possível look-ahead residual no sentiment do BRIDGEWATER [MED, mitigado depois]

**Problema:** `engines/millennium.py:1411` chama `collect_sentiment()` **sem**
`end_time_ms`. O fix aplicado hoje em `core/sentiment.py` (que derrubou
BRIDGEWATER de Sharpe 11 → 3.03) só opera quando `end_time_ms` é passado.

**Impacto:** Se o "grande dia" for backtest **OOS histórico delimitado**
(ex: 2022-2023), BRIDGEWATER vai receber sentiment atual (2026) como proxy
do passado — look-ahead residual. Se for backtest em janela padrão/live-like
(últimos N dias), é comportamento esperado e seguro.

**Ação:** confirmar janela do run. Se for OOS rigoroso, o caller precisaria
passar `end_time_ms` pro `_collect_operational_trades` — não é trivial.
Alternativa: registrar caveat nos resultados do BRIDGEWATER pós-run.

### R3 — Pesos fantasmas legados em millennium.py [LOW]

**Problema:** `engines/millennium.py:70-71` define `CITADEL_CAPITAL_WEIGHT = 0.65` e `RENAISSANCE_CAPITAL_WEIGHT = 0.35` que **não são usados** pelo path op=1 (CORE OPERATIONAL). Só são lidos pela função legada `ensemble_reweight()` (linhas 341-376), ativa só em path "CITADEL + RENAISSANCE".

**Impacto:** zero operacional pra rodar op=1. Risco: confusão em leitura
futura do código ou se alguém trocar op inadvertidamente.

**Ação:** anotar pra cleanup depois do run.

---

## 📋 Protocolo de GO (checklist antes de apertar run)

Preferencialmente:

1. **Rodar `python -m pytest tests/test_millennium_contracts.py -v`** pra confirmar os 6 contract tests verdes (especialmente `test_capital_weights_reflect_2026_04_17_calibration`).
2. **Escolher opção 1 (CORE OPERATIONAL)** no menu — CITADEL + RENAISSANCE + JUMP. **NÃO** opção 7 (ALL) nem 8 (TWO SIGMA), que puxam DE SHAW (experimental) e contaminam métricas.
3. **Confirmar janela do run** pra decidir R2:
   - Janela padrão / últimos N dias → safe
   - OOS histórico delimitado → caveat no BRIDGEWATER
4. **Decidir sobre R1** (RENAISSANCE rodar ou não).
5. **(Opcional) commitar ou stashear** mudanças unstaged do Codex (`engines/deshaw.py`, `engines/phi.py`, `tests/test_phi.py`) pra ter estado reproduzível. Não é bloqueador porque op=1 não chama deshaw/phi.
6. **Durante o run**, monitorar `data/millennium/<timestamp>/logs/mercurio.log`.

---

## 🔴 Issues pra deploy futuro (NÃO bloqueiam hoje)

**S1 — `janestreet.py:1582`: flush implícito antes de `os.replace`**
Padrão `mkstemp + os.fdopen + json.dump + os.replace` sem `f.flush()`
explícito. Em OneDrive com sync ativo, `os.replace` pode acontecer antes
do OS gravar o buffer. Fix: adicionar `f.flush(); os.fsync(fd)` ou migrar
pra `core.fs.atomic_write`. Não afeta MILLENNIUM (JANE STREET não é
chamada em op=1).

**S2 — Verificar histórico git de `config/keys.json`**
Audit read-only não rodou `git log --all -p -- config/keys.json`. Dado o
incidente do `AURUM.spec` incluindo keys.json no build (corrigido hoje),
vale uma verificação manual.

**S3 — `config/risk_gates.json` fora do `.gitignore`**
Arquivo contém thresholds de risco (não credenciais), decisão de política
se versiona ou não.

**S4 — Pesos fantasmas + FROZEN_ENGINES ghost-flags**
R1 + R3 juntos = limpar flags decorativas em `params.py` e `millennium.py`
pra evitar confusão futura.

---

## Referências

- Lane 1 full: agent internal ID a6080803db3cd3b3d
- Lane 2 full: agent internal ID a967977065e91d215
- Lane 3 full: agent internal ID a16d1a3f1af36ddaf
- Lane 4 full: agent internal ID aa6f2ca7f6a339b60
- Daily log: `docs/days/2026-04-17.md`
- OOS verdict anterior: `docs/audits/2026-04-17_oos_revalidation.md`
- Anti-overfit protocol: `docs/methodology/anti_overfit_protocol.md`
