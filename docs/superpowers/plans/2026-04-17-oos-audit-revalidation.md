# OOS Audit Revalidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Validar se o veredito OOS de 2026-04-16 é metodologicamente honesto — reprodutibilidade, simetria de custos, multi-janela, sample-size, DSR, look-ahead — e produzir veredito final revisado por engine antes de qualquer ação de alinhamento.

**Architecture:** Script orquestrador (`tools/oos_revalidate.py`) dispara runs dos 7 engines em janelas OOS extras, colhe `summary.json`, compara contra baseline de ontem. Função `deflated_sharpe_ratio` nova em `analysis/dsr.py` (TDD). Scanner estático `tools/lookahead_scan.py` pra padrões suspeitos. Todo output consolidado em `docs/audits/2026-04-17_oos_revalidation.md`. Zero toque no CORE protegido.

**Tech Stack:** Python 3.14, pandas, pytest, pathlib, subprocess. Sem deps novas.

**Spec:** `docs/superpowers/specs/2026-04-17-strategies-alignment-anti-overfit-design.md` — Bloco 0 (gate).

**Scope:** Só Bloco 0. Blocos 1-3 (alinhamento + forense) ganham plano próprio **depois** do checkpoint, porque o resultado do Bloco 0 pode mudá-los.

---

## File Structure

### Create

- `analysis/dsr.py` — função `deflated_sharpe_ratio()` + helpers. Uma responsabilidade: compute Bailey & López de Prado DSR a partir de trade returns ou Sharpe+n_trials+skew+kurt+n.
- `tests/test_dsr.py` — unit tests com valores fixture verificáveis.
- `tools/oos_revalidate.py` — orquestrador: lê config de engines+janelas, dispara subprocess de cada engine, parseia `summary.json`, monta tabelas markdown.
- `tools/lookahead_scan.py` — grep estruturado por padrões de look-ahead (`shift(-`, `iloc[i+`, nomes `future_/ahead_/peek_`), output markdown com file:line:context.
- `docs/audits/2026-04-17_oos_revalidation.md` — output consolidado do Bloco 0 (veredito final revisado).

### Modify

- Nada. Zero arquivo existente é alterado neste plano. (Isso inclui engines, core, params.py.)

### CORE protegido

Nenhum dos 4 arquivos protegidos (`core/indicators.py`, `core/signals.py`, `core/portfolio.py`, `config/params.py`) é tocado. Confirmado na self-review do plano.

---

## Baseline de referência (audit 2026-04-16)

Pra comparar reprodutibilidade, os valores a bater são:

| Engine | Window | Sharpe | ROI | n_trades | MDD |
|---|---|---|---|---|---|
| CITADEL | 2022-01..2023-01 | 5.677 | — | 240 | — |
| CITADEL | 2021-01..2022-01 | 2.921 | — | 134 | — |
| CITADEL | Last 360d baseline | 3.007 | — | 299 | — |
| RENAISSANCE | 2022-01..2023-01 | 2.421 | 8.81 | 226 | 1.72 |
| JUMP | 2022-01..2023-01 | 3.15 | 16.36 | 110 | 1.65 |
| DE SHAW | 2022-01..2023-01 | -1.726 | -28.34 | 1819 | 30.66 |
| BRIDGEWATER | 2022-01..2023-01 | 11.04 | 267.22 | 9194 | 6.77 |
| KEPOS | 2022-01..2023-01 | — | — | 0 | — |
| MEDALLION | 2022-01..2023-01 | -3.218 | -38.12 | 173 | 38.36 |

Fonte: `docs/audits/2026-04-16_oos_verdict.md`.

Tolerância de reprodutibilidade: **Sharpe ± 0.01, ROI ± 0.1%, n_trades exato**. Diferenças maiores → investigar seed, cache, params.

---

## Janelas OOS

| Regime | Start | End (--end) | Justificativa |
|---|---|---|---|
| BEAR puro | 2022-01-01 | 2023-01-01 | Já rodada, baseline 2026-04-16 |
| BULL puro | 2020-07-01 | 2021-07-01 | DeFi summer + BTC halving rally |
| CHOP/transição | 2019-06-01 | 2020-03-01 | Pré-COVID, range-bound alt |

Cada engine roda com `--days 360 --end YYYY-MM-DD` pra cobrir exatamente 360 dias até a data de fim.

---

## Task 1: DSR function — `analysis/dsr.py` (TDD)

