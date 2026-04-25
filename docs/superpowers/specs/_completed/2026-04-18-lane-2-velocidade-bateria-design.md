# Lane 2 — Velocidade (Bateria/Walk-forward) — Design

**Data:** 2026-04-18
**Branch de origem:** `feat/phi-engine`
**Escopo:** reduzir wall-time de batteries, walk-forward e OOS revalidation
sem alterar resultado numérico de backtest.
**Motivação:** usuário sente dor no ciclo de iteração — bateria/OOS tomam
muito tempo. ThreadPool existe mas provavelmente não ajuda em trabalho
CPU-bound (GIL). Nenhum profile foi rodado — "mais rápido" sem número é
fishing.

**Princípio-guia:** profile-first obrigatório. Só fixes validados por dados
reais. Regra de parada honra: hipótese não aparece no profile → arquiva.

---

## Fase A — Profile (obrigatório antes de qualquer fix)

### Cenários canônicos

| # | Cenário | Comando base | Target de medição |
|---|---------|--------------|-------------------|
| 1 | Battery padrão | `tools/batteries/longrun_battery.py` com params default | Wall-time total + top funções |
| 2 | Walk-forward single | 1 engine (CITADEL) × universo completo × janela 6m | Inner-loop por engine/symbol |
| 3 | OOS revalidate | `tools/audits/oos_revalidate.py` com 3 engines | Overhead de agregação |

### Ferramenta
`pyinstrument` — amostragem baixa-intrusão, saída HTML flamegraph.
Instalar temporariamente; não precisa virar dependência permanente.

### Outputs
`data/perf_profile/2026-04-18/`:
- `{cenario}.pyinstrument.html` — flamegraph interativo
- `{cenario}_summary.md` — top-20 funções por wall-time, breakdown CPU vs I/O, CPU utilization média

Relatório consolidado em `docs/audits/2026-04-18_battery_perf_profile.md`:
- Tempos baseline por cenário
- Top gargalos identificados
- Mapeamento gargalo → hipótese pré-registrada
- Veredito por hipótese (confirmar / arquivar)

---

## Fase B — Hipóteses pré-registradas

**Registrar ANTES de ver o profile** — anti-overfit do método. Se aparecer
um gargalo não antecipado, anotar mas não atacar no mesmo ciclo (fishing).

| # | Hipótese | Sinal esperado | Fix proposto | Risco |
|---|----------|---------------|--------------|-------|
| H1 | GIL bottleneck em ThreadPool CPU-bound | `threading.Lock.acquire` alto; CPU total < 100% × ncores; tempo wall ≫ soma CPU | `ProcessPoolExecutor` em batteries | Médio (Windows pickle) |
| H2 | Recompute de indicadores idênticos por param combo | `indicators`, `atr`, `bollinger`, `ema`, `swing_structure` no top-10 | `@lru_cache` em wrappers puros + cache em-memória por processo | Baixo |
| H3 | Cache OHLCV miss frequente | `cache.read` retornando None; `fetch` indo pra API | Estender prefetch; validar coverage de janela | Baixo |
| H4 | I/O CSV/JSON serializando no inner loop | `to_csv`, `to_json`, `DataFrame.to_dict` no topo | Bufferizar; 1 write final por engine run | Baixo |
| H5 | pandas groupby/apply não-vetorizado | `Groupby.apply`, `frame_apply` no top-5 | Converter pra vectorizado/numpy | Médio |
| H6 | Deep copies de DataFrames | `DataFrame.copy`, `NDFrame.__finalize__` alto | Views onde não há escrita | Baixo |

**Regra:** hipótese cujo sinal não aparece no top-20 do flamegraph é arquivada sem
implementação. Sem exceção.

---

## Fase C — Fixes (só para hipóteses validadas)

### Ordem de ataque (ganho esperado × risco)

1. **H1 — ProcessPool** (se validada): maior ganho esperado em batteries que rodam
   N engine configs em paralelo. Requer guardas Windows-safe (`if __name__ ==
   "__main__"`), funções de worker picklable, e atenção a módulos com singletons
   (logger, cache). Benchmark pré/pós.

2. **H2 — Indicator cache**: wrapper puro com `@functools.lru_cache(maxsize=256)`
   em funções determinísticas de indicadores. Novo módulo
   `core/signals/indicator_cache.py` (criado dentro da estrutura Lane 1.3).
   Chave: `(symbol, interval, indicator_name, params_hash)`. Escopo: em-memória
   por processo. Só memoiza se a função for pura.

3. **H4 — Buffer de I/O**: batchar writes em vez de escrita incremental por
   iteração. Escritor centralizado em `tools/_lib/` (futuro Lane 1.2b; por ora,
   inline no call-site da bateria).

4. **H3 — Cache coverage**: auditar janelas pedidas vs cobertas; se miss for
   estrutural (janela fora do range prefetched), estender prefetch script.

5. **H5, H6 — Pandas hot spots**: caso-a-caso, só no top do flamegraph. Sem
   refactor de pipeline inteiro.

### Disciplina por fix

Cada fix em commit atômico, seguido de re-medição do cenário onde a hipótese foi
validada. Critério de manutenção: **≥10% de ganho** nesse cenário. Se não bater,
`git revert` — não deixar complexidade sem payoff comprovado.

---

## Fase D — Cache novo

### Não tocar
- `core/cache.py` (OHLCV disk cache) — funciona.
- Cache de sentiment (Codex endureceu 2026-04-17) — não mexer.

### Novo: cache de indicadores em-memória
- Localização: `core/signals/indicator_cache.py`
  (na estrutura Lane 1.3; antes dela, `core/indicator_cache.py` com shim posterior).
- Escopo: uma instância por processo.
- Chave: tupla `(symbol, interval, indicator_name, params_hash)`.
- Invalidação: nenhuma. Chave é determinística pelos inputs.
- Regra forte: só memoiza funções puras. Função que pega `df` mutável
  ou lê clock externo é off-limits.

---

## Critérios de sucesso

### Wall-time
- Battery longrun 6m: **≥2× speedup** (alvo conservador)
- OOS revalidate 3 engines: **≥1.5× speedup**
- Walk-forward single engine: **≥1.3× speedup**

### Integridade numérica (critério duro)
- Digest SHA-256 do CSV final de cada cenário **bit-identical** ao baseline pré-Lane 2.
- Se qualquer fix mudar resultado numérico → bug → revert.

### Regressão zero
- `python smoke_test.py --quiet` 156/156 após cada fix.
- Nenhum teste novo falha.

---

## Fora de escopo (explicitamente)

- Cython / numba (backlog futuro).
- GPU (irrelevante pra carga atual).
- Reescrita de pipeline em polars / duckdb (Lane 2b futura).
- Otimização do launcher cold-start (pode virar bônus se profile mostrar
  imports pesados; sem compromisso neste design).
- Reescrita dos batteries como framework comum (Lane 1.2b; este design
  não depende disso).

---

## Integração com Lane 1

Lane 2 executa **após** Lane 1 ou **em paralelo**, conforme preferência.

Preferência: Lane 1.3 (core/ + shims) antes da Lane 2 Fase D — o cache de
indicadores já nasce em `core/signals/indicator_cache.py`, sem shim extra.

Nada em Lane 2 toca lógica de indicadores, sinais, portfolio, ou params
protegidos. É envolvente (wrapper memoizado), não invasivo.
