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
| **H1** | GIL em ThreadPool CPU-bound | CPU total < 100% × ncores; wall ≫ CPU total agregado | CITADEL standalone a 82% CPU — mas o orquestrador da battery **já dispara subprocess** por engine (ThreadPool só faz wait). ~~ProcessPool traria paralelismo~~ **Correção:** paralelismo já acontece no nível correto (subprocess-per-engine). Ver ERRATA abaixo. | **NÃO SE APLICA AO ALVO** |
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

## ERRATA — H1 mal-interpretada (2026-04-18, pós-leitura do código)

**A primeira versão deste report concluía "H1 CONFIRMAR → ProcessPool em
batteries". Isso estava errado.** Correção após ler
`tools/batteries/longrun_battery.py:67`:

- O orquestrador da battery dispara cada engine como
  `subprocess.call(cmd, ...)` — cada engine já roda em processo Python
  separado.
- O `ThreadPoolExecutor` em `longrun_battery.py:163` só orquestra o
  dispatch — cada thread fica esperando o subprocess terminar (não faz
  trabalho CPU-bound).
- Threads aqui **não estão contestando GIL**. O trabalho CPU-bound está
  dentro de cada subprocess de engine, isolado pelo próprio OS.
- Converter pra `ProcessPoolExecutor` seria overhead inútil: processo-mãe
  spawnaria processo que spawnaria outro processo.

**O 82% CPU que o profile mostrou era do CITADEL standalone
(`python -m engines.citadel --days 180`), não do orquestrador.** Isso
significa que a paralelização já acontece no nível correto (subprocess),
e os ganhos reais de speedup estão **dentro** de cada engine — não na
orquestração.

**H1 como originalmente formulada não se aplica ao alvo correto.**

## Fase C — Reavaliada

Nenhuma das 6 hipóteses pré-registradas tem fix acionável com o profile
que temos:

- H1: orquestrador já faz paralelização correta via subprocess
- H2: bloqueado por CORE PROTECTED (`swing_structure` em `core/indicators.py`)
- H3, H4, H5, H6: arquivadas — sinais ausentes no top-20

**Próximo passo honra:** ciclo novo de pre-registro dedicado às hipóteses
intra-engine (H7/H8 do bloco anterior), com profile específico pra cada:

- Contar quantas vezes `enrich_with_regime` é chamado numa run CITADEL
  180d — se for 1× por símbolo (= 11 calls), cache tem pouco retorno
- Profile do `GaussianHMMNp.fit` isolado pra ver se `logsumexp` é
  substituível por implementação local
- Só registrar H7/H8 oficialmente quando houver mecanismo defensável +
  mediçao de quantas chamadas redundantes existem

**Não executar nada de Fase C neste ciclo.** Parar com honestidade: a
bateria pré-registrada falhou, e pular direto pra nova hipótese sem
pre-registro é fishing.

## Invariante pós-fix

Toda mudança de Fase C precisa:
- Reproduzir digests SHA-256 idênticos em saídas JSON/CSV dos engines pra mesmas entradas
- Suite `pytest` verde
- Smoke test 178/178
- Backtest CITADEL 180d: número de trades + PnL exatamente iguais

## Estado (pós-errata)

- Fase A: **COMPLETA**
- Fase B (hipóteses): **todas arquivadas** — H1 não se aplicava ao alvo
  correto (orquestrador já usa subprocess), H2 bloqueado por CORE
  protegido, H3-H6 sem sinal. H7/H8 registradas como ideias mas sem
  pre-registro formal ainda.
- Fase C: **não executada.** Bateria pré-registrada falhou honestamente.
  Novo ciclo precisa ser aberto com pre-registro dedicado pra H7/H8
  quando for o caso.

## Arquivos gerados

- `data/perf_profile/2026-04-18/battery.html` (121 KB — orchestrator overhead, baixo sinal)
- `data/perf_profile/2026-04-18/walkforward_citadel.html` (13.9 MB — flamegraph rico)
- `data/perf_profile/2026-04-18/walkforward_citadel.txt` (text view, usado neste report)
- `data/perf_profile/2026-04-18/oos_revalidate.txt` (agregação negligível)
