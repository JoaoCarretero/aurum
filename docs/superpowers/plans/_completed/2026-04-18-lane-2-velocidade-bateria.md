# Lane 2 — Velocidade (Bateria/Walk-forward) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduzir wall-time de batteries, walk-forward e OOS revalidation, com garantia de bit-identidade de resultados.

**Architecture:** Profile-first obrigatório com `pyinstrument`. 6 hipóteses pré-registradas; só hipóteses validadas viram fix. Cada fix em commit atômico com critério de manutenção ≥10% speedup.

**Tech Stack:** Python 3.14, pandas, pyinstrument (transient), concurrent.futures, functools.lru_cache.

**Spec:** `docs/superpowers/specs/2026-04-18-lane-2-velocidade-bateria-design.md`

---

## Phase 0 — Baseline e pré-registro

### Task 0.1: Capturar baseline de wall-time e digests

**Files:**
- Create: `data/perf_profile/2026-04-18/baseline.json`

- [ ] **Step 1: Instalar pyinstrument (transient)**

Run: `python -m pip install pyinstrument`
Expected: install sem erro. Confirmar: `python -c "import pyinstrument; print(pyinstrument.__version__)"`.

- [ ] **Step 2: Medir battery padrão**

Run:
```bash
mkdir -p data/perf_profile/2026-04-18
python -m pyinstrument -r html -o data/perf_profile/2026-04-18/battery.html \
  -m tools.batteries.longrun_battery --help
# (substituir --help pela invocação real curta da bateria; alvo 3-5 min típico)
```

Também medir apenas wall-time (sem overhead do profiler):
```bash
time python -m tools.batteries.longrun_battery --symbols BNBUSDT --days 90 2>&1 | tee data/perf_profile/2026-04-18/battery_wallclock.txt
```
Registrar o `real=<X>m<Y>s`.

- [ ] **Step 3: Medir walk-forward single engine**

```bash
python -m pyinstrument -r html -o data/perf_profile/2026-04-18/walkforward_citadel.html \
  -c "from engines.citadel import run_backtest; run_backtest(days=180)"
time python -c "from engines.citadel import run_backtest; run_backtest(days=180)" 2>&1 | tee data/perf_profile/2026-04-18/walkforward_wallclock.txt
```

- [ ] **Step 4: Medir OOS revalidate**

```bash
python -m pyinstrument -r html -o data/perf_profile/2026-04-18/oos_revalidate.html \
  -m tools.audits.oos_revalidate --engines citadel,jump,renaissance --quick
time python -m tools.audits.oos_revalidate --engines citadel,jump,renaissance --quick 2>&1 | tee data/perf_profile/2026-04-18/oos_wallclock.txt
```
(Ajustar flags conforme CLI real do script; se `--quick` não existir, usar configuração mínima.)

- [ ] **Step 5: Gerar digests dos outputs de backtest**

```bash
python -c "
import hashlib, glob
for csv in sorted(glob.glob('data/*/*.csv'))[-10:]:
    with open(csv, 'rb') as fh:
        print(csv, hashlib.sha256(fh.read()).hexdigest()[:16])
" > data/perf_profile/2026-04-18/digests_baseline.txt
```
Registrar arquivos que apareceram e seus digests.

- [ ] **Step 6: Escrever `baseline.json`**

Write `data/perf_profile/2026-04-18/baseline.json`:
```json
{
  "date": "2026-04-18",
  "scenarios": {
    "battery": {"wallclock_seconds": "<do Step 2>", "profile": "battery.html"},
    "walkforward_citadel": {"wallclock_seconds": "<do Step 3>", "profile": "walkforward_citadel.html"},
    "oos_revalidate": {"wallclock_seconds": "<do Step 4>", "profile": "oos_revalidate.html"}
  },
  "digests_file": "digests_baseline.txt"
}
```

- [ ] **Step 7: Commit baseline**

```bash
git add data/perf_profile/2026-04-18/
git commit -m "chore(lane2): baseline de wall-time e digests pre-otimizacao"
```

### Task 0.2: Pré-registrar hipóteses

**Files:**
- Create: `docs/audits/2026-04-18_battery_perf_hypotheses.md`

- [ ] **Step 1: Escrever pré-registro das hipóteses**

