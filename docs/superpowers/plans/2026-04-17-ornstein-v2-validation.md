# ORNSTEIN v2 Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Executar o protocolo de 4 etapas do spec `docs/superpowers/specs/2026-04-17-ornstein-v2-validation-design.md` pra decidir se ORNSTEIN v2 (preset `robust` + wrapper) vira canônico ou arquiva.

**Architecture:** Split Lane 2 primeiro. Rodar baseline v1. Reproduzir 0-trades do Codex. Ablation dos 5 guards novos via script Python in-process (não subprocess) pra não depender de CLI flags inexistentes. Coletar métricas em CSV + validation doc. Aplicar regra pré-registrada (DSR + N_trades + Sharpe uplift 10%) e commitar decisão atômica.

**Tech Stack:** Python 3.14 (global, sem venv), pandas, engines.ornstein API in-process (`run_backtest`, `save_run`, `OrnsteinParams`, `ORNSTEIN_PRESETS`), `analysis/dsr.py` pro haircut.

---

## File Structure

**Create:**
- `tools/ornstein_v2_ablation.py` — script efêmero. In-process runner: loopa sobre variants, chama `run_backtest`, escreve CSV agregado. Removido no Task 9 se decisão = archive.
- `tests/test_ornstein_v2_ablation.py` — testa `build_variant_params(name)` retorna OrnsteinParams correto por variant.
- `docs/engines/ornstein_v2/2026-04-17_validation.md` — doc de resultados + decisão.
- `data/ornstein_v2/ablation_2026-04-17/results.csv` — saída do ablation runner (gitignored via `data/` pattern).

**Modify (Task 0 apenas — staging do WIP existente):**
- `core/run_manager.py` — já modificado, stage + commit.
- `launcher_support/bootstrap.py` — idem.
- `launcher_support/engines_live_view.py` — idem.
- `tests/test_run_manager_contracts.py` — idem.
- `tests/test_launcher_bootstrap_contracts.py` — idem.
- `tests/test_engines_live_view.py` — idem.

**Modify (Task 8, caso decisão = archive):**
- `engines/ornstein.py` — reverte os 5 campos novos de `OrnsteinParams`, preset `robust`, e lógica em `_resolve_ornstein_exit` + `scan_symbol`.
- `engines/ornstein_v2.py` — deletar.
- `config/engines.py` — remover linha `ornstein_v2`.
- `tests/test_ornstein.py` — remover 3 testes novos.
- `tools/ornstein_v2_ablation.py` — deletar.
- `tests/test_ornstein_v2_ablation.py` — deletar.

---

## Task 0: Split Lane 2 into separate commit

**Files:**
- Stage only: `core/run_manager.py`, `launcher_support/bootstrap.py`, `launcher_support/engines_live_view.py`, `tests/test_run_manager_contracts.py`, `tests/test_launcher_bootstrap_contracts.py`, `tests/test_engines_live_view.py`

- [ ] **Step 1: Verify WIP state**

Run: `git status --short`

Expected output (ornstein files + lane 2 files all modified, nothing staged):
```
 M config/engines.py
 M core/run_manager.py
 M engines/ornstein.py
 M launcher_support/bootstrap.py
 M launcher_support/engines_live_view.py
 M tests/test_engines_live_view.py
 M tests/test_launcher_bootstrap_contracts.py
 M tests/test_ornstein.py
 M tests/test_run_manager_contracts.py
?? engines/ornstein_v2.py
```

If ornstein files are already staged or committed beyond spec commit `92f7805`, stop and diagnose.

- [ ] **Step 2: Run lane 2 tests standalone to confirm they pass**

Run: `python -m pytest tests/test_run_manager_contracts.py tests/test_launcher_bootstrap_contracts.py tests/test_engines_live_view.py -q`

Expected: all pass.

- [ ] **Step 3: Stage lane 2 files only**

Run:
```bash
git add core/run_manager.py launcher_support/bootstrap.py launcher_support/engines_live_view.py tests/test_run_manager_contracts.py tests/test_launcher_bootstrap_contracts.py tests/test_engines_live_view.py
```

- [ ] **Step 4: Verify staging is correct**

Run: `git diff --cached --stat`

Expected: exactly 6 files, no ornstein.py / ornstein_v2.py / config/engines.py / test_ornstein.py in staging.

- [ ] **Step 5: Commit lane 2**

Run:
```bash
git commit -m "$(cat <<'EOF'
hardening: run_manager compare lookup + vps host parse + cockpit order

Três melhorias pequenas sem relação com trading:

- core/run_manager._resolve_compare_run_dir: compare_runs agora aceita
  run_id ou caminho explícito, usa índice pra resolver run_dir/summary_path
  quando o layout canônico não se aplica (engines com out= custom).
- launcher_support/bootstrap: VPS host normalize aceita "user@host" na
  config e separa corretamente; fail-closed quando host não configurado.
- launcher_support/engines_live_view: cockpit KPI order — DESK vai pro
  fim, RUNNING/READY/RESEARCH primeiro. Adiciona bucket_header_title pra
  títulos mais descritivos no painel.

Testes em tests/test_run_manager_contracts, test_launcher_bootstrap_contracts,
test_engines_live_view atualizados.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 6: Verify ornstein WIP still unstaged**

Run: `git status --short`

Expected:
```
 M config/engines.py
 M engines/ornstein.py
 M tests/test_ornstein.py