**Files:**
- Create: `analysis/dsr.py`
- Test: `tests/test_dsr.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dsr.py
"""Unit tests for deflated Sharpe ratio (Bailey & López de Prado 2014).

Reference values computed from the formula:
  DSR = Phi(((Sharpe - E[max_Sharpe]) * sqrt(n-1)) / sqrt(1 - g3*Sharpe + g4/4 * Sharpe^2))
  E[max_Sharpe] ~ sqrt(2*log(n_trials)) for iid Gaussian (Euler-Mascheroni ignored in simple form)
"""
import math
import pytest

from analysis.dsr import deflated_sharpe_ratio, expected_max_sharpe


def test_expected_max_sharpe_monotonic_in_n_trials():
    # E[max] grows with n_trials
    e1 = expected_max_sharpe(n_trials=1)
    e10 = expected_max_sharpe(n_trials=10)
    e100 = expected_max_sharpe(n_trials=100)
    assert e1 < e10 < e100
    # n_trials=1 -> ~0 (no multiple testing penalty)
    assert abs(e1) < 0.1


def test_dsr_single_trial_is_high_for_good_sharpe():
    # With n_trials=1, no haircut. A Sharpe of 2 over 252 days is genuine edge.
    dsr = deflated_sharpe_ratio(
        sharpe=2.0, n_trials=1, skew=0.0, kurtosis=3.0, n_obs=252
    )
    assert dsr > 0.95  # high probability edge is real


def test_dsr_many_trials_penalizes_moderate_sharpe():
    # Sharpe 1.5 with 100 trials should be heavily deflated
    dsr = deflated_sharpe_ratio(
        sharpe=1.5, n_trials=100, skew=0.0, kurtosis=3.0, n_obs=252
    )
    assert 0.0 < dsr < 0.8  # probability dropped due to multiple testing


def test_dsr_negative_skew_penalizes():
    # Negative skew (fat left tail) lowers DSR for same Sharpe
    dsr_pos = deflated_sharpe_ratio(sharpe=2.0, n_trials=10, skew=0.5, kurtosis=3.0, n_obs=252)
    dsr_neg = deflated_sharpe_ratio(sharpe=2.0, n_trials=10, skew=-0.5, kurtosis=3.0, n_obs=252)
    assert dsr_neg < dsr_pos


def test_dsr_returns_in_unit_interval():
    dsr = deflated_sharpe_ratio(sharpe=3.0, n_trials=50, skew=0.2, kurtosis=4.0, n_obs=500)
    assert 0.0 <= dsr <= 1.0


def test_expected_max_sharpe_zero_trials_raises():
    with pytest.raises(ValueError):
        expected_max_sharpe(n_trials=0)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd C:/Users/Joao/OneDrive/aurum.finance && python -m pytest tests/test_dsr.py -v
```

Expected: all 6 tests FAIL with `ModuleNotFoundError: No module named 'analysis.dsr'`.

- [ ] **Step 3: Write minimal implementation**

```python
# analysis/dsr.py
"""Deflated Sharpe Ratio (Bailey & López de Prado, 2014).

DSR corrige o Sharpe pela inflação causada por multiple testing
(n_trials de param-sweep) e por não-normalidade dos retornos (skew,
kurtosis). Output: probabilidade de que o Sharpe observado reflita edge
real em vez de acaso dentre N tentativas.

Referência: Bailey, David H., and Marcos López de Prado. "The deflated
Sharpe ratio: correcting for selection bias, backtest overfitting, and
non-normality." The Journal of Portfolio Management 40.5 (2014): 94-107.
"""
from __future__ import annotations
import math


_EULER_MASCHERONI = 0.5772156649015329


def expected_max_sharpe(n_trials: int) -> float:
    """E[max Sharpe] entre n_trials amostras iid Gaussianas N(0,1).

    Forma fechada (López de Prado):
      E[max] = (1 - gamma) * Phi^-1(1 - 1/N) + gamma * Phi^-1(1 - 1/(N*e))
    onde gamma = Euler-Mascheroni. Pra N=1, retorna ~0.
    """
    if n_trials <= 0:
        raise ValueError(f"n_trials must be positive, got {n_trials}")
    if n_trials == 1:
        return 0.0
    n = float(n_trials)
    # Inverse standard normal CDF via rational approximation (Acklam, via stdlib math)
    z1 = _inv_norm_cdf(1.0 - 1.0 / n)
    z2 = _inv_norm_cdf(1.0 - 1.0 / (n * math.e))
    return (1.0 - _EULER_MASCHERONI) * z1 + _EULER_MASCHERONI * z2


def deflated_sharpe_ratio(
    sharpe: float,
    n_trials: int,
    skew: float,
    kurtosis: float,
    n_obs: int,
) -> float:
    """DSR = Prob(true Sharpe > 0 | observed Sharpe, n_trials, moments, n_obs).

    Args:
        sharpe: Sharpe ratio observado (non-annualized; mesma escala que n_obs).
        n_trials: quantas configurações distintas de params foram testadas.
        skew: skewness dos retornos.
        kurtosis: kurtosis dos retornos (Gaussiano=3.0).
        n_obs: número de observações (trades ou períodos) usado pra estimar Sharpe.

    Returns:
        DSR em [0, 1]. > 0.95 = evidência forte de edge real. < 0.5 = suspeito.
    """
    if n_obs < 2:
        raise ValueError(f"n_obs must be >= 2, got {n_obs}")
    exp_max = expected_max_sharpe(n_trials)
    # Variance of Sharpe estimator under non-normal returns (Mertens 2002)
    var_sharpe = (1.0 - skew * sharpe + ((kurtosis - 1.0) / 4.0) * sharpe * sharpe) / (n_obs - 1)
    if var_sharpe <= 0:
        return 1.0 if sharpe > exp_max else 0.0
    z = (sharpe - exp_max) / math.sqrt(var_sharpe)
    return _norm_cdf(z)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _inv_norm_cdf(p: float) -> float:
    """Inverse standard normal CDF via Beasley-Springer-Moro approximation."""
    if p <= 0.0 or p >= 1.0:
        raise ValueError(f"p must be in (0, 1), got {p}")
    # Acklam's rational approximation — accurate to ~1.15e-9
    a = [-39.69683028665376, 220.9460984245205, -275.9285104469687,
         138.3577518672690, -30.66479806614716, 2.506628277459239]
    b = [-54.47609879822406, 161.5858368580409, -155.6989798598866,
         66.80131188771972, -13.28068155288572]
    c = [-0.007784894002430293, -0.3223964580411365, -2.400758277161838,
         -2.549732539343734, 4.374664141464968, 2.938163982698783]
    d = [0.007784695709041462, 0.3224671290700398, 2.445134137142996,
         3.754408661907416]
    p_low = 0.02425
    p_high = 1 - p_low
    if p < p_low:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5]) / \
               ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1)
    if p <= p_high:
        q = p - 0.5
        r = q * q
        return (((((a[0]*r + a[1])*r + a[2])*r + a[3])*r + a[4])*r + a[5]) * q / \
               (((((b[0]*r + b[1])*r + b[2])*r + b[3])*r + b[4])*r + 1)
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0]*q + c[1])*q + c[2])*q + c[3])*q + c[4])*q + c[5]) / \
             ((((d[0]*q + d[1])*q + d[2])*q + d[3])*q + 1)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd C:/Users/Joao/OneDrive/aurum.finance && python -m pytest tests/test_dsr.py -v
```