Write `docs/audits/2026-04-18_battery_perf_hypotheses.md`:
```markdown
# Lane 2 — Hipóteses de Performance (pré-registro)

Pré-registrado em 2026-04-18 antes de ler qualquer profile.

| # | Hipótese | Sinal no profile | Fix | Validada? |
|---|----------|-------------------|-----|-----------|
| H1 | GIL bottleneck em ThreadPool CPU-bound | threading.Lock.acquire alto + CPU total < 100%*ncores | ProcessPool em batteries | TBD |
| H2 | Recompute de indicadores | atr/bollinger/ema/swing_structure no top-10 | lru_cache em wrapper puro | TBD |
| H3 | Cache OHLCV miss | cache.read None + fetch indo pra API | Estender prefetch | TBD |
| H4 | I/O no inner loop | to_csv/to_json/to_dict no topo | Buffer de writes | TBD |
| H5 | groupby/apply não-vetorizado | Groupby.apply no top-5 | Converter pra vectorized | TBD |
| H6 | Deep copies | DataFrame.copy alto | Views onde sem escrita | TBD |

Regra: hipótese não validada pelo profile → arquivada, sem tentativa de fix.
```

- [ ] **Step 2: Commit**

```bash
git add docs/audits/2026-04-18_battery_perf_hypotheses.md
git commit -m "docs(lane2): pre-registro de hipoteses de performance"
```

---

## Phase 1 — Análise dos profiles

### Task 1.1: Analisar flamegraph da battery

**Files:**
- Modify: `docs/audits/2026-04-18_battery_perf_hypotheses.md` — preencher coluna "Validada?"

- [ ] **Step 1: Abrir `data/perf_profile/2026-04-18/battery.html`**

Abrir manualmente no browser. Identificar top-20 funções por wall-time.

- [ ] **Step 2: Extrair top-20 em texto pra análise reproducível**

```bash
python -m pyinstrument -r text -o data/perf_profile/2026-04-18/battery_top.txt \
  --load data/perf_profile/2026-04-18/battery.pyisession 2>/dev/null || \
  echo "fallback: inspecionar HTML manualmente"
```
(Se `--load` não estiver disponível na versão instalada, documentar top-20 do HTML manualmente num `.txt`.)

- [ ] **Step 3: Checar sinais das 6 hipóteses contra o top-20**

Para cada hipótese, procurar o sinal descrito:
- H1: soma de `threading.Lock.acquire` nas stacks >5% do tempo + CPU utilization < 100%*ncores? → sim/não
- H2: funções de indicadores aparecem múltiplas vezes? → sim/não
- H3: `core.cache.read` devolvendo None observável no log? → sim/não
- H4: `to_csv`/`to_json`/`to_dict` >2% no flamegraph? → sim/não
- H5: `Groupby.apply` ou `frame_apply` no top-5? → sim/não
- H6: `DataFrame.copy` >3% do tempo? → sim/não

- [ ] **Step 4: Atualizar arquivo de hipóteses**

Edit `docs/audits/2026-04-18_battery_perf_hypotheses.md`: substituir "TBD" por "Sim (N% wall-time)" ou "Não (não aparece)" para cada.

- [ ] **Step 5: Commit análise**

```bash
git add docs/audits/2026-04-18_battery_perf_hypotheses.md
git commit -m "docs(lane2): analise de profile battery — validacao de hipoteses"
```

### Task 1.2: Analisar walk-forward e OOS

- [ ] **Step 1: Repetir procedimento da Task 1.1 pra `walkforward_citadel.html` e `oos_revalidate.html`**

- [ ] **Step 2: Adicionar secção no mesmo documento com validação por cenário**

Expected: tabela por cenário mostrando quais hipóteses doíam onde.

- [ ] **Step 3: Escrever veredito consolidado**

Append em `docs/audits/2026-04-18_battery_perf_hypotheses.md`:
```markdown
## Veredito

- Hipóteses validadas (fix autorizado): H<N>, H<M>
- Hipóteses arquivadas (sem sinal no profile): H<X>, H<Y>
- Gargalo inesperado observado: <descrição se houver>
```

- [ ] **Step 4: Commit veredito**

```bash
git add docs/audits/2026-04-18_battery_perf_hypotheses.md
git commit -m "docs(lane2): veredito de hipoteses por cenario"
```

---

## Phase 2 — Fixes condicionais (executar só as tasks cujas hipóteses foram validadas)

### Task 2.1 (H1): Trocar ThreadPool → ProcessPool onde CPU-bound

**Condição de execução:** H1 validada na Phase 1.

**Files:**
- Modify: `tools/batteries/longrun_battery.py` (ou `tools/longrun_battery.py` se Lane 1.2 não executou ainda)
- Modify: outras batteries onde o perfil mostrar GIL

- [ ] **Step 1: Write failing benchmark test**