?? engines/ornstein_v2.py
```

Só os 4 arquivos da Lane 1 restantes unstaged.

---

## Task 1: Create validation doc skeleton

**Files:**
- Create: `docs/engines/ornstein_v2/2026-04-17_validation.md`

- [ ] **Step 1: Create parent dir**

Run:
```bash
mkdir -p docs/engines/ornstein_v2
```

- [ ] **Step 2: Write skeleton with placeholders**

Write to `docs/engines/ornstein_v2/2026-04-17_validation.md`:

```markdown
# ORNSTEIN v2 — Validation Report (2026-04-17)

> Resultado da execução do protocolo em `docs/superpowers/specs/2026-04-17-ornstein-v2-validation-design.md`.

## Contexto

Preset `robust` + wrapper `engines/ornstein_v2.py` foram adicionados na
sessão Claude+Codex de 2026-04-17. 5 params novos em `OrnsteinParams`.
Codex rodou `ornstein_v2 --basket bluechip_active --days 360` e obteve
0 trades. Este doc valida/arquiva a variante com evidência honesta.

## Etapa 1 — Baseline (v1 default / bluechip_active / 360d)

Run dir: `PLACEHOLDER_BASELINE_RUN_DIR`

| Métrica | Valor |
|---------|-------|
| N_trades | — |
| Sharpe | — |
| MaxDD | — |
| WinRate | — |
| Expectancy (R) | — |
| Total return | — |
| DSR (n_trials=1) | — |

## Etapa 2 — Reprodução do Codex (v2 robust / bluechip_active / 360d)

Run dir: `PLACEHOLDER_V2_REPRO_RUN_DIR`

| Métrica | Valor |
|---------|-------|
| N_trades | — |
| Top 5 vetos | — |

Distribuição completa de vetos:

```
(colar output do _print_summary aqui)
```

## Etapa 3 — Ablation (majors / 180d)

Universo: `BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT`.
CSV: `data/ornstein_v2/ablation_2026-04-17/results.csv`.

| Variant | N_trades | Sharpe | MaxDD | WinRate | Δ Sharpe vs B_MAJORS |
|---------|----------|--------|-------|---------|----------------------|
| B_MAJORS | — | — | — | — | 0.00 |
| R0 robust_full | — | — | — | — | — |
| R1 no_hurst | — | — | — | — | — |
| R2 no_bb | — | — | — | — | — |
| R3 no_min_dev | — | — | — | — | — |
| R4 no_target_dist | — | — | — | — | — |
| R5 no_div_flip | — | — | — | — | — |
| R6 no_stop_lock | — | — | — | — | — |

Best variant por score `Sharpe / (1 + MaxDD)` com `N_trades >= 20`: PLACEHOLDER.

## Etapa 4 — Final comparison (best variant / bluechip_active / 360d)

Run dir: `PLACEHOLDER_FINAL_RUN_DIR`

| Métrica | v1 default (Etapa 1) | best variant |
|---------|----------------------|---------------|
| N_trades | — | — |
| Sharpe | — | — |
| MaxDD | — | — |
| DSR (n_trials=7) | — | — |

## Decisão

PLACEHOLDER: promote | remove_guard:X | archive

Justificativa em 1-3 parágrafos quando preenchido.

Próximos passos:

- (se promote) overfit_audit 6/6 em janelas OOS distintas via `tools/ornstein_overfit_audit.py`.
- (se remove_guard) atualizar preset `robust` removendo guard X, re-testar.
- (se archive) commit de revert completo.
```

- [ ] **Step 3: Stage and commit skeleton**

Run:
```bash
git add docs/engines/ornstein_v2/2026-04-17_validation.md
git commit -m "$(cat <<'EOF'
docs(ornstein_v2): validation report skeleton — to be filled in-flight

Container pro output das 4 etapas do spec. Será atualizado task-a-task
com métricas reais dos runs.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Etapa 1 — Run baseline (v1 default / bluechip_active / 360d)

**Files:**
- Modify: `docs/engines/ornstein_v2/2026-04-17_validation.md` (fill Etapa 1 table)

- [ ] **Step 1: Run baseline backtest**

Run:
```bash
python -m engines.ornstein --preset default --basket bluechip_active --days 360 --no-menu
```

Expected: log termina com `Run saved to: data/ornstein/<YYYY-MM-DD_HHMM>/`. Isso demora ~10min (19 símbolos × 5 TFs × 360d prefetch + scan).

Guarda o path do run_dir pra próximos steps.

- [ ] **Step 2: Inspect summary.json**

Run:
```bash
python -c "import json; p=json.load(open('data/ornstein/<RUN_DIR>/summary.json', encoding='utf-8')); print(json.dumps({k:p.get(k) for k in ['total_trades','win_rate','profit_factor','sharpe','sortino','max_drawdown','expectancy_r','total_pnl']}, indent=2))"
```

