# Lane 2b — HMM Speedup — Design

**Data:** 2026-04-19
**Branch de origem:** `feat/phi-engine` (commit 30d4ed4)
**Branch de trabalho:** `feat/lane-2b-hmm`
**Escopo:** reduzir o wall-time de CITADEL 180d em ≥25% via otimização do
`GaussianHMMNp.fit` e seu hot path, sem alterar o trade-ledger de nenhum
engine HMM-user.
**Protocolo:** anti-overfit (mecanismo pré-registrado, grid fechado,
regra de parada honra). Ver `docs/methodology/anti_overfit_protocol.md`.

---

## Contexto herdado

Lane 2 Fase A (2026-04-18, `docs/audits/2026-04-18_battery_perf_profile.md`)
identificou `GaussianHMMNp.fit` em `core/chronos.py:174` consumindo **43%
do wall-time** de CITADEL 180d (47.2s). O gargalo não estava nas 6
hipóteses pré-registradas originalmente, então foi registrado sem atacar
— per protocolo, nova hipótese exige novo ciclo com pre-register formal.
Este design abre esse ciclo.

HMM é usado por 5 engines: `citadel`, `bridgewater`, `deshaw`,
`medallion`, `jump`, além de `core/harmonics.py`. Ganho em HMM fit se
propaga proporcionalmente a toda bateria que rode esses engines.

---

## Hipóteses pré-registradas

### H7 — Memoization de `GaussianHMMNp.fit` por hash de X_train

- **Mecanismo:** se o mesmo `X_train` (np.ndarray de returns+vol) for
  passado duas vezes, reusa o modelo treinado em vez de re-treinar.
- **Pré-teste obrigatório (antes de codar):** contador temporário em
  `_build_hmm_backend` → rodar CITADEL 180d → esperado ≤11 calls
  (1/símbolo). Se for o caso, **H7 MORTA** antes de qualquer
  implementação. Se ≥2× por símbolo, H7 viva.
- **Fix (se viva):** função wrapper puro-funcional com
  `@functools.lru_cache(maxsize=256)`. Chave:
  `hashlib.sha1(X_train.tobytes()).hexdigest()`. Cache em-memória por
  processo. Inline em `core/chronos.py` se ≤40 LoC; senão em
  `core/_hmm_cache.py`.
- **Risco:** baixo. HMM é determinístico (random_state=42). Hash
  colisão → catch guard em predict_proba.
- **Veredito esperado:** provavelmente morta no diagnóstico (1 call
  por símbolo em walk-forward single-pass).

### H8 — `scipy.special.logsumexp` → implementação numpy local

- **Mecanismo:** `logsumexp` é chamado dentro de loop EM (100 iters × 2
  passes forward/backward × ~500 amostras). scipy tem overhead de
  dispatch (checa axis, keepdims, b, return_sign). Inline
  `np.log(np.exp(x - x.max(axis=1, keepdims=True)).sum(axis=1)) + x.max(axis=1)`
  evita overhead.
- **Pré-teste:** microbench isolado `scipy.special.logsumexp` vs local
  em array de shape (500, 3). Esperado: 2–5× speedup na função
  isolada.
- **Fix:** auxiliar `_logsumexp_axis1(M)` em `core/chronos.py` + 2
  substituições em `_forward` e `_backward` de `GaussianHMMNp`.
- **Risco:** médio. Precisão numérica. Invariante B (trade-ledger)
  protege, mas diferença mínima em float pode cascatear em edge cases
  raros (probs muito próximas entre estados → nanargmax flip).
- **Ganho esperado:** 10–20% do wall-time total CITADEL 180d. Fase A
  mostrou `_forward` + `_backward` ≈ 20s de 47s total (ambos
  dominados por `logsumexp`). Se o overhead de dispatch do scipy é
  30–50% do tempo dessas chamadas, cortar dá 6–10s → 12–21% do total.

### H9 — Tentar instalar `hmmlearn` (backend C)