Create `tests/integration/test_battery_perf_processpool.py`:
```python
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.perf


def test_battery_runs_under_baseline(tmp_path):
    """Battery wall-time < 0.6 * baseline (alvo: ≥ 1.67× speedup para aprovar)."""
    from tools.batteries import longrun_battery

    # Baseline em segundos vem de data/perf_profile/2026-04-18/baseline.json
    baseline = 120.0  # substituir pelo valor real do baseline.json
    max_allowed = baseline * 0.6

    t0 = time.perf_counter()
    longrun_battery.run(symbols=["BNBUSDT"], days=90, out=tmp_path)
    elapsed = time.perf_counter() - t0

    assert elapsed < max_allowed, f"{elapsed:.1f}s >= {max_allowed:.1f}s (speedup insuficiente)"
```

- [ ] **Step 2: Run test to confirm baseline fails**

Run: `pytest tests/integration/test_battery_perf_processpool.py -v`
Expected: FAIL (performance atual é baseline, não passa ainda).

- [ ] **Step 3: Implement ProcessPool swap**

Edit `tools/batteries/longrun_battery.py` — localizar `ThreadPoolExecutor` e trocar por `ProcessPoolExecutor`:
```python
# antes
from concurrent.futures import ThreadPoolExecutor, as_completed
# ...
with ThreadPoolExecutor(max_workers=workers) as ex:

# depois
from concurrent.futures import ProcessPoolExecutor, as_completed
# ...
if __name__ == "__main__":  # Windows-safe guard no módulo
    ...
with ProcessPoolExecutor(max_workers=workers) as ex:
```

Atenção:
- Adicionar `if __name__ == "__main__":` guard no entry-point do módulo (Windows exige).
- Garantir que funções passadas pro executor são picklable (não usar closures).
- Se a bateria depende de estado global (ex: logger configurado), mover init do logger pra dentro do worker.

- [ ] **Step 4: Run perf test**

Run: `pytest tests/integration/test_battery_perf_processpool.py -v`
Expected: PASS.

- [ ] **Step 5: Re-rodar cenário completo e comparar digest**

```bash
python -m tools.batteries.longrun_battery --symbols BNBUSDT --days 90 --out /tmp/post_h1/
python -c "
import hashlib
for csv in sorted(__import__('glob').glob('/tmp/post_h1/*.csv')):
    with open(csv,'rb') as fh:
        print(csv, hashlib.sha256(fh.read()).hexdigest()[:16])
"
```
Comparar com `data/perf_profile/2026-04-18/digests_baseline.txt`.
Expected: digests **idênticos**. Se divergir → bug → revert e investigar.

- [ ] **Step 6: Medir speedup real**

```bash
time python -m tools.batteries.longrun_battery --symbols BNBUSDT --days 90 --out /tmp/post_h1_time/
```
Comparar com baseline. Se < 10% speedup → revert (não mantém complexidade sem payoff).

- [ ] **Step 7: Commit se speedup ≥ 10% e digest bate**

```bash
git add tools/batteries/longrun_battery.py tests/integration/test_battery_perf_processpool.py
git commit -m "perf(battery): ProcessPool em longrun_battery (H1, X% speedup, digest match)"
```

### Task 2.2 (H2): Cache de indicadores

**Condição de execução:** H2 validada.

**Files:**
- Create: `core/signals/indicator_cache.py` (ou `core/indicator_cache.py` se Lane 1.3 não executou ainda)
- Modify: consumers em `engines/` que chamam indicadores repetidamente

- [ ] **Step 1: Write failing test**

Create `tests/core/test_indicator_cache.py`:
```python
import pandas as pd
import pytest

from core.signals.indicator_cache import cached_atr


def _sample_frame():
    return pd.DataFrame({
        "high": [1.0, 1.2, 1.1, 1.3, 1.5],
        "low":  [0.9, 1.0, 0.95, 1.1, 1.2],
        "close":[1.0, 1.1, 1.05, 1.2, 1.4],
    })


def test_cache_hit_returns_identical_result():
    df = _sample_frame()
    key = ("TEST", "1h", "atr", 14)

    r1 = cached_atr(df, length=14, key=key)
    r2 = cached_atr(df, length=14, key=key)

    pd.testing.assert_series_equal(r1, r2)


def test_cache_miss_on_different_key():
    df = _sample_frame()
    r1 = cached_atr(df, length=14, key=("A", "1h", "atr", 14))
    r2 = cached_atr(df, length=14, key=("B", "1h", "atr", 14))
    # Mesmos valores numéricos mas objetos distintos (miss no cache)
    pd.testing.assert_series_equal(r1, r2)
```

- [ ] **Step 2: Run test to confirm fail**

Run: `pytest tests/core/test_indicator_cache.py -v`
Expected: FAIL — ImportError.

- [ ] **Step 3: Implement cache module**