Substituir `<RUN_DIR>` pelo timestamp real.

Expected: JSON com os valores. Se `total_trades=0`, flag immediately — significa que v1 default também zerou no universo completo, e o problema é estrutural no engine, não no preset `robust`.

- [ ] **Step 3: Compute DSR with n_trials=1**

Run:
```bash
python -c "
import json, statistics
from analysis.dsr import deflated_sharpe_ratio
run='data/ornstein/<RUN_DIR>'
s=json.load(open(f'{run}/summary.json', encoding='utf-8'))
trades=json.load(open(f'{run}/trades.json', encoding='utf-8'))
rs=[t.get('r',0.0) for t in trades]
if len(rs)<2:
    print('DSR_SKIP: insufficient trades')
else:
    sk=statistics.fmean([(r-statistics.fmean(rs))**3 for r in rs])/(statistics.pstdev(rs)**3 or 1e-9)
    ku=statistics.fmean([(r-statistics.fmean(rs))**4 for r in rs])/(statistics.pstdev(rs)**4 or 1e-9)
    print('DSR=', deflated_sharpe_ratio(s['sharpe'], 1, sk, ku, len(rs)))
"
```

Guarda o valor.

- [ ] **Step 4: Update validation doc Etapa 1 table**

Edit `docs/engines/ornstein_v2/2026-04-17_validation.md`, substituindo `PLACEHOLDER_BASELINE_RUN_DIR` pelo path real e preenchendo a tabela com os valores dos steps 2-3.

- [ ] **Step 5: Commit**

Run:
```bash
git add docs/engines/ornstein_v2/2026-04-17_validation.md
git commit -m "$(cat <<'EOF'
docs(ornstein_v2): etapa 1 baseline — v1 default / bluechip_active / 360d

Baseline frozen pra comparação contra v2. Valores no doc.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Etapa 2 — Reproduce Codex 0-trades

**Files:**
- Modify: `docs/engines/ornstein_v2/2026-04-17_validation.md` (fill Etapa 2)

- [ ] **Step 1: Run v2 robust on full universe**

Run:
```bash
python -m engines.ornstein_v2 --basket bluechip_active --days 360 --no-menu 2>&1 | tee /tmp/ornstein_v2_repro.log
```

Expected: ~0 trades como Codex reportou. Capturar toda a saída pro log.

- [ ] **Step 2: Extract veto distribution from summary.json**

Run:
```bash
python -c "
import json, os
import glob
run_dir=sorted(glob.glob('data/ornstein_v2/*'))[-1]
print('run_dir=', run_dir)
s=json.load(open(f'{run_dir}/summary.json', encoding='utf-8'))
print('total_trades=', s.get('total_trades',0))
vetos=s.get('vetos',{})
for k,v in sorted(vetos.items(), key=lambda kv: -kv[1]):
    print(f'  {k}: {v}')
"
```

- [ ] **Step 3: Update validation doc Etapa 2**

Edit `docs/engines/ornstein_v2/2026-04-17_validation.md` — substituir `PLACEHOLDER_V2_REPRO_RUN_DIR` pelo path e preencher tabela + block de vetos com o output do Step 2.

- [ ] **Step 4: Commit**

Run:
```bash
git add docs/engines/ornstein_v2/2026-04-17_validation.md
git commit -m "$(cat <<'EOF'
docs(ornstein_v2): etapa 2 reprodução Codex — v2 robust / 360d / vetos dump

Confirma ~0 trades + distribuição completa de vetos.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Write ablation runner

**Files:**
- Create: `tools/ornstein_v2_ablation.py`
- Test: `tests/test_ornstein_v2_ablation.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_ornstein_v2_ablation.py`:

```python
"""Unit tests for tools/ornstein_v2_ablation.py variant builder."""
from __future__ import annotations

import pytest

from tools.ornstein_v2_ablation import VARIANTS, build_variant_params


def test_variants_list_covers_all_new_guards():
    assert set(VARIANTS) == {
        "B_MAJORS",
        "R0_robust_full",
        "R1_no_hurst",
        "R2_no_bb",
        "R3_no_min_dev",
        "R4_no_target_dist",
        "R5_no_div_flip",
        "R6_no_stop_lock",
    }


def test_b_majors_is_default_preset():
    p = build_variant_params("B_MAJORS")
    assert p.require_bb_confirmation is False
    assert p.min_deviation_abs == 0.0
    assert p.min_target_distance_atr == 0.0
    assert p.exit_on_divergence_flip is False


def test_r0_robust_full_applies_all_robust_fields():
    p = build_variant_params("R0_robust_full")
    assert p.require_bb_confirmation is True
    assert p.min_deviation_abs > 0.0
    assert p.min_target_distance_atr > 0.0
    assert p.exit_on_divergence_flip is True


def test_r1_no_hurst_reverts_threshold():
    p = build_variant_params("R1_no_hurst")
    assert p.hurst_threshold > 0.50  # back to v1 default (0.55)


def test_r2_no_bb_disables_bb_confirmation():
    p = build_variant_params("R2_no_bb")
    assert p.require_bb_confirmation is False


def test_r3_no_min_dev_zeroes_deviation_guard():
    p = build_variant_params("R3_no_min_dev")
    assert p.min_deviation_abs == 0.0


def test_r4_no_target_dist_zeroes_target_guard():
    p = build_variant_params("R4_no_target_dist")
    assert p.min_target_distance_atr == 0.0


def test_r5_no_div_flip_disables_flip_exit():
    p = build_variant_params("R5_no_div_flip")
    assert p.exit_on_divergence_flip is False


def test_r6_no_stop_lock_flag_off():
    p = build_variant_params("R6_no_stop_lock")
    assert p.post_partial_stop_offset_atr < 0.0


def test_unknown_variant_raises():
    with pytest.raises(KeyError):
        build_variant_params("not_a_variant")
```