- **Mecanismo:** `_build_hmm_backend` já prefere `hmmlearn.GaussianHMM`
  quando `_HAS_HMM=True`. Python 3.14 Windows historicamente não
  instalava por falta de MSVC Build Tools. Tentar `pip install hmmlearn`
  no ambiente atual.
- **Pré-teste:** `pip install hmmlearn`. Se falha → **H9 MORTA,
  arquivar**. Se sucesso → CITADEL 180d com hmmlearn ativo, diff
  trade-ledger vs baseline GaussianHMMNp.
- **Fix (se viva):** nenhuma mudança de código — `_HAS_HMM` flag já
  trata dispatch. Adicionar `hmmlearn` como optional em
  `requirements.txt`.
- **Risco:** alto na integridade. hmmlearn usa init diferente (k-means
  com múltiplos restarts vs nosso single Lloyd's) e pode convergir
  para permutação de estados diferente. Se trade-ledger divergir → H9
  morre.
- **Ganho esperado:** 30–50% do wall-time total se convergência bater;
  0% caso contrário.

---

## Benchmark e métrica

### Cenário canônico (único)

```bash
python -m engines.citadel --days 180 --no-menu
```

- **Baseline gravado:** 47.2s wall / 38.6s CPU / 82% CPU utilization
  (Fase A, 2026-04-18)
- **Sample size:** 3 runs, mediana reportada
- **Hardware-lock:** mesma máquina, idle, AC power estável

### Métrica primária — wall-time

```python
speedup = baseline_wall / post_fix_wall
gain_pct = (baseline_wall - post_fix_wall) / baseline_wall
```

- **Gate por fix:** `gain_pct ≥ 10%` no delta vs run imediatamente
  anterior → fix fica. Senão `git revert`.
- **Gate do ciclo:** `gain_pct_total ≥ 25%` comparando baseline
  original (47.2s) vs final. Senão ciclo fecha como "insuficiente" e
  reverte tudo exceto diagnósticos e docs.

### Métrica secundária — HMM fit isolado

Microbench via `pyinstrument` focado em `GaussianHMMNp.fit` (ou
hmmlearn equivalente). Não é gate — é instrumento de validação da
mecânica (confirmar que o ganho veio de onde a hipótese previu).

### Invariante de integridade — trade-ledger idêntico (critério duro)

```python
import hashlib, pathlib
digest = lambda p: hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
assert digest(baseline_trades_csv) == digest(post_fix_trades_csv)
```

Arquivos comparados: `data/citadel/{run}/reports/trades.csv`.

Se digests diferem → fix não entra, independente do speedup. Sem
exceção para H7 e H8.

Para H9 (hmmlearn) que pode convergir diferente: se ledger diverge
mas por ≤1 trade ou ≤0.5% PnL → registrar como "falha numérica
esperada" e arquivar sem tentar ajustar convergência.

### Regressão zero

- `pytest tests/ -q` verde após cada fix
- `python smoke_test.py --quiet` mantém 178/178
- Novo: `tests/perf/test_hmm_ledger_invariant.py` — roda CITADEL mini
  (7 dias, 1 símbolo) e verifica digest estável contra fixture
  `tests/fixtures/citadel_mini_baseline.csv`

### Regra de parada honra

- **2 hipóteses consecutivas falham no gate de 10%** → ciclo para
  imediatamente. Sem "tentar H_next por desespero". Documentar no
  report final.
- **Hipótese mata trade-ledger** → fix revertido + hipótese arquivada
  + próxima hipótese considerada normalmente (não conta como falha
  consecutiva).

---

## Ordem de execução

| # | Etapa | Budget | Ação | Gate |
|---|---|---:|---|---|
| 0 | Setup | 30 min | Criar branch, gravar 3 runs baseline, fixtures | n/a |
| 1 | Diagnóstico H7 | 15 min | Contador temporário + run 180d | ≤11 calls → arquiva |
| 2 | Diagnóstico H9 | 10 min | `pip install hmmlearn` + run de ledger | Falha pip → arquiva; ledger diverge → arquiva |
| 3 | H8 impl | 45 min | Microbench + code + 3 runs + ledger diff | ≥10% + ledger digest ok |
| 4 | H7 impl (se viva) | 30 min | lru_cache wrapper + 3 runs + ledger diff | ≥10% + ledger digest ok |
| 5 | Consolidação | 20 min | Ganho ≥25%? Suite verde? Report + session log | n/a |

**Budget total estimado:** 2h30 se tudo roda. ~1h30 se H7 e H9 morrem
nos diagnósticos (cenário provável).

---

## Escopo e boundaries

### Escopo do código

- `core/chronos.py` — `GaussianHMMNp._forward`, `GaussianHMMNp._backward`,
  `_build_hmm_backend`, `enrich_with_regime`
- Novo (condicional): `core/_hmm_cache.py` se H7 viva e inline >40 LoC
- Testes: `tests/core/test_chronos_hmm.py` (reforço numérico),
  `tests/perf/test_hmm_ledger_invariant.py` (novo)
- `requirements.txt` — `hmmlearn` como optional se H9 viva

### Fora do escopo (explícito)

- `core/indicators.py`, `core/signals.py`, `core/portfolio.py`,
  `config/params.py` — CORE PROTEGIDO, zero linhas
- Restruturar `_forward`/`_backward` além da substituição de
  `logsumexp` (H10 parkada)
- Cython, numba, GPU, polars
- Outras funções de `chronos.py` (GARCH, Hurst, seasonality) mesmo que
  apareçam no profile
- Paralelização inter-símbolo dentro de um engine (outro ciclo)

---

## Riscos e mitigações

| Risco | Probabilidade | Mitigação |
|---|---|---|
| H8 quebra trade-ledger por precisão float | Médio | Invariante B é trava absoluta — revert imediato + arquiva H8 |
| H9 hmmlearn instala mas trava em outra parte do código | Baixo | Isolado ao fit; se falha, `pip uninstall hmmlearn` |
| Diagnóstico H7 demora >15 min | Baixo | Instrumentação é 3 linhas; cap hard em 30 min, senão arquiva H7 sem testar |
| Ciclo inteiro <25% mesmo com H8+H9 | Médio | Registrar como "insuficiente" mas manter fixes individuais que passaram gate de 10% |
| 2 falhas consecutivas disparam stop rule antes de chegar em H7 | Possível | Aceita. Disciplina > completude |
| 3×47s runs por gate somam muito | Baixo | ~8 checks × 2.5 min = 20 min em medição pura, aceitável |

---

## Artefatos gerados

- `data/perf_profile/2026-04-19/{baseline,post_h8,post_h9,post_h7}_citadel_180d.json`
- `data/perf_profile/2026-04-19/hmm_fit_microbench.txt`
- `data/perf_profile/2026-04-19/logsumexp_microbench.txt`
- `tests/fixtures/citadel_mini_baseline.csv` (digest-lock)
- `docs/audits/2026-04-19_lane_2b_hmm_speedup.md` (report final)

---

## Integração e handoff

- Branch `feat/lane-2b-hmm` isolada; merge back pra `feat/phi-engine`
  no fim do ciclo
- Session log em `docs/sessions/2026-04-19_HHMM.md` conforme regra
  permanente (CLAUDE.md)
- Daily log atualizado em `docs/days/2026-04-19.md`
- Zero impacto em Lane 1 (já merged) e Lane 3 (não iniciada)
- Zero linhas em CORE PROTEGIDO

---

## Critério de fechamento

Ciclo termina em 1 dos 3 estados:

1. **Sucesso:** ganho ≥25%, trade-ledger bit-idêntico, suite verde →
   merge pra `feat/phi-engine` + report celebratório
2. **Sucesso parcial:** ganho entre 10% e 25%, ledger ok, suite verde
   → merge com caveat documentado ("insuficiente pela barra mas fica
   pelo ganho individual")
3. **Falha honra:** ganho <10% ou todas hipóteses morrem nos
   diagnósticos → revert de código (manter docs + diagnósticos) +
   report de falha honesta + hipótese nova parkada pra ciclo futuro

Em nenhum caso: iterar hipótese nova não-pré-registrada dentro deste
ciclo. É fishing.