Create `core/signals/indicator_cache.py`:
```python
"""In-memory cache for deterministic indicator computations.

Key is an explicit tuple passed by the caller. Values are pandas Series
or DataFrames. Scope: per-process. No eviction of correctness concerns —
the key IS the determinism contract.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Tuple

import pandas as pd

from core.signals.indicators import atr as _atr_impl


_CACHE: dict = {}


def cached_atr(df: pd.DataFrame, length: int, key: Tuple) -> pd.Series:
    """ATR memoizado por chave explícita.

    A chave deve ser fornecida pelo caller (ex: (symbol, interval, "atr", length)).
    Se o caller errar a chave, o cache miss é correto mas performance cai.
    Nunca usar sem chave explícita.
    """
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    result = _atr_impl(df, length=length)
    _CACHE[key] = result
    return result


def clear() -> None:
    """Limpar cache — para testes e isolamento entre batteries."""
    _CACHE.clear()
```

- [ ] **Step 4: Run test to verify PASS**

Run: `pytest tests/core/test_indicator_cache.py -v`
Expected: PASS.

- [ ] **Step 5: Adotar cache em um battery onde H2 apareceu**

Identificar o hot call no profile. Exemplo: `engines/citadel.py` chama `atr(df, 14)` N vezes.

Edit call-site:
```python
# antes
from core.signals.indicators import atr
# ...
stop_atr = atr(df, 14)

# depois
from core.signals.indicator_cache import cached_atr
# ...
stop_atr = cached_atr(df, length=14, key=(symbol, interval, "atr", 14))
```

⚠️ Só trocar em call-sites **não-protegidos**. Dentro de `core/signals/` (protegido) não mexer.

- [ ] **Step 6: Re-medir cenário**

```bash
time python -m tools.batteries.longrun_battery --symbols BNBUSDT --days 90 --out /tmp/post_h2/
python -c "
import hashlib, glob
for csv in sorted(glob.glob('/tmp/post_h2/*.csv')):
    print(csv, hashlib.sha256(open(csv,'rb').read()).hexdigest()[:16])
"
```
Comparar speedup + digest.

- [ ] **Step 7: Commit se speedup ≥ 10% e digest bate**

```bash
git add core/signals/indicator_cache.py tests/core/test_indicator_cache.py engines/<engine-alterado>.py
git commit -m "perf(indicators): cache em-memoria de ATR (H2, X% speedup, digest match)"
```

### Task 2.3 (H3): Estender prefetch se coverage falhou

**Condição:** H3 validada (cache miss no profile).

**Files:**
- Modify: `tools/capture/prefetch.py` (ou `tools/prefetch.py`)

- [ ] **Step 1: Identificar janela que faltou**

Do profile, extrair símbolo + intervalo + range das requisições que caíram em API.

- [ ] **Step 2: Estender prefetch pra cobrir janela**

Editar `tools/capture/prefetch.py` para incluir range mais amplo (ex: `--days 400` em vez de `--days 365`).

- [ ] **Step 3: Rodar prefetch + re-rodar cenário**

```bash
python -m tools.capture.prefetch --days 400
time python -m tools.batteries.longrun_battery --symbols BNBUSDT --days 90 --out /tmp/post_h3/
```

- [ ] **Step 4: Commit**

```bash
git add tools/capture/prefetch.py
git commit -m "perf(prefetch): estender cobertura para eliminar miss no cache (H3)"
```

### Task 2.4 (H4): Buffer I/O

**Condição:** H4 validada.

**Files:**
- Modify: call-sites onde `to_csv`/`to_json` aparecem no inner loop

- [ ] **Step 1: Write failing perf test (opcional)**

Se quantificável, test de performance sobre o cenário menor.

- [ ] **Step 2: Identificar inner-loop writes**

Do profile, localizar arquivo + linha de cada `DataFrame.to_csv` recorrente.

- [ ] **Step 3: Refatorar pra buffer + 1 write final**

Exemplo:
```python
# antes
for row in iterator:
    result.to_csv(out_path, mode="a", header=False)

# depois
rows = []
for row in iterator:
    rows.append(row)
final = pd.concat(rows)
final.to_csv(out_path, index=False)
```

- [ ] **Step 4: Re-medir + digest check**

Mesmo protocolo das tasks anteriores.

- [ ] **Step 5: Commit**

```bash
git add <arquivos>
git commit -m "perf(io): buffer de writes em inner loop (H4, X% speedup, digest match)"
```

### Task 2.5 (H5): Vetorizar groupby/apply

**Condição:** H5 validada.

**Files:**
- Modify: call-site específico identificado no profile