Expected: 6/6 PASS.

- [ ] **Step 5: Commit**

```bash
cd C:/Users/Joao/OneDrive/aurum.finance && git add analysis/dsr.py tests/test_dsr.py && git commit -m "$(cat <<'EOF'
feat(analysis): deflated Sharpe ratio (Bailey & López de Prado 2014)

Adiciona analysis/dsr.py com deflated_sharpe_ratio() e
expected_max_sharpe(). Usado no Bloco 0 do plano de revalidação OOS
pra aplicar haircut por n_trials nos engines sobreviventes (CITADEL,
JUMP). Não toca CORE. Test fixture: 6/6 PASS.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Orquestrador `tools/oos_revalidate.py` — skeleton + config

**Files:**
- Create: `tools/oos_revalidate.py`

- [ ] **Step 1: Write the orchestrator skeleton**

```python
# tools/oos_revalidate.py
"""OOS Audit Revalidation orchestrator (Bloco 0).

Dispara runs dos 7 engines em até 3 janelas OOS, colhe summary.json,
monta tabelas markdown pra docs/audits/2026-04-17_oos_revalidation.md.

Uso:
    python tools/oos_revalidate.py --window bear   # 2022-01..2023-01 (baseline redo)
    python tools/oos_revalidate.py --window bull   # 2020-07..2021-07
    python tools/oos_revalidate.py --window chop   # 2019-06..2020-03
    python tools/oos_revalidate.py --all           # roda as 3

Não salva nada em data/ além do output normal dos engines. Consolidação
final em audit doc é manual (Task 9).
"""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Window:
    slug: str  # bear/bull/chop
    end: str   # YYYY-MM-DD
    days: int  # 360


WINDOWS: dict[str, Window] = {
    "bear": Window("bear", "2023-01-01", 360),
    "bull": Window("bull", "2021-07-01", 360),
    "chop": Window("chop", "2020-03-01", 360),
}


@dataclass(frozen=True)
class EngineSpec:
    key: str         # registry key
    script: str      # path rel to repo
    interval: str    # default TF pro engine
    basket: str      # default basket
    out_dir: str     # onde o engine escreve data/<X>/<run>/


ENGINES: list[EngineSpec] = [
    EngineSpec("citadel",     "engines/citadel.py",     "15m", "default",  "data/runs"),
    EngineSpec("renaissance", "engines/renaissance.py", "15m", "bluechip", "data/renaissance"),
    EngineSpec("jump",        "engines/jump.py",        "1h",  "bluechip", "data/jump"),
    EngineSpec("deshaw",      "engines/deshaw.py",      "1h",  "bluechip", "data/deshaw"),
    EngineSpec("bridgewater", "engines/bridgewater.py", "1h",  "bluechip", "data/bridgewater"),
    EngineSpec("kepos",       "engines/kepos.py",       "15m", "bluechip", "data/kepos"),
    EngineSpec("medallion",   "engines/medallion.py",   "15m", "bluechip", "data/medallion"),
]


def run_engine(spec: EngineSpec, window: Window, timeout_s: int = 900) -> dict:
    """Dispara engine, retorna dict com status + path do summary.json."""
    before = _snapshot_runs(spec)
    cmd = [
        sys.executable, spec.script,
        "--no-menu",
        "--days", str(window.days),
        "--basket", spec.basket,
        "--interval", spec.interval,
        "--end", window.end,
    ]
    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd, cwd=str(REPO), capture_output=True, text=True, timeout=timeout_s,
        )
        elapsed = time.time() - t0
        after = _snapshot_runs(spec)
        new_runs = sorted(after - before)
        if not new_runs:
            return {
                "engine": spec.key, "window": window.slug,
                "status": "NO_RUN_DIR", "stderr_tail": proc.stderr[-500:],
                "elapsed_s": round(elapsed, 1),
            }
        latest = new_runs[-1]
        summary_path = REPO / spec.out_dir / latest / "summary.json"
        if not summary_path.exists():
            return {
                "engine": spec.key, "window": window.slug,
                "status": "NO_SUMMARY", "run_id": latest,
                "elapsed_s": round(elapsed, 1),
            }
        summary = json.loads(summary_path.read_text())
        return {
            "engine": spec.key, "window": window.slug,
            "status": "OK", "run_id": latest, "summary": summary,
            "elapsed_s": round(elapsed, 1),
        }
    except subprocess.TimeoutExpired:
        return {"engine": spec.key, "window": window.slug, "status": "TIMEOUT"}
    except Exception as e:
        return {"engine": spec.key, "window": window.slug,
                "status": "EXCEPTION", "error": str(e)}