- [ ] **Step 2: Run test to confirm it fails**

Run: `python -m pytest tests/test_ornstein_v2_ablation.py -v`

Expected: `ModuleNotFoundError: No module named 'tools.ornstein_v2_ablation'` (não escrevemos ainda).

- [ ] **Step 3: Write the ablation runner**

Create `tools/ornstein_v2_ablation.py`:

```python
"""Ablation runner for ORNSTEIN v2 robust preset guards.

Isolated in tools/ (not engines/) because this is research-only scaffolding.
If decision = archive, this file is deleted.

Runs 8 variants in-process (avoiding subprocess + CLI flag limitations):
    B_MAJORS       - v1 default preset, reference baseline
    R0_robust_full - full robust preset, local repro on reduced universe
    R1_no_hurst    - robust minus hurst gate (threshold back to v1 default)
    R2_no_bb       - robust minus require_bb_confirmation
    R3_no_min_dev  - robust minus min_deviation_abs
    R4_no_target_dist - robust minus min_target_distance_atr
    R5_no_div_flip - robust minus exit_on_divergence_flip
    R6_no_stop_lock - robust minus post_partial_stop_offset_atr (flag off)

Output: data/ornstein_v2/ablation_<DATE>/results.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from config.params import ACCOUNT_SIZE
from engines.ornstein import (
    ORNSTEIN_PRESETS,
    OrnsteinParams,
    run_backtest,
    save_run,
)

VARIANTS = (
    "B_MAJORS",
    "R0_robust_full",
    "R1_no_hurst",
    "R2_no_bb",
    "R3_no_min_dev",
    "R4_no_target_dist",
    "R5_no_div_flip",
    "R6_no_stop_lock",
)

V1_DEFAULT_HURST = 0.55  # matches OrnsteinParams default


def _apply_preset(params: OrnsteinParams, preset_name: str) -> None:
    for k, v in ORNSTEIN_PRESETS[preset_name].items():
        setattr(params, k, v)


def build_variant_params(variant: str) -> OrnsteinParams:
    """Return OrnsteinParams for the given ablation variant."""
    if variant == "B_MAJORS":
        return OrnsteinParams()

    if variant not in VARIANTS:
        raise KeyError(f"unknown variant: {variant}")

    p = OrnsteinParams()
    _apply_preset(p, "robust")

    if variant == "R0_robust_full":
        return p
    if variant == "R1_no_hurst":
        p.hurst_threshold = V1_DEFAULT_HURST
        return p
    if variant == "R2_no_bb":
        p.require_bb_confirmation = False
        return p
    if variant == "R3_no_min_dev":
        p.min_deviation_abs = 0.0
        return p
    if variant == "R4_no_target_dist":
        p.min_target_distance_atr = 0.0
        return p
    if variant == "R5_no_div_flip":
        p.exit_on_divergence_flip = False
        return p
    if variant == "R6_no_stop_lock":
        p.post_partial_stop_offset_atr = -1.0
        return p

    raise KeyError(f"unhandled variant: {variant}")  # unreachable


def run_one_variant(variant: str, symbols: list[str], days: int,
                    out_root: Path) -> dict:
    params = build_variant_params(variant)
    print(f"\n==== variant={variant} ====", flush=True)
    trades, summary, per_sym = run_backtest(
        symbols, params, ACCOUNT_SIZE, days=days, end=None, profile=False,
    )
    vetos = summary.pop("vetos", {})
    run_dir = out_root / variant
    run_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "variant": variant,
        "symbols": symbols,
        "days": days,
        "initial_equity": float(ACCOUNT_SIZE),
    }
    save_run(run_dir, trades, summary, params, vetos, per_sym, meta, ablation=None)

    return {
        "variant": variant,
        "n_trades": int(summary.get("total_trades", 0)),
        "sharpe": float(summary.get("sharpe", 0.0)),
        "sortino": float(summary.get("sortino", 0.0)),
        "max_dd": float(summary.get("max_drawdown", 0.0)),
        "win_rate": float(summary.get("win_rate", 0.0)),
        "expectancy_r": float(summary.get("expectancy_r", 0.0)),
        "total_pnl": float(summary.get("total_pnl", 0.0)),
        "run_dir": str(run_dir),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="ORNSTEIN v2 ablation runner")
    ap.add_argument("--symbols", default="BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT")
    ap.add_argument("--days", type=int, default=180)
    ap.add_argument("--out", default=None,
                    help="Output base dir (default: data/ornstein_v2/ablation_<DATE>)")
    ap.add_argument("--only", default=None,
                    help="Run a single variant (for retry/debug)")
    args = ap.parse_args(argv)

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    if args.out:
        out_root = Path(args.out)
    else:
        out_root = Path("data/ornstein_v2") / f"ablation_{datetime.now():%Y-%m-%d}"
    out_root.mkdir(parents=True, exist_ok=True)

    variants_to_run = [args.only] if args.only else list(VARIANTS)
    for v in variants_to_run:
        if v not in VARIANTS:
            raise SystemExit(f"unknown variant: {v}")

    rows = []
    for v in variants_to_run:
        row = run_one_variant(v, symbols, args.days, out_root)
        rows.append(row)

    csv_path = out_root / "results.csv"
    csv_mode = "a" if (args.only and csv_path.exists()) else "w"
    with open(csv_path, csv_mode, newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        if csv_mode == "w":
            w.writeheader()
        w.writerows(rows)

    print(f"\nAblation CSV written to: {csv_path}")
    print(json.dumps(rows, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_ornstein_v2_ablation.py -v`