- [ ] **Step 1: Identificar `groupby().apply(lambda)` no top do flamegraph**

Mapear arquivo + linha.

- [ ] **Step 2: Converter para operações vetorizadas**

Padrão:
```python
# antes
df.groupby("symbol").apply(lambda g: g["close"].pct_change().mean())

# depois (vetorizado)
df.sort_values("symbol")
pct = df.groupby("symbol")["close"].pct_change()
result = pct.groupby(df["symbol"]).mean()
```

- [ ] **Step 3: Test de igualdade numérica**

Escrever test comparando resultado antes/depois em sample pequeno.

- [ ] **Step 4: Re-medir + digest**

- [ ] **Step 5: Commit**

```bash
git commit -m "perf(pandas): vetorizar groupby em <local> (H5, X% speedup)"
```

### Task 2.6 (H6): Eliminar deep copies desnecessárias

**Condição:** H6 validada.

**Files:**
- Modify: call-sites com `DataFrame.copy()` no inner loop

- [ ] **Step 1: Identificar copies no top**

- [ ] **Step 2: Substituir copy por view onde sem escrita subsequente**

Atenção: pandas SettingWithCopyWarning — se a chamada subsequente escreve no df, **não remover copy**. Só em caminhos read-only.

- [ ] **Step 3: Re-medir + digest**

- [ ] **Step 4: Commit**

```bash
git commit -m "perf(pandas): eliminar copies em read-only paths (H6, X% speedup)"
```

---

## Phase 3 — Re-medição final e aceite

### Task 3.1: Bench final

**Files:**
- Create: `data/perf_profile/2026-04-18/final.json`

- [ ] **Step 1: Rodar os 3 cenários canônicos com wall-time**

Mesmos comandos da Task 0.1 Steps 2-4. Registrar tempos.

- [ ] **Step 2: Gerar digests finais**

Mesmo procedimento Step 5.

- [ ] **Step 3: Comparar digests com baseline**

```bash
diff data/perf_profile/2026-04-18/digests_baseline.txt <final_digests.txt>
```
Expected: sem diferença.

- [ ] **Step 4: Calcular speedup por cenário**

Write `data/perf_profile/2026-04-18/final.json`:
```json
{
  "speedups": {
    "battery": "<final/baseline>",
    "walkforward_citadel": "<final/baseline>",
    "oos_revalidate": "<final/baseline>"
  },
  "digests_match_baseline": true
}
```

- [ ] **Step 5: Validar critério de sucesso**

Speedups requeridos:
- Battery ≥ 2.0×
- OOS ≥ 1.5×
- Walk-forward ≥ 1.3×

Se algum não atingir, documentar em `docs/audits/2026-04-18_battery_perf_final.md` com explicação (ex: a hipótese não se confirmou ou o fix deu ganho menor que o esperado). **Não inflar métricas**.

- [ ] **Step 6: Commit**

```bash
git add data/perf_profile/2026-04-18/ docs/audits/2026-04-18_battery_perf_final.md
git commit -m "chore(lane2): bench final — speedups registrados, digests bit-identical"
```

### Task 3.2: Limpeza

- [ ] **Step 1: Remover pyinstrument das deps se foi install transient**

Run: `python -m pip uninstall -y pyinstrument`

- [ ] **Step 2: Session log Lane 2**

Criar `docs/sessions/YYYY-MM-DD_HHMM.md` e atualizar `docs/days/YYYY-MM-DD.md`.

- [ ] **Step 3: Commit final Lane 2**

```bash
git add docs/sessions/ docs/days/
git commit -m "docs(sessions): Lane 2 velocidade — fechamento"
```

---

## Critérios de sucesso (duros)

- Digests SHA-256 de todos os outputs de backtest **idênticos** ao baseline.
- Smoke 156/156 mantido.
- Speedups alcançados **ou** justificados explicitamente em `docs/audits/2026-04-18_battery_perf_final.md`.
- Nenhum fix mantido sem ≥10% de ganho comprovado (princípio YAGNI).

---

## Self-Review Checklist

- [x] Spec coverage: profile-first (Phase 0.1, 1.1-1.2), hipóteses pré-registradas (0.2), fixes condicionais (2.1-2.6), bit-identical check em cada task.
- [x] Placeholder scan: todos os steps têm código ou comando exato. Task 2.1 Step 1 tem `baseline = 120.0` como placeholder literal — instruído a substituir pelo valor real do baseline.json.
- [x] Consistency: `ProcessPoolExecutor`, `cached_atr`, `data/perf_profile/2026-04-18/` usados uniformemente.
- [x] Sem implementação de hipóteses não validadas (regra de parada honra).
