# Lane 2b — HMM Speedup — Design (v2, hardened)

**Data:** 2026-04-19 (v2 reescrita após review João)
**Branch de origem:** `feat/phi-engine` (commit 92cd2d8, pós-spec v1)
**Branch de trabalho:** `feat/lane-2b-hmm`
**Escopo:** reduzir o wall-time de CITADEL 180d em ≥25% via otimização
numérica do `GaussianHMMNp.fit` e seu hot path, preservando **byte-a-byte**
o output do HMM e o trade-ledger de **todos os 5 engines HMM-users** em
**4 janelas históricas** (canônica + 3 adversariais).
**Protocolo:** anti-overfit (mecanismo pré-registrado, grid fechado,
regra de parada honra). Ver `docs/methodology/anti_overfit_protocol.md`.
**Postura:** paranoia de quant profissional. Logica de estratégia é o
ativo. Speedup é bônus. Nunca se troca rigor numérico por velocidade.

---

## Contexto herdado

Lane 2 Fase A (2026-04-18, `docs/audits/2026-04-18_battery_perf_profile.md`)
identificou `GaussianHMMNp.fit` em `core/chronos.py:174` consumindo **43%
do wall-time** de CITADEL 180d (47.2s). O gargalo não estava nas 6
hipóteses pré-registradas originalmente, então foi registrado sem atacar
— per protocolo, nova hipótese exige novo ciclo com pre-register formal.
Este design abre esse ciclo.