Expected: 10/10 pass.

- [ ] **Step 5: Commit runner + test**

Run:
```bash
git add tools/ornstein_v2_ablation.py tests/test_ornstein_v2_ablation.py
git commit -m "$(cat <<'EOF'
tools(ornstein_v2): ablation runner — 8 variants, in-process

Scaffolding efêmero pra etapa 3 do protocolo de validação. Roda B_MAJORS +
7 variantes do preset robust (desligando 1 guard por vez), escreve CSV
agregado em data/ornstein_v2/ablation_<DATE>/. Se decisão = archive,
este arquivo e seu teste são deletados.

In-process (importa run_backtest/save_run de engines.ornstein) porque 4
dos 5 guards não têm CLI flag.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Execute ablation

**Files:**
- Produces: `data/ornstein_v2/ablation_2026-04-17/results.csv` + 8 run_dirs

- [ ] **Step 1: Run ablation full**

Run:
```bash
python -m tools.ornstein_v2_ablation --days 180
```

Expected: ~8-12min total (8 runs × 5 símbolos × 180d). Cada variant imprime `==== variant=<name> ====` no início. CSV final impresso.

Se um variant crashar no meio, anotar o erro. Pra retomar: `python -m tools.ornstein_v2_ablation --only <variant_name> --out data/ornstein_v2/ablation_2026-04-17` (usa o mesmo out_root; ablation CSV em append).

- [ ] **Step 2: Inspect CSV**

Run:
```bash
python -c "
import csv
with open('data/ornstein_v2/ablation_2026-04-17/results.csv', encoding='utf-8') as f:
    rows=list(csv.DictReader(f))
