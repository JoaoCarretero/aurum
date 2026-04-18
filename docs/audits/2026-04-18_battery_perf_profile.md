# Lane 2 Fase A — Battery Performance Profile (2026-04-18)

## Método

pyinstrument 5.1.2, 3 cenários canônicos. Hipóteses pré-registradas em
`docs/superpowers/specs/2026-04-18-lane-2-velocidade-bateria-design.md`
**antes** de rodar o profile (anti-overfit do método). Hipótese que não
aparece no top-20 do flamegraph é **arquivada sem fix**.

Artefatos: `data/perf_profile/2026-04-18/`.

## Baselines

| Cenário | Comando | Wall | CPU | Observação |
|---|---|---:|---:|---|
| Battery smoke | `tools.batteries.longrun_battery --smoke` (30d, citadel only) | ~30s | n/a | Orchestrator dispatch em subprocess. Profile vê pouco (overhead do launcher é trivial). |
| Walkforward CITADEL 180d | `engines.citadel --days 180 --no-menu` | **47.2s** | 38.6s | **82% CPU-bound**. Profile rico. |
| OOS revalidate (skip-runs) | `tools.audits.oos_revalidate --engines citadel jump renaissance --skip-runs` | **0.056s** | 0.047s | Agregação é negligível. Tempo real está em rerodar engines (subprocess), não em agregar. |

## Top gargalos — walkforward CITADEL 180d (47.2s wall)

| Função | Tempo | % wall | Local | Natureza |
|---|---:|---:|---|---|
| `GaussianHMMNp.fit` | 20.156s | **43%** | `core/chronos.py:174` | HMM re-fit por chamada de `enrich_with_regime` |
| ├─ `_forward` → `scipy logsumexp` | 10.173s | 22% | chronos + scipy | Inner loop do EM |
| └─ `_backward` → `scipy logsumexp` | 9.782s | 21% | chronos + scipy | Inner loop do EM |
| `swing_structure` | 7.664s | 16% | `core/indicators.py:65` | ⚠️ CORE PROTEGIDO |
| `fetch_all` (via `as_completed`) | 7.047s | 15% | `core/data/base.py:94` | Parallel fetch — I/O + threading |
| `_iLocIndexer.__getitem__` | 2.473s | 5% | pandas | Consumo em `scan_symbol` loop |
| `scan_symbol` self | 1.463s | 3% | `engines/citadel.py` | Loop body overhead |

**Pai dominante:** `scan_symbol` agrega 35.8s (76%) — dos quais 21.7s (46%) é `enrich_with_regime`.

## Mapeamento hipótese → gargalo

| # | Hipótese | Sinal esperado | Observado no top-20 | Veredito |
|---|---|---|---|---|
| **H1** | GIL em ThreadPool CPU-bound | CPU total < 100% × ncores; wall ≫ CPU total agregado | Single-process a 82% CPU. Battery multi-engine dispatcha N subprocesses sequenciais por `--parallel` default. ProcessPool traria paralelismo real entre configs. | **CONFIRMAR** |
| **H2** | Recompute de indicadores idênticos | `indicators`, `atr`, `bollinger`, `ema`, `swing_structure` no top-10 | `swing_structure` em 16% — mas CORE PROTEGIDO. `indicators()` fora do top-10. | **PARCIAL — bloqueado em CORE** |
| **H3** | Cache OHLCV miss frequente | `cache.read` retornando None; `fetch` indo pra API | `fetch_all` = 15% via `as_completed` + threading. Sinal fraco. Não é cache miss puro. | **ARQUIVAR** |
| **H4** | I/O CSV/JSON no inner loop | `to_csv`, `to_json`, `DataFrame.to_dict` no top-10 | Nenhum destes no top-20. | **ARQUIVAR** |
| **H5** | pandas groupby/apply não-vetorizado | `Groupby.apply`, `frame_apply` no top-5 | Não no top-20 (nem groupby nem apply aparecem). `swing_structure` tem loop pandas mas é CORE. | **ARQUIVAR** |
| **H6** | Deep copies de DataFrames | `DataFrame.copy`, `NDFrame.__finalize__` alto | Não no top-20. | **ARQUIVAR** |

## Gargalo não antecipado (anti-overfit — registrar, não atacar neste ciclo)

**HMM fitting (`GaussianHMMNp.fit` em `core/chronos.py:174`) = 43% do wall-time.**

- `enrich_with_regime` é chamado por `scan_symbol` e refit o HMM a cada chamada.
- `_forward` + `_backward` do EM dominam (~20s combinados), puxados por `scipy.special.logsumexp`.
- Não estava nas 6 hipóteses pré-registradas.
- **Per protocolo: registrar sem atacar.** Hipótese nova pra ciclo futuro:
  - **H7 (proposta, não validada ainda):** `@lru_cache` / memoization em `fit()` por (dados.hash, n_states, seed). Risco: estado aleatório — garantir bit-identidade ou trocar por seed fixo.
  - **H8 (proposta):** substituir `scipy.special.logsumexp` por implementação vetorizada local (2 chamadas × N iterações EM × N amostras = muita ida ao scipy).

Ambas ficam arquivadas neste ciclo. Nova bateria Fase B-bis dedicada ao HMM se hipótese precisar ser testada — **só após fechar H1.**

## Fase C — Ordem de ataque validada

1. **H1 — ProcessPool em batteries** (confirmado): maior ganho esperado quando rodando N engines/configs em paralelo. Battery com `--parallel > 1` hoje usa threads (sujeito ao GIL). Converter pra `ProcessPoolExecutor`.
   - Target: ≥2× speedup em `longrun_battery --parallel 5` quando N engines ≥ 3.
   - Risco: Windows pickle, guards `if __name__ == "__main__"`, module singletons (logger, cache).
   - Critério de manutenção: ≥10% speedup end-to-end.

2. **(arquivado neste ciclo)** H2/H3/H4/H5/H6 — sinais fracos ou inexistentes no profile.

3. **(próximo ciclo)** H7/H8 — HMM fit cache/otimização. Só se H1 não der o ganho necessário.

## Invariante pós-fix

Toda mudança de Fase C precisa:
- Reproduzir digests SHA-256 idênticos em saídas JSON/CSV dos engines pra mesmas entradas
- Suite `pytest` verde
- Smoke test 178/178
- Backtest CITADEL 180d: número de trades + PnL exatamente iguais

## Estado

- Fase A: **COMPLETA**
- Fase B (hipóteses): **validada (H1)** + **arquivada (H2-H6)** + **2 novas propostas (H7, H8) registradas mas não atacadas**
- Fase C: **pronta pra H1 (ProcessPool)**

## Arquivos gerados

- `data/perf_profile/2026-04-18/battery.html` (121 KB — orchestrator overhead, baixo sinal)
- `data/perf_profile/2026-04-18/walkforward_citadel.html` (13.9 MB — flamegraph rico)
- `data/perf_profile/2026-04-18/walkforward_citadel.txt` (text view, usado neste report)
- `data/perf_profile/2026-04-18/oos_revalidate.txt` (agregação negligível)