HMM é usado por 5 engines (consumo confirmado via grep em engines/*.py):

| Engine | Campos consumidos | Uso |
|---|---|---|
| `citadel.py` | `regime_label`, `confidence`, `prob_{bull,bear,chop}` | Report + regime_analysis |
| `bridgewater.py` | idem | Idem |
| `deshaw.py` | idem | Idem |
| `jump.py` | idem | Idem |
| `medallion.py` | `prob_{bull,bear,chop}` **em lógica de decisão** (linha 413-415) | 1 bit de float diferente → trade diferente |

Ganho em HMM fit se propaga proporcionalmente. Risco também.

---

## Hipóteses pré-registradas (v2)

### H7 — Memoization de `GaussianHMMNp.fit` por hash de X_train

- **Mecanismo:** se o mesmo `X_train` for passado duas vezes, reusa o
  modelo treinado em vez de re-treinar.
- **Pré-teste obrigatório (antes de codar):** contador temporário em
  `_build_hmm_backend` → rodar CITADEL 180d → esperado ≤11 calls
  (1/símbolo). Se for o caso, **H7 MORTA** antes de qualquer
  implementação. Se ≥2× por símbolo, H7 viva.
- **Fix (se viva):** função wrapper puro-funcional com
  `@functools.lru_cache(maxsize=256)`. Chave:
  `hashlib.sha1(X_train.tobytes()).hexdigest()`. Cache em-memória por
  processo. Inline em `core/chronos.py` se ≤40 LoC; senão em
  `core/_hmm_cache.py`.
- **Risco numérico:** **zero** — reusar modelo já treinado dá output
  bit-identical por definição. Único risco é hash colisão (mitigado
  por catch guard).
- **Veredito esperado:** provavelmente morta no diagnóstico.

### H8 — `scipy.special.logsumexp` → implementação numpy local

- **Mecanismo:** `logsumexp` é chamado dentro de loop EM (100 iters × 2
  passes forward/backward × ~500 amostras). scipy tem overhead de
  dispatch (checa axis, keepdims, b, return_sign). Inline
  `np.log(np.exp(x - x.max(axis=1, keepdims=True)).sum(axis=1)) + x.max(axis=1)`
  evita overhead.
- **Pré-teste:** microbench isolado `scipy.special.logsumexp` vs local
  em array de shape (500, 3). Esperado: 2–5× speedup na função.
- **Fix:** auxiliar `_logsumexp_axis1(M)` em `core/chronos.py` + 2
  substituições em `_forward` e `_backward` de `GaussianHMMNp`.
- **Risco numérico:** médio. scipy pode usar paths diferentes (LogsumExp
  estável vs subtração simples do max). Diferença em último bit de
  float64 é esperada. Passa no invariante de 3 camadas **somente se**
  math for idêntica em aritmética IEEE 754. Se não passar → H8 morre.
- **Ganho esperado:** 10–20% do wall-time total CITADEL 180d.

### H9 — **ARQUIVADA preemptivamente**

Substituir backend `GaussianHMMNp` por `hmmlearn.GaussianHMM` envolve
init diferente (k-means com múltiplos restarts) e path de convergência
diferente. Bit-identical em todas 4 janelas × 11 símbolos é
matematicamente quase impossível.

H9 fica **fora deste ciclo**. Exploração futura exige ciclo próprio
dedicado a quantificar equivalência de convergência sob seeds
adversariais — não mistura com speedup.

---

## Invariante de Integridade — 3 Camadas (ordem go/no-go)

**Princípio:** integridade é binária. Speedup é contínuo. Integridade
falha = fim, sem discussão. Speedup só é medido **depois** das 3
camadas passarem.

### Camada 1 — HMM Output (per-símbolo, per-janela)

Dump das 6 colunas HMM (`hmm_regime`, `hmm_regime_label`,
`hmm_prob_bull`, `hmm_prob_bear`, `hmm_prob_chop`, `hmm_confidence`)
para CSV determinístico:

```
tests/fixtures/hmm_golden/{window}/{symbol}_hmm_cols.csv
tests/fixtures/hmm_golden/{window}/{symbol}_hmm_cols.sha256
```

Formato do CSV: pandas `to_csv(path, float_format='%.17g')` para
preservar precisão total. sha256 do CSV commitado em git.

**Pass:** `sha256(post_fix_csv) == sha256(golden)` para todo (símbolo,
janela).
**Fail:** qualquer digest diferente → fix rejeitado. Não passa pra
Camada 2.

### Camada 2 — Per-Engine Trade Ledger (4 janelas × 5 engines)

Rodar os **5** engines HMM-users em cada uma das **4 janelas**:

```
data/{engine}/{run_id}/reports/trades.csv
```

sha256 comparado contra golden:

```
tests/fixtures/hmm_golden/{window}/{engine}_trades.sha256
```

**Pass:** todos 20 digests (4 × 5) batem.
**Fail:** qualquer um diverge → fix rejeitado.

### Camada 3 — Equity Curve + Métricas Agregadas

Para cada (engine, janela):
- sha256 de `equity.csv` (curva equity bar-a-bar)
- Campos específicos de `report.json`: `total_trades`, `win_rate`,
  `sharpe_ratio`, `max_drawdown`, `total_pnl` — dumpados ordenados e
  sha256

Total: 40 digests (4 × 5 × 2).

**Pass:** todos batem.
**Fail:** rejeita.

**Racional das 3 camadas:** Camada 1 pega drift no output do HMM
direto. Camada 2 pega drift que passou pela decide_direction dos
engines. Camada 3 pega drift em ordem de fechamento / PnL que não
mudou o número de trades. Redundância intencional — cada camada
pega classe de bug diferente.

---

## Janelas de Teste (4 janelas pré-registradas)

| Janela | Período | Universo | Regime | Por quê |
|---|---|---|---|---|
| `canonical_180d` | 2024-10-01 → 2025-03-31 | 11 altcoins AURUM | Mix | Baseline do audit Fase A (47.2s) |
| `stress_covid` | 2020-02-15 → 2020-04-15 | Subset disponível (BTC, ETH, BNB, LINK, XRP) | Crash violento | Regime switching extremo |
| `stress_ftx` | 2022-10-15 → 2022-12-31 | Universo AURUM filtrado por disponibilidade | Bear profundo | Vol amplificada, downtrend estrutural |
| `stress_etf_rally` | 2024-01-01 → 2024-03-31 | 11 altcoins AURUM | Bull estrutural | Estabilidade de regime + subidas |

**Universo por janela** é commitado em
`tests/fixtures/hmm_golden/{window}/universe.txt` (um símbolo por
linha). Gerado uma vez durante o setup, imutável dali em diante.

**Invariante:** fix só é aceito se passar 3 camadas em **todas 4
janelas**. Passa em 3/4 = rejeitado.

---

## Golden Fixture Lock (executado ANTES de qualquer fix)

Setup Etapa 0 cria e commita em git:

```
tests/fixtures/hmm_golden/
  ├── canonical_180d/
  │   ├── universe.txt
  │   ├── BNBUSDT_hmm_cols.csv         (pinned, float_format='%.17g')
  │   ├── BNBUSDT_hmm_cols.sha256
  │   ├── ... (11 símbolos × 6 arquivos)
  │   ├── citadel_trades.sha256
  │   ├── citadel_equity.sha256
  │   ├── citadel_metrics.sha256
  │   ├── ... (5 engines × 3 arquivos)
  ├── stress_covid/
  ├── stress_ftx/
  └── stress_etf_rally/
```

Total estimado: 4 janelas × (11 símbolos × 2 + 5 engines × 3) =
4 × 37 = **~148 arquivos pinnados em git**. Exato varia por
disponibilidade de símbolos.

Commit: `fix(fixtures): lock HMM golden outputs antes de Lane 2b` —
feito **ANTES** de qualquer code change em chronos.py.

---

## Dual Verification (contra bug no próprio check)

### Caminho primário
`tests/perf/test_hmm_integrity.py` — roda 3 camadas × 4 janelas,
compara sha256 automaticamente.

### Caminho secundário (independente)
`tools/audits/hmm_output_recompute.py` — script standalone que:
1. Recomputa HMM outputs do zero (baseline branch vs post-fix branch)
2. Usa pandas testing `assert_frame_equal(rtol=0, atol=0)` em vez de
   sha256 — redundância via abordagem diferente
3. Cospe report txt com qualquer célula divergente (symbol, bar, col)

Ambos devem concordar. Se primário passa e secundário falha (ou
vice-versa) → fix rejeitado até descobrir por quê.

---

## Métrica de speedup (medida APENAS após integridade passar)

### Cenário canônico (único)

```bash
python -m engines.citadel --days 180 --no-menu
```

- **Baseline gravado:** 47.2s wall / 38.6s CPU (Fase A, 2026-04-18)
- **Sample size:** 3 runs, mediana reportada
- **Hardware-lock:** mesma máquina, idle, AC power estável

### Gates

- **Por fix:** `gain_pct ≥ 10%` no delta vs run imediatamente anterior
  → fix fica. Senão `git revert`. **MAS:** integridade 3-camadas × 4-janelas
  tem que passar **antes** desta medição. Sem integridade, nem mede speedup.
- **Do ciclo:** `gain_pct_total ≥ 25%` vs baseline 47.2s. Senão ciclo
  fecha como "insuficiente".

### Microbench secundário (diagnóstico, não gate)

- `pyinstrument` em `GaussianHMMNp.fit` isolado
- scipy vs local `logsumexp` em array fixo
- Artefatos em `data/perf_profile/2026-04-19/`

---

## Regra de Parada Honra

- **2 hipóteses consecutivas falham no gate de 10%** (após passar
  integridade) → ciclo para imediatamente.
- **Hipótese quebra qualquer camada de integridade** → fix revertido +
  hipótese arquivada + próxima hipótese considerada normalmente (não
  conta como falha consecutiva pro stop rule).
- **Todas hipóteses morrem nos diagnósticos** → ciclo fecha como falha
  honra, mantém golden fixtures como contribuição (valor permanente).

---

## Kill Switch / Rollback Plan (post-merge)

### Auto-revert script
`tools/audits/hmm_rollback.py` — se invocado, faz `git revert` da
branch de merge e roda suite de integridade contra o commit original
pra confirmar rollback limpo.

### Shadow mode (condicional por hipótese)

**H7 (memoization) — shadow DISPENSADO.** Reusar modelo já treinado
é bit-identical por construção (mesma memória → mesmo output).
Integridade das 3 camadas em histórico é garantia suficiente.

**H8 (logsumexp local) — shadow OBRIGATÓRIO 72h.** Mudança
algorítmica em aritmética IEEE 754 pode ter comportamento divergente
em distribuições não representadas no histórico de teste.
- Rodar shadow 72h: ambos HMM (antigo e novo) computam outputs lado
  a lado em dados live, compara digest por símbolo/bar em tempo real
- **NENHUMA ENTRADA DE POSIÇÃO** pela versão nova durante shadow
- Se diverge em 1 bar → rollback automático
- Infra: reusar `millennium_shadow` (VPS live já tem pipeline)
- Registrar tudo em `data/shadow/hmm_lane_2b/{date}/`

### Triggers de rollback
- Divergência detectada em shadow
- Regressão numérica em weekly integrity re-run
- Engine em live retorna trade diferente do walkforward da mesma data

---

## Ordem de Execução (atualizada)

| # | Etapa | Budget | Ação | Gate |
|---|---|---:|---|---|
| 0 | Setup + golden lock | **90 min** | Branch + gravar goldens × 4 janelas × 5 engines × 11 símbolos + commit fixtures | 148 digests em git |
| 1 | Diagnóstico H7 | 15 min | Contador em `_build_hmm_backend` + run 180d | ≤11 calls → arquiva |
| 2 | Impl H8 | 60 min | Microbench + code + 3 camadas × 4 janelas (integridade primeiro) + 3 runs CITADEL (speedup) | 3 camadas × 4 janelas × dual-verify + ≥10% |
| 3 | Impl H7 (se viva) | 45 min | lru_cache + 3 camadas × 4 janelas + 3 runs CITADEL | Idem |
| 4 | Consolidação | 30 min | Ganho total ≥25%? Suite completa verde? Report | n/a |
| 5 | Shadow mode (só se H8 passou) | **72h wall** | Lado-a-lado em live, sem abrir posição | Zero divergência em bar |
| 6 | Declarar estável | 15 min | Remove shadow (se houve), merge final | n/a |

**Budget de hands-on (etapas 0-4):** ~4h com medições paralelizadas
(engines rodam em subprocess, dá pra rodar 5 engines em paralelo por
janela → 4 janelas × 47s ≈ 3-5 min por attempt se paralelo).

**Shadow:** 72h wall-time passivo, não bloqueia outras atividades.

---

## Audit Trail Automático

### Pré-fix
- Commit `fix(fixtures): lock HMM golden outputs antes de Lane 2b`
  com os 148 digests pinnados

### Por attempt de fix
Script `tools/audits/hmm_attempt_report.py` gera:
`docs/audits/2026-04-19_lane_2b_fix_{hypothesis}_attempt_{N}.md`

Conteúdo:
- Hipótese tentada + commit hash
- Tabela: (janela, engine/símbolo, camada) → (expected_digest,
  observed_digest, match/diff)
- Speedup medido (wall-time pré/pós, mediana de 3 runs)
- Dual-verify result (primário vs secundário)
- Veredito: PASS / FAIL_INTEGRITY_LAYER_{1,2,3} / FAIL_SPEEDUP / REVERTED

### Pós-merge
- `docs/audits/2026-04-19_lane_2b_final.md` consolidado
- Scheduled weekly re-run via Lane 3 (futuro) ou manual

---

## Escopo do Código

### Mudanças em produção
- `core/chronos.py` — `_logsumexp_axis1` auxiliar + substituições em
  `_forward`/`_backward` (H8)
- `core/chronos.py` ou `core/_hmm_cache.py` — wrapper lru_cache (H7 se
  viva)

### Novos artefatos permanentes
- `tests/fixtures/hmm_golden/` (148 arquivos)
- `tests/perf/test_hmm_integrity.py`
- `tools/audits/hmm_output_recompute.py`
- `tools/audits/hmm_attempt_report.py`
- `tools/audits/hmm_rollback.py`
- `docs/audits/2026-04-19_lane_2b_final.md`

### Fora do escopo (explícito)
- `core/indicators.py`, `core/signals.py`, `core/portfolio.py`,
  `config/params.py` — CORE PROTEGIDO, zero linhas
- Loop body de `_forward`/`_backward` além da substituição de
  `logsumexp` (H10 parkada)
- hmmlearn / C backend (H9 parkada pra ciclo próprio)
- Cython, numba, GPU, polars
- Outras funções de `chronos.py` (GARCH, Hurst, seasonality)

---

## Critério de Fechamento

Ciclo termina em 1 dos 4 estados:

1. **Sucesso completo:** ganho ≥25%, 3 camadas × 4 janelas bit-identical,
   72h shadow zero-divergência → merge pra `feat/phi-engine` + PR pra `main`
2. **Sucesso parcial integrity-intact:** ganho 10–25%, integridade
   perfeita, shadow ok → merge com caveat documentado
3. **Falha integridade:** qualquer digest diverge → **NADA fica**,
   apenas golden fixtures + audit docs
4. **Falha honra (diagnósticos):** H7 + H8 morrem → golden fixtures +
   docs + hipótese nova parkada (H9, H10, etc) pra ciclo futuro

**Em nenhum caso** iterar hipótese não-pré-registrada dentro deste
ciclo. Não há exceção pra "só mais uma coisa". Disciplina > payoff.

---

## Audit of the Audit

Este spec inteiro é um contrato. Qualquer modificação durante
execução exige:
1. Commit isolado alterando este arquivo, com justificativa no body
2. Não vale "ajustar no meio" pra acomodar achado
3. Se justificativa é sólida, pausa ciclo, atualiza spec, reinicia
   do setup com golden fixtures re-travados

**O spec é o controle. Rodada de achado que não cabe no spec ≠
motivo pra relaxar spec.**