for r in rows:
    print(f\"{r['variant']:<20} n={r['n_trades']:>4} sharpe={float(r['sharpe']):>+6.3f} dd={float(r['max_dd'])*100:>5.1f}% wr={float(r['win_rate'])*100:>5.1f}%\")
"
```

Salvar esse output.

- [ ] **Step 3: No commit yet** (waiting for validation doc update in Task 6)

---

## Task 6: Compile ablation results + select best variant

**Files:**
- Modify: `docs/engines/ornstein_v2/2026-04-17_validation.md` (fill Etapa 3)

- [ ] **Step 1: Populate ablation table in validation doc**

Edit `docs/engines/ornstein_v2/2026-04-17_validation.md`, substituir toda a tabela de Etapa 3 pelos valores do CSV. Para coluna `Δ Sharpe vs B_MAJORS`, calcular `sharpe(variant) - sharpe(B_MAJORS)` manualmente.

- [ ] **Step 2: Select best variant**

Run:
```bash
python -c "
import csv
with open('data/ornstein_v2/ablation_2026-04-17/results.csv', encoding='utf-8') as f:
    rows=list(csv.DictReader(f))
eligible=[r for r in rows if r['variant']!='B_MAJORS' and int(r['n_trades'])>=20]
if not eligible:
    print('NO_ELIGIBLE_VARIANT: every v2 variant below N_trades>=20 threshold')
else:
    best=max(eligible, key=lambda r: float(r['sharpe'])/(1.0+float(r['max_dd'])))
    print('BEST_VARIANT=', best['variant'])
    print(f\"  n={best['n_trades']} sharpe={float(best['sharpe']):+.3f} dd={float(best['max_dd'])*100:.1f}%\")
"
```

Guardar `BEST_VARIANT`. Se `NO_ELIGIBLE_VARIANT`, pular Task 7 e ir direto pra Task 8 Branch C (archive).

- [ ] **Step 3: Document best variant in validation doc**

Substituir `Best variant ... : PLACEHOLDER` pelo nome e critério.

- [ ] **Step 4: Commit Etapa 3**

Run:
```bash
git add docs/engines/ornstein_v2/2026-04-17_validation.md
git commit -m "$(cat <<'EOF'
docs(ornstein_v2): etapa 3 ablation — 8 variants em majors/180d

Tabela completa + best variant selecionado por sharpe/(1+dd) com N>=20.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Etapa 4 — Final comparison (best variant / bluechip_active / 360d)

**Files:**
- Modify: `docs/engines/ornstein_v2/2026-04-17_validation.md` (fill Etapa 4)

**Skip this task if Task 6 Step 2 returned `NO_ELIGIBLE_VARIANT`. Go straight to Task 8 Branch C.**

- [ ] **Step 1: Run best variant on full window**

Run ONE of the following (dependendo do BEST_VARIANT do Task 6):

**Se `BEST_VARIANT=R0_robust_full`:**
```bash
python -m engines.ornstein_v2 --basket bluechip_active --days 360 --no-menu
```
(já temos — é o mesmo run da Etapa 2. Re-use o run_dir da Etapa 2.)

**Se `BEST_VARIANT=R1_no_hurst`:**
```bash
python -m engines.ornstein --preset robust --hurst-threshold 0.55 --basket bluechip_active --days 360 --no-menu --out data/ornstein_v2
```

**Se qualquer outra variant (R2-R6):** escrever override via script:
```bash
python -c "
from pathlib import Path
from datetime import datetime
from config.params import ACCOUNT_SIZE
from engines.ornstein import run_backtest, save_run, OrnsteinParams, ORNSTEIN_PRESETS
from tools.ornstein_v2_ablation import build_variant_params

variant='<BEST_VARIANT>'
params=build_variant_params(variant)
from config.params import BASKETS
symbols=BASKETS['bluechip_active']
ts=datetime.now().strftime('%Y-%m-%d_%H%M')
run_dir=Path('data/ornstein_v2')/f'{variant}_full_{ts}'
run_dir.mkdir(parents=True, exist_ok=True)
trades, summary, per_sym = run_backtest(symbols, params, ACCOUNT_SIZE, days=360, end=None, profile=False)
vetos=summary.pop('vetos',{})
meta={'variant':variant,'symbols':symbols,'days':360,'initial_equity':float(ACCOUNT_SIZE)}
save_run(run_dir, trades, summary, params, vetos, per_sym, meta, ablation=None)
print('done:', run_dir)
"
```

Substituir `<BEST_VARIANT>` pelo nome real.

Expected: ~10min. Run dir impresso no final.

- [ ] **Step 2: Compute DSR for best variant with n_trials=7**

Run:
```bash
python -c "
import json, statistics
from analysis.dsr import deflated_sharpe_ratio
run='<RUN_DIR>'
s=json.load(open(f'{run}/summary.json', encoding='utf-8'))
trades=json.load(open(f'{run}/trades.json', encoding='utf-8'))
rs=[t.get('r',0.0) for t in trades]
if len(rs)<2:
    print('DSR_SKIP: insufficient trades')
else:
    mean=statistics.fmean(rs)
    stdev=statistics.pstdev(rs) or 1e-9
    sk=statistics.fmean([(r-mean)**3 for r in rs])/(stdev**3)
    ku=statistics.fmean([(r-mean)**4 for r in rs])/(stdev**4)
    dsr=deflated_sharpe_ratio(s['sharpe'], 7, sk, ku, len(rs))
    print(f'n_trades={len(rs)} sharpe={s[\"sharpe\"]:.3f} dsr={dsr:.3f}')
"
```

Substituir `<RUN_DIR>`. Guarda sharpe e DSR.

- [ ] **Step 3: Compute DSR for baseline with n_trials=1**

(Já calculado no Task 2 Step 3 — re-use o valor armazenado no doc.)

- [ ] **Step 4: Populate Etapa 4 table**

Editar `docs/engines/ornstein_v2/2026-04-17_validation.md` — substituir `PLACEHOLDER_FINAL_RUN_DIR` e preencher tabela comparativa.

- [ ] **Step 5: Commit**

Run:
```bash
git add docs/engines/ornstein_v2/2026-04-17_validation.md
git commit -m "$(cat <<'EOF'
docs(ornstein_v2): etapa 4 final comparison — best variant / 360d

Best variant rodada em bluechip_active/360d, DSR n_trials=7 calculado.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Decide disposition + execute

**Files:**
- Depends on branch (see sub-tasks).

Aplicar a decision rule do spec:

| Condição | Branch |
|----------|--------|
| `DSR(best) > DSR(default)` **E** `N_trades(best) >= 30` **E** `Sharpe(best) > Sharpe(default) * 1.10` | **A. Promote** |
| Ablation mostra 1 guard sozinho zera sample **E** removendo ele uma variant passa critério acima | **B. Remove guard** |
| Nenhuma variant bate critério | **C. Archive** |

Preencher a seção "Decisão" do validation doc com branch escolhido + justificativa.

### Branch A — Promote

- [ ] **A.1: Se `BEST_VARIANT != R0_robust_full`**, editar `engines/ornstein.py` preset `ORNSTEIN_PRESETS["robust"]` removendo o guard que a variant venceu por desligar. Exemplo (se `R1_no_hurst`):

```python
"robust": {
    "omega_entry": 80.0,
    "halflife_min": 6.0,
    "halflife_max": 36.0,
    # "hurst_threshold": 0.42,  ← REMOVIDO via ablation (guard inalcançável em cripto)
    "adf_pvalue_max": 0.03,
    "atr_percentile_block": 85.0,
    "require_bb_confirmation": True,
    "min_bb_score": 10.0,
    "min_deviation_abs": 0.8,
    "min_target_distance_atr": 0.9,
    "post_partial_stop_offset_atr": 0.10,
    "exit_on_divergence_flip": True,
},
```

- [ ] **A.2: Stage remaining ornstein lane 1 WIP**

Run:
```bash
git add engines/ornstein.py engines/ornstein_v2.py config/engines.py tests/test_ornstein.py
```

- [ ] **A.3: Run tests**

Run: `python -m pytest tests/test_ornstein.py tests/test_ornstein_v2_ablation.py -q`

Expected: all pass.

- [ ] **A.4: Commit promote**

Run:
```bash
git commit -m "$(cat <<'EOF'
feat(ornstein_v2): promote robust preset — validated OOS edge over v1 default

Protocolo em docs/superpowers/specs/2026-04-17-ornstein-v2-validation-design.md.
Resultados em docs/engines/ornstein_v2/2026-04-17_validation.md.

Best variant: <BEST_VARIANT> bateu baseline v1 default em
bluechip_active/360d com DSR > baseline E N_trades >= 30 E
Sharpe uplift > 10%.

Preset robust final registrado com guards sobreviventes. Próximo passo:
overfit_audit 6/6 em janelas OOS distintas.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **A.5: File followup note**

Adicionar ao top do validation doc:
```markdown
> **Follow-up:** rodar `tools/ornstein_overfit_audit.py` em janelas OOS
> adicionais (6 splits) antes de considerar `stage=validated` em
> `config/engines.py`.
```

Commit:
```bash
git add docs/engines/ornstein_v2/2026-04-17_validation.md
git commit -m "docs(ornstein_v2): flag overfit_audit 6/6 as next step"
```

**Jump to Task 9.**

### Branch B — Remove guard

- [ ] **B.1: Editar preset `ORNSTEIN_PRESETS["robust"]`** em `engines/ornstein.py` removendo SÓ o guard identificado pela ablation como "zera sample estruturalmente". Manter os demais.

- [ ] **B.2: Re-rodar best-without-that-guard em bluechip_active/360d** (mesma mecânica do Task 7).

- [ ] **B.3: Re-aplicar decision rule** com novo best. Se agora passa → volta pra Branch A. Se ainda não passa → Branch C (archive — regra de parada, sem mais iterações).

### Branch C — Archive

Approach: Lane 1 (ornstein_v2) changes were never committed, so we use `git checkout HEAD --` to revert tracked files and `rm` for the untracked `engines/ornstein_v2.py`. The ablation scaffolding WAS committed in Task 4, so it needs `git rm`.

- [ ] **C.1: Revert tracked Lane 1 files**

Run:
```bash
git checkout HEAD -- engines/ornstein.py config/engines.py tests/test_ornstein.py
```

Isso restaura esses 3 arquivos ao estado do commit inicial de ornstein v1 (`a1fb95e`) — apaga os 5 params novos, preset `robust`, lógica dos guards, 3 testes novos, entry `ornstein_v2` no registry.

- [ ] **C.2: Delete untracked wrapper**

Run: `rm engines/ornstein_v2.py`

- [ ] **C.3: Delete committed ablation scaffolding**

Run:
```bash
git rm tools/ornstein_v2_ablation.py tests/test_ornstein_v2_ablation.py
```

- [ ] **C.4: Check that ornstein.main() signature doesn't break anything**

A `main(argv, *, default_preset, default_out)` signature foi adicionada com Lane 1 e será revertida no step C.1. Verificar que nada fora de Lane 1 dependia dela:

Run: `grep -rn "ornstein_main\|default_preset=\|default_out=" --include="*.py" .`

Expected: zero hits fora de files já removidos.

- [ ] **C.5: Run full test suite**

Run: `python -m pytest tests/test_ornstein.py -q`

Expected: pass (agora sem os 3 testes removidos).

Smoke geral:
```bash
python -m pytest tests/ -q --ignore=tests/_tmp 2>&1 | tail -20
```

Expected: sem regressões vs branch inicial.

- [ ] **C.6: Stage archive**

Run:
```bash
git status --short
```

Expected:
```
D  engines/ornstein_v2.py   (untracked delete — pode aparecer só como "?? " sumindo)
D  tools/ornstein_v2_ablation.py
D  tests/test_ornstein_v2_ablation.py
```

Nenhum `M` em engines/ornstein.py, config/engines.py, tests/test_ornstein.py (já revertidos).

- [ ] **C.7: Commit archive**

Run:
```bash
git commit -m "$(cat <<'EOF'
revert(ornstein): archive v2 robust preset — failed honest OOS validation

Protocolo em docs/superpowers/specs/2026-04-17-ornstein-v2-validation-design.md.
Resultados em docs/engines/ornstein_v2/2026-04-17_validation.md.

O preset robust + wrapper ornstein_v2.py foram adicionados na sessão
2026-04-17 sem validação OOS prévia. Codex rodou no universo completo e
obteve 0 trades; ablation subsequente em majors/180d confirmou que os 5
guards novos não entregam edge real vs v1 default (critério:
DSR > baseline, N_trades >= 30, Sharpe uplift >= 10%).

Per anti-overfit protocol (regra 5: regra de parada honrada), arquivando
a variante sem reformular universo/janela/thresholds.

Removido:
- 5 campos de OrnsteinParams (require_bb_confirmation, min_bb_score,
  post_partial_stop_offset_atr, exit_on_divergence_flip, min_deviation_abs,
  min_target_distance_atr)
- preset "robust" de ORNSTEIN_PRESETS
- lógica associada em _resolve_ornstein_exit e scan_symbol
- engines/ornstein_v2.py (wrapper)
- entry "ornstein_v2" em config/engines.py
- 3 testes em tests/test_ornstein.py
- tools/ornstein_v2_ablation.py + teste (scaffolding efêmero)

Mantidos:
- engines/ornstein.py core (v1) intacto, segue research-only.
- docs/engines/ornstein_v2/2026-04-17_validation.md permanece como
  registro histórico da validação.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

**Continue to Task 9.**

---

## Task 9: Close-out

**Files:**
- Modify: `docs/days/2026-04-17.md` (daily log append)
- Create: `docs/sessions/2026-04-17_<HHMM>.md` (session log)

- [ ] **Step 1: Update memory — engine status**

Atualizar `C:\Users\Joao\.claude\projects\C--Users-Joao-OneDrive-aurum-finance\memory\project_engine_status_2026_04_16_oos.md` com resultado do v2 (promote/archive). Adicionar nota "ornstein v2 validated 2026-04-17 → [decisão]".

- [ ] **Step 2: Write session log**

Criar `docs/sessions/2026-04-17_<HHMM>.md` no formato da CLAUDE.md (Resumo, Commits, Mudanças Críticas, Achados, Estado do Sistema, Arquivos Modificados, Notas para o Joao). Destacar decisão de promote/archive como Mudança Crítica.

- [ ] **Step 3: Append to daily log**

Editar `docs/days/2026-04-17.md`, adicionar sessão no topo de "Sessões do dia" e atualizar consolidados.

- [ ] **Step 4: Final commit**

Run:
```bash
git add docs/sessions/2026-04-17_<HHMM>.md docs/days/2026-04-17.md
git commit -m "$(cat <<'EOF'
docs(sessions): 2026-04-17_<HHMM> ornstein v2 validation closeout

Session log + daily log append. Decisão: [promote|archive].

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 5: Verify branch state**

Run: `git log --oneline -15`

Expected: últimos commits em ordem:
1. hardening: run_manager + vps + cockpit (Task 0)
2. docs(ornstein_v2): validation report skeleton (Task 1)
3. docs(ornstein_v2): etapa 1 baseline (Task 2)
4. docs(ornstein_v2): etapa 2 reprodução (Task 3)
5. tools(ornstein_v2): ablation runner (Task 4)
6. docs(ornstein_v2): etapa 3 ablation (Task 6)
7. docs(ornstein_v2): etapa 4 final comparison (Task 7)
8. Uma de: `feat(ornstein_v2): promote` OU `revert(ornstein): archive v2` (Task 8)
9. docs(sessions): 2026-04-17 closeout (Task 9)

Run: `git status`

Expected: working tree clean (exceto `docs/audits/2026-04-17_claude_codex_summary.md` untracked — fora do escopo).

---

## Self-Review Notes

Cobertura do spec:

- ✓ Etapa 0 (spec) → Task 0
- ✓ Etapa 1 (spec) → Tasks 1, 2
- ✓ Etapa 2 (spec) → Task 3
- ✓ Etapa 3 (spec) → Tasks 4, 5, 6
- ✓ Etapa 4 (spec) → Task 7
- ✓ Decision matrix (spec) → Task 8 (3 branches)
- ✓ Archive actions (spec) → Task 8 Branch C (7 sub-steps cobrem os 6 pontos do spec via `git checkout` + `git rm`)
- ✓ Anti-overfit guarantees → embutidos nos critérios do Task 8 + comentários do ablation runner

Placeholders:
- `<BEST_VARIANT>` — marker explícito, substituído em runtime.
- `<RUN_DIR>` — marker explícito, substituído em runtime.
- `<HHMM>` — marker explícito, substituído em runtime.
- Nenhum TBD/TODO no corpo dos steps.

Type consistency:
- `build_variant_params(name) -> OrnsteinParams` — consistente entre Task 4 (implementação) e Task 7 (re-uso em override script).
- Preset name `"robust"` — consistente.
- Variant names — consistentes entre `VARIANTS` tuple (Task 4), test assertions (Task 4), CSV rows (Tasks 5, 6), decision switch (Task 7, 8).

Ambiguidade:
- Task 8 branch selection deixa critério explícito em tabela. Sem wiggle room.
- Task 7 Step 1 tem 3 caminhos de comando conforme BEST_VARIANT — todos escritos por extenso.