def _snapshot_runs(spec: EngineSpec) -> set[str]:
    d = REPO / spec.out_dir
    if not d.exists():
        return set()
    return {p.name for p in d.iterdir() if p.is_dir()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--window", choices=list(WINDOWS.keys()), default=None)
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--engine", choices=[e.key for e in ENGINES], default=None,
                        help="Roda só um engine (útil pra debug).")
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()

    if args.all:
        windows_to_run = list(WINDOWS.values())
    elif args.window:
        windows_to_run = [WINDOWS[args.window]]
    else:
        parser.error("Use --window <bear|bull|chop> ou --all")

    engines_to_run = [e for e in ENGINES if not args.engine or e.key == args.engine]

    results = []
    for w in windows_to_run:
        for e in engines_to_run:
            print(f">>> {e.key:12s}  window={w.slug:4s}  end={w.end}  ...", flush=True)
            r = run_engine(e, w, timeout_s=args.timeout)
            print(f"    status={r['status']}  elapsed={r.get('elapsed_s', '?')}s")
            results.append(r)

    out = REPO / "data" / "audit" / "oos_revalidate.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2))
    print(f"\n[done] {len(results)} runs, json em {out.relative_to(REPO)}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Smoke test — invoke help**

```bash
cd C:/Users/Joao/OneDrive/aurum.finance && python tools/oos_revalidate.py --help
```

Expected: imprime help sem error.

- [ ] **Step 3: Commit**

```bash
cd C:/Users/Joao/OneDrive/aurum.finance && git add tools/oos_revalidate.py && git commit -m "$(cat <<'EOF'
feat(tools): oos_revalidate.py orquestrador do Bloco 0

Dispara os 7 engines auditados em até 3 janelas OOS (BEAR/BULL/CHOP),
colhe summary.json, grava data/audit/oos_revalidate.json pra
consolidação em audit doc.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Reprodutibilidade BEAR — rodar 7 engines, diff vs baseline

**Files:**
- Run output: `data/<engine>/<new-run>/summary.json` (7 novas)
- Read: `data/audit/oos_revalidate.json`

- [ ] **Step 1: Executar o orquestrador na janela BEAR**

```bash
cd C:/Users/Joao/OneDrive/aurum.finance && python tools/oos_revalidate.py --window bear --timeout 1200
```

Expected: 7 engines rodam em sequência. Tempo total ~15-30 min. Output stdout mostra linha por engine. Arquivo final `data/audit/oos_revalidate.json` tem 7 entradas.

- [ ] **Step 2: Validar todas OK**

```bash
cd C:/Users/Joao/OneDrive/aurum.finance && python -c "
import json
rs = json.load(open('data/audit/oos_revalidate.json'))
for r in rs:
    print(f\"{r['engine']:12s}  {r['status']:10s}  {r.get('run_id','')}\")"
```

Expected: todos `OK` exceto possivelmente KEPOS (pode terminar OK com 0 trades).

- [ ] **Step 3: Diff contra baseline 2026-04-16**

```bash
cd C:/Users/Joao/OneDrive/aurum.finance && python -c "
import json
from pathlib import Path

# baseline from yesterday's audit
BASELINE = {
    'citadel':     {'sharpe': 5.677, 'n_trades': 240},
    'renaissance': {'sharpe': 2.421, 'n_trades': 226, 'roi': 8.81,   'mdd': 1.72},
    'jump':        {'sharpe': 3.15,  'n_trades': 110, 'roi': 16.36,  'mdd': 1.65},
    'deshaw':      {'sharpe': -1.726,'n_trades': 1819,'roi': -28.34, 'mdd': 30.66},
    'bridgewater': {'sharpe': 11.04, 'n_trades': 9194,'roi': 267.22, 'mdd': 6.77},
    'kepos':       {'n_trades': 0},
    'medallion':   {'sharpe': -3.218,'n_trades': 173, 'roi': -38.12, 'mdd': 38.36},
}

rs = json.load(open('data/audit/oos_revalidate.json'))
print(f\"{'engine':12s} {'sharpe_now':>10s} {'sharpe_base':>10s} {'diff':>8s} {'trades_now':>10s} {'trades_base':>10s}  {'verdict'}\")
for r in rs:
    e = r['engine']
    b = BASELINE.get(e, {})
    s = r.get('summary', {})
    s_now = s.get('sharpe', 0)
    t_now = s.get('n_trades', 0)
    s_base = b.get('sharpe', 0)
    t_base = b.get('n_trades', 0)
    diff = abs(s_now - s_base)
    verdict = 'OK' if diff <= 0.01 and t_now == t_base else 'DIVERGE'
    print(f'{e:12s} {s_now:>10.3f} {s_base:>10.3f} {diff:>8.3f} {t_now:>10d} {t_base:>10d}  {verdict}')"
```

Expected: todas linhas `OK`. Se alguma `DIVERGE`, investigar (seed, cache, params.py mudou desde ontem). Diferença em Sharpe até 0.01 aceitável por arredondamento.

- [ ] **Step 4: Anotar divergências (se houver) em audit doc stub**

Se todas OK, pular pra Task 4. Se divergir:

```bash
cd C:/Users/Joao/OneDrive/aurum.finance && echo "## Divergências de reprodutibilidade

[engine X]: baseline Sharpe Y, agora Z. Causa investigada: [...]" > docs/audits/_revalidation_divergences.txt
```

E não prosseguir até causa raiz ser identificada (cache limpo, git log de params.py, seed).

- [ ] **Step 5: Commit (raw output)**

```bash
cd C:/Users/Joao/OneDrive/aurum.finance && git add data/audit/oos_revalidate.json && git commit -m "chore(audit): BEAR window re-run raw output (7 engines)"
```

---

## Task 4: Simetria de custos — audit estático

**Files:**
- Read (grep): `engines/*.py`, `core/signals.py`, `core/portfolio.py`, `config/params.py`

- [ ] **Step 1: Grep cada engine por aplicação de custos**

```bash
cd C:/Users/Joao/OneDrive/aurum.finance && for eng in citadel renaissance jump deshaw bridgewater kepos medallion; do
  echo "=== $eng ==="
  grep -Hn -E "SLIPPAGE|SPREAD|COMMISSION|FUNDING_PER_8H|fees|funding_cost|cost_model|c1_c2" engines/$eng.py 2>/dev/null | head -20
done
```

Expected: cada engine deve ter pelo menos uma referência a SLIPPAGE+COMMISSION ou chamar uma função do core que aplica.

- [ ] **Step 2: Grep core/signals.py e core/portfolio.py por cost paths**

```bash
cd C:/Users/Joao/OneDrive/aurum.finance && grep -Hn -E "SLIPPAGE|SPREAD|COMMISSION|FUNDING_PER_8H|funding_cost|cost_model" core/signals.py core/portfolio.py config/params.py 2>/dev/null | head -40
```

- [ ] **Step 3: Identificar cost path de cada engine**

Pra cada engine, tabular:
- Usa `core.signals.label_trade()` (caminho canônico C1+C2)?
- Usa função própria? Aplica todos os 4 componentes (SLIPPAGE, SPREAD, COMMISSION, FUNDING)?
- Alguma flag de "backtest mode" skipa custo?

Montar tabela em `docs/audits/_revalidation_costs.txt`:

```
engine        cost_path           slippage  spread  commission  funding  verdict
citadel       core.label_trade    ✓         ✓       ✓           ✓        OK
renaissance   ...
```

- [ ] **Step 4: Sinalizar anomalias**

Se algum engine não aplicar os 4, flag como `BUG_SUSPECT_<componente_faltando>`. BRIDGEWATER primeira parada de investigação.

- [ ] **Step 5: Commit**

```bash
cd C:/Users/Joao/OneDrive/aurum.finance && git add docs/audits/_revalidation_costs.txt && git commit -m "chore(audit): cost symmetry tabulada (7 engines)"
```

---

## Task 5: Multi-janela BULL — rodar 7 engines em 2020-07..2021-07

**Files:**
- Run output: `data/<engine>/<new-run>/summary.json` (7 novas)
- Read: `data/audit/oos_revalidate.json` (acumulado)

- [ ] **Step 1: Executar janela BULL**

```bash
cd C:/Users/Joao/OneDrive/aurum.finance && python tools/oos_revalidate.py --window bull --timeout 1200
```

**Nota:** script sobrescreve `data/audit/oos_revalidate.json`. Fazer backup antes:

```bash
cd C:/Users/Joao/OneDrive/aurum.finance && cp data/audit/oos_revalidate.json data/audit/oos_revalidate_bear.json
```

E rodar BULL:

```bash
cd C:/Users/Joao/OneDrive/aurum.finance && python tools/oos_revalidate.py --window bull --timeout 1200
cp data/audit/oos_revalidate.json data/audit/oos_revalidate_bull.json
```

- [ ] **Step 2: Validar**

```bash
cd C:/Users/Joao/OneDrive/aurum.finance && python -c "
import json
rs = json.load(open('data/audit/oos_revalidate_bull.json'))
for r in rs:
    s = r.get('summary', {})
    print(f\"{r['engine']:12s} {r['status']:10s} sharpe={s.get('sharpe','—'):>7} n_trades={s.get('n_trades','—'):>6} roi={s.get('roi_pct','—'):>7}\")"
```

Expected: cada engine imprime uma linha. KEPOS pode ter `n_trades=0`.

- [ ] **Step 3: Commit**

```bash
cd C:/Users/Joao/OneDrive/aurum.finance && git add data/audit/oos_revalidate_bear.json data/audit/oos_revalidate_bull.json && git commit -m "chore(audit): BULL window run (7 engines, 2020-07..2021-07)"
```

---

## Task 6: Multi-janela CHOP — rodar 7 engines em 2019-06..2020-03

**Files:**
- Run output: `data/<engine>/<new-run>/summary.json` (7 novas)
- Read: `data/audit/oos_revalidate_chop.json`

- [ ] **Step 1: Executar janela CHOP**

```bash
cd C:/Users/Joao/OneDrive/aurum.finance && python tools/oos_revalidate.py --window chop --timeout 1200 && cp data/audit/oos_revalidate.json data/audit/oos_revalidate_chop.json
```

- [ ] **Step 2: Validar e sumário multi-janela**

```bash
cd C:/Users/Joao/OneDrive/aurum.finance && python -c "
import json
bear = {r['engine']: r.get('summary', {}) for r in json.load(open('data/audit/oos_revalidate_bear.json'))}
bull = {r['engine']: r.get('summary', {}) for r in json.load(open('data/audit/oos_revalidate_bull.json'))}
chop = {r['engine']: r.get('summary', {}) for r in json.load(open('data/audit/oos_revalidate_chop.json'))}
engines = sorted(set(bear) | set(bull) | set(chop))
print(f\"{'engine':12s} {'BEAR_S':>8s} {'BEAR_N':>7s} {'BULL_S':>8s} {'BULL_N':>7s} {'CHOP_S':>8s} {'CHOP_N':>7s}  {'verdict'}\")
for e in engines:
    b, u, c = bear.get(e, {}), bull.get(e, {}), chop.get(e, {})
    def fmt(s, k): return f\"{s.get(k,0):.2f}\" if s.get(k) is not None else '—'
    pos_windows = sum(1 for w in (b, u, c) if w.get('sharpe', 0) > 0 and w.get('n_trades', 0) >= 50)
    verdict = {3: 'EDGE_REAL', 2: 'EDGE_REGIME', 1: 'EDGE_MARGINAL', 0: 'OVERFIT_OR_BROKEN'}[pos_windows]
    print(f'{e:12s} {fmt(b,\"sharpe\"):>8s} {b.get(\"n_trades\",0):>7d} {fmt(u,\"sharpe\"):>8s} {u.get(\"n_trades\",0):>7d} {fmt(c,\"sharpe\"):>8s} {c.get(\"n_trades\",0):>7d}  {verdict}')"
```

Expected: tabela com veredito por engine baseado em quantas janelas positivas (sharpe>0 E n_trades>=50).

- [ ] **Step 3: Commit**

```bash
cd C:/Users/Joao/OneDrive/aurum.finance && git add data/audit/oos_revalidate_chop.json && git commit -m "chore(audit): CHOP window run (7 engines, 2019-06..2020-03)"
```

---

## Task 7: DSR nos sobreviventes

**Files:**
- Read: `data/audit/oos_revalidate_*.json`
- Read: `config/params.py`, git log
- Use: `analysis/dsr.deflated_sharpe_ratio`

- [ ] **Step 1: Estimar n_trials pra CITADEL e JUMP**

```bash
cd C:/Users/Joao/OneDrive/aurum.finance && echo "=== CITADEL iter trail ===" && grep -Hn -E "iter\d+|CITADEL_.*=.*#.*iter" config/params.py | head -20
echo "=== JUMP (MERCURIO) iter trail ===" && grep -Hn -E "MERCURIO_.*=.*#.*iter" config/params.py | head -20
echo "=== git log citadel param bumps ===" && git log --oneline --grep="citadel\|CITADEL" -- config/params.py | head -20
echo "=== git log jump/mercurio param bumps ===" && git log --oneline --grep="jump\|mercurio\|MERCURIO" -- config/params.py | head -20
```

- [ ] **Step 2: Documentar n_trials estimado**

Arquivo `docs/audits/_revalidation_dsr_inputs.txt`:

```
CITADEL  n_trials ~ [contagem de commits * configs × OMEGA_WEIGHTS sweep]
JUMP     n_trials ~ [baseado em iter19, iter13 = 19+13 = 32 bump]
```

Conservador: se incerto, usar o maior valor plausível.

- [ ] **Step 3: Aplicar DSR**

```bash
cd C:/Users/Joao/OneDrive/aurum.finance && python -c "
import json
from analysis.dsr import deflated_sharpe_ratio

runs = {}
for w in ('bear', 'bull', 'chop'):
    for r in json.load(open(f'data/audit/oos_revalidate_{w}.json')):
        runs[(r['engine'], w)] = r.get('summary', {})

# Conservative n_trials estimates — documented in _revalidation_dsr_inputs.txt
N_TRIALS = {'citadel': 50, 'jump': 35}

print(f\"{'engine':10s} {'window':6s} {'sharpe':>7s} {'n_trades':>8s} {'n_trials':>8s} {'DSR':>6s}  {'verdict'}\")
for (eng, w), s in runs.items():
    if eng not in N_TRIALS:
        continue
    n = s.get('n_trades', 0)
    if n < 30:
        print(f'{eng:10s} {w:6s} {s.get(\"sharpe\",0):>7.2f} {n:>8d}      {\"—\":>8s} {\"—\":>6s}  INSUFFICIENT_SAMPLE')
        continue
    sharpe = s.get('sharpe', 0.0)
    dsr = deflated_sharpe_ratio(sharpe=sharpe, n_trials=N_TRIALS[eng], skew=0.0, kurtosis=3.0, n_obs=n)
    verdict = 'ROBUST' if dsr > 0.95 else ('MODERATE' if dsr > 0.5 else 'INFLATED')
    print(f'{eng:10s} {w:6s} {sharpe:>7.2f} {n:>8d} {N_TRIALS[eng]:>8d} {dsr:>6.3f}  {verdict}')"
```

Expected: CITADEL e JUMP imprimem DSR em cada janela. DSR > 0.95 confirma edge robusto. DSR < 0.5 invalida o claim.

**Nota:** skew=0 e kurtosis=3 são defaults conservadores. Se o engine salvar trades em `trades.json`, dá pra calcular os moments reais — mas pra este plano, usar defaults.

- [ ] **Step 4: Commit**

```bash
cd C:/Users/Joao/OneDrive/aurum.finance && git add docs/audits/_revalidation_dsr_inputs.txt && git commit -m "chore(audit): DSR inputs documented for CITADEL/JUMP"
```

---

## Task 8: Look-ahead scan

**Files:**
- Create: `tools/lookahead_scan.py`
- Output: `docs/audits/_revalidation_lookahead.txt`

- [ ] **Step 1: Write scanner**

```python
# tools/lookahead_scan.py
"""Static scanner for common look-ahead-bias patterns.

Não prova leak — só levanta hits pra revisão manual. Padrões:
  - .shift(-N) — uso de valor futuro como feature
  - iloc[i+N:] ou iloc[idx+1:] em contexto de decisão
  - nomes future_/ahead_/peek_ suspeitos
  - uso de close/high/low do candle atual em decisão do mesmo candle
    (heurística: label_trade + close[i] sem idx+1)
"""
from __future__ import annotations
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TARGETS = [
    "engines/citadel.py", "engines/renaissance.py", "engines/jump.py",
    "engines/deshaw.py", "engines/bridgewater.py", "engines/kepos.py",
    "engines/medallion.py",
    "core/signals.py", "core/indicators.py", "core/portfolio.py",
    "core/htf.py", "core/harmonics.py",
]

PATTERNS = [
    ("shift_negative", re.compile(r"\.shift\(\s*-\s*\d+")),
    ("iloc_plus", re.compile(r"\.iloc\s*\[\s*\w+\s*\+\s*\d+")),
    ("future_name", re.compile(r"\bfuture_|\bahead_|\bpeek_", re.IGNORECASE)),
    ("idx_plus_read", re.compile(r"\[\s*i\s*\+\s*\d+\s*\]")),
]


def scan_file(path: Path) -> list[tuple[str, int, str, str]]:
    hits = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for name, pat in PATTERNS:
            if pat.search(line):
                hits.append((name, lineno, stripped[:120], str(path.relative_to(REPO))))
    return hits


def main():
    out_lines = ["# Look-ahead scan — 2026-04-17\n\n"]
    total = 0
    for rel in TARGETS:
        p = REPO / rel
        if not p.exists():
            continue
        hits = scan_file(p)
        if not hits:
            out_lines.append(f"## {rel}  — clean\n\n")
            continue
        out_lines.append(f"## {rel}  — {len(hits)} hits\n\n")
        for name, lineno, code, _ in hits:
            out_lines.append(f"- line {lineno} `{name}`: `{code}`\n")
        out_lines.append("\n")
        total += len(hits)

    out = REPO / "docs" / "audits" / "_revalidation_lookahead.txt"
    out.write_text("".join(out_lines), encoding="utf-8")
    print(f"{total} hits total. See {out.relative_to(REPO)}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it**

```bash
cd C:/Users/Joao/OneDrive/aurum.finance && python tools/lookahead_scan.py
```

Expected: imprime `<N> hits total. See docs/audits/_revalidation_lookahead.txt`. Output file lista hits por arquivo.

- [ ] **Step 3: Manual review**

Ler `docs/audits/_revalidation_lookahead.txt`. Cada hit precisa ser classificado:
- **OK** — é contexto legítimo (loop index, array bounds, etc.)
- **REVIEW** — precisa ler contexto mais amplo
- **LEAK** — look-ahead confirmado, invalida backtest do engine

Anotar classificação inline no arquivo (`→ OK`, `→ REVIEW`, `→ LEAK`).

- [ ] **Step 4: Commit**

```bash
cd C:/Users/Joao/OneDrive/aurum.finance && git add tools/lookahead_scan.py docs/audits/_revalidation_lookahead.txt && git commit -m "$(cat <<'EOF'
feat(tools): lookahead_scan.py static bias detector

Scans engines + core for .shift(-N), iloc[i+N], future_/ahead_/peek_
names, idx-plus reads. Raises hits for manual review. First pass
output in docs/audits/_revalidation_lookahead.txt.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Consolidate audit doc

**Files:**
- Create: `docs/audits/2026-04-17_oos_revalidation.md`
- Read: `data/audit/oos_revalidate_{bear,bull,chop}.json`
- Read: `docs/audits/_revalidation_costs.txt`
- Read: `docs/audits/_revalidation_dsr_inputs.txt`
- Read: `docs/audits/_revalidation_lookahead.txt`

- [ ] **Step 1: Draft audit doc skeleton**

```bash
cd C:/Users/Joao/OneDrive/aurum.finance && cat > docs/audits/2026-04-17_oos_revalidation.md <<'EOF'
# OOS Audit Revalidation — 2026-04-17

**Metodologia:** audit-o-auditor. Revalida o veredito de
`docs/audits/2026-04-16_oos_verdict.md` em 6 eixos: reprodutibilidade,
simetria de custos, multi-janela (BEAR+BULL+CHOP), sample-size floor,
DSR nos sobreviventes, look-ahead scan.

---

## 1. Reprodutibilidade (BEAR 2022-01..2023-01)

[inserir tabela gerada no Task 3, Step 3]

**Veredito:** [OK se todos batem ± 0.01 Sharpe / exact n_trades; senão
listar divergências]

## 2. Simetria de custos

[copiar conteúdo de docs/audits/_revalidation_costs.txt]

**Veredito:** [engines com todos os 4 componentes C1+C2 aplicados / lista
de bug_suspect]

## 3. Multi-janela (BEAR + BULL + CHOP)

[inserir tabela gerada no Task 6, Step 2]

**Veredito por engine:**
- EDGE_REAL = sharpe>0 e n_trades>=50 em 3/3 janelas
- EDGE_REGIME = 2/3
- EDGE_MARGINAL = 1/3
- OVERFIT_OR_BROKEN = 0/3

## 4. Sample-size floor

Engines com n_trades<50 em alguma janela ganham flag INSUFFICIENT_SAMPLE
em vez de COLLAPSED.

[listar engines/janelas abaixo do floor]

## 5. DSR nos sobreviventes

[inserir tabela gerada no Task 7, Step 3]

**Veredito:** [CITADEL/JUMP robustos se DSR > 0.95 em 2+ janelas]

## 6. Look-ahead scan

[copiar/resumir docs/audits/_revalidation_lookahead.txt]

**Veredito:** [número de LEAKs confirmados, engines afetados]

---

## Veredito final revisado por engine

| Engine | 2026-04-16 | 2026-04-17 | Muda? | Ação |
|---|---|---|---|---|
| CITADEL | ✅ edge real | [revisado] | [sim/não] | [...] |
| JUMP | ✅ robusto | [revisado] | [sim/não] | [...] |
| RENAISSANCE | ⚠️ inflado | [revisado] | [sim/não] | [...] |
| BRIDGEWATER | ⚠️ bug suspect | [revisado] | [sim/não] | [...] |
| DE SHAW | 🔴 colapsado | [revisado] | [sim/não] | [...] |
| KEPOS | 🔴 não-funcional | [revisado] | [sim/não] | [...] |
| MEDALLION | 🔴 overfit | [revisado] | [sim/não] | [...] |

---

## Impacto nos Blocos 1-3 da spec

[Se todos vereditos confirmados → blocos 1-3 seguem como plano original.
 Se algum engine mudou de classe → marcar quais blocos re-escrever antes
 da próxima sessão.]

## Runs persistidos

- `data/audit/oos_revalidate_bear.json`
- `data/audit/oos_revalidate_bull.json`
- `data/audit/oos_revalidate_chop.json`

## Arquivos de apoio

- `docs/audits/_revalidation_costs.txt`
- `docs/audits/_revalidation_dsr_inputs.txt`
- `docs/audits/_revalidation_lookahead.txt`
EOF
```

- [ ] **Step 2: Preencher tabelas**

Editar o doc manualmente, copiando as tabelas geradas nos Tasks 3/6/7 e resumindo os arquivos `_revalidation_*.txt`.

- [ ] **Step 3: Final verdict writeback**

Pra cada engine, classificar:
- Se repro+custos+multi-janela+DSR+look-ahead tudo OK: **veredito de ontem confirmado**.
- Se algum eixo mudar o veredito: explicitar qual e a nova classificação.

- [ ] **Step 4: Commit**

```bash
cd C:/Users/Joao/OneDrive/aurum.finance && git add docs/audits/2026-04-17_oos_revalidation.md && git commit -m "$(cat <<'EOF'
docs(audit): OOS audit revalidation — veredito final revisado

Bloco 0 do plano 2026-04-17 concluído. Valida o veredito de ontem em
6 eixos (reprodutibilidade, custos, multi-janela BEAR+BULL+CHOP,
sample-size, DSR, look-ahead). Resultado por engine em tabela final.
Gate: blocos 1-3 seguem/ajustam conforme este veredito.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Session + daily log

**Files:**
- Create: `docs/sessions/2026-04-17_HHMM.md`
- Create or update: `docs/days/2026-04-17.md`

- [ ] **Step 1: Gerar session log conforme CLAUDE.md**

Seguir template da REGRA PERMANENTE em CLAUDE.md (resumo, commits,
mudanças críticas, achados, estado, arquivos, notas pro Joao).

- [ ] **Step 2: Atualizar daily log**

Se `docs/days/2026-04-17.md` já existe (sessão UI 00:00 de hoje),
incrementar. Senão criar.

- [ ] **Step 3: Commit final**

```bash
cd C:/Users/Joao/OneDrive/aurum.finance && git add docs/sessions/2026-04-17_*.md docs/days/2026-04-17.md && git commit -m "docs(sessions): OOS revalidation Bloco 0 — session + daily 2026-04-17"
```

---

## Checkpoint pro Joao

Após Task 9 commitado, **parar** e apresentar:

> "Bloco 0 completo. Veredito final em `docs/audits/2026-04-17_oos_revalidation.md`.
> Resumo: [X] engines confirmados, [Y] reclassificados.
> Blocos 1-3 precisam de ajuste? Revisa o audit e me diz antes do próximo plano."

Não prosseguir pra Blocos 1-3 sem user input.

---

## Self-Review

**Spec coverage:**
- ✅ 0.1 Reprodutibilidade → Task 3
- ✅ 0.2 Simetria custos → Task 4
- ✅ 0.3 Multi-janela BEAR+BULL+CHOP → Task 3 + 5 + 6
- ✅ 0.4 Sample-size floor → aplicado no Task 6 e Task 7 (threshold 50/30)
- ✅ 0.5 DSR sobreviventes → Task 7, função em Task 1
- ✅ 0.6 Look-ahead scan → Task 8
- ✅ 0.7 Audit doc consolidado → Task 9

**Placeholder scan:** nenhum TBD/TODO. Comandos bash/python completos. DSR code completo.

**Type consistency:** `deflated_sharpe_ratio` assinatura idêntica em Task 1 (def) e Task 7 (uso): `sharpe, n_trials, skew, kurtosis, n_obs`. `Window`/`EngineSpec` dataclasses em Task 2 usados consistentemente.

**CORE protegido:** plano não modifica nenhum dos 4 arquivos protegidos. Confirmado.

**Windows-safe:** paths com `/`, evita `find/grep` direto do shell onde possível. Comandos usam `python -c` pra lógica complexa em vez de awk/sed.
