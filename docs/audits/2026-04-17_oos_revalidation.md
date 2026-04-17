# OOS Revalidation Gate — 2026-04-17

Generated: `2026-04-17T09:25:03`

Baseline source: persisted runs cited in `docs/audits/2026-04-16_oos_verdict.md`.

## Reproducibility

| Engine | Regime | Match | Sharpe baseline | Sharpe fresh | Field fails |
| --- | --- | --- | --- | --- | --- |
| CITADEL | BEAR | PASS | 5.677 | 5.677 | 0 |
| RENAISSANCE | BEAR | PASS | 2.421 | 2.421 | 0 |
| JUMP | BEAR | PASS | 3.15 | 3.15 | 0 |
| DE SHAW | BEAR | PASS | -1.726 | -1.726 | 0 |
| BRIDGEWATER | BEAR | FAIL | 11.04 | 11.237 | 10 |
| KEPOS | BEAR | PASS | 0.0 | 0.0 | 0 |
| MEDALLION | BEAR | FAIL | -3.218 | -3.218 | 1 |

## Cost Symmetry

### Static token presence (all 4 cost components referenced per engine)

| Engine | All cost tokens present | Found | Scanned files | Suspicious lines |
| --- | --- | --- | --- | --- |
| CITADEL | yes | SLIPPAGE, SPREAD, COMMISSION, FUNDING_PER_8H | engines\citadel.py | — |
| RENAISSANCE | yes | SLIPPAGE, SPREAD, COMMISSION, FUNDING_PER_8H | core\harmonics.py, engines\renaissance.py | — |
| JUMP | yes | SLIPPAGE, SPREAD, COMMISSION, FUNDING_PER_8H | engines\jump.py | — |
| DE SHAW | yes | SLIPPAGE, SPREAD, COMMISSION, FUNDING_PER_8H | engines\deshaw.py | — |
| BRIDGEWATER | yes | SLIPPAGE, SPREAD, COMMISSION, FUNDING_PER_8H | engines\bridgewater.py | — |
| KEPOS | yes | SLIPPAGE, SPREAD, COMMISSION, FUNDING_PER_8H | engines\kepos.py | — |
| MEDALLION | yes | SLIPPAGE, SPREAD, COMMISSION, FUNDING_PER_8H | engines\medallion.py | — |

### Entry/exit application asymmetry (deeper read)

Tokens referenced ≠ tokens applied to both sides of a trade. Reading
each engine's PnL math:

| Engine | Entry slip+spread | Exit slip+spread | Commission | Funding | Verdict |
| --- | --- | --- | --- | --- | --- |
| CITADEL | ✓ (baked in `calc_levels`) | ✓ | ✓ | ✓ | OK |
| RENAISSANCE | ✓ (baked) | ✓ | ✓ | ✓ | OK |
| JUMP | ✓ (baked) | ✓ | ✓ | ✓ | OK |
| DE SHAW | ✓ (explicit) | ✓ | ✓ | ✓ | OK |
| BRIDGEWATER | ✓ (baked) | ✓ | ✓ | ✓ | OK |
| **KEPOS** | **✗ MISSING** | ✓ | ✓ | ✓ | **BUG-SUSPECT** |
| **MEDALLION** | **✗ MISSING** | ✓ | ✓ | ✓ | **BUG-SUSPECT** |

Evidence:
- `engines/kepos.py:260` — `entry = float(df["open"].iloc[t + 1])`: raw
  next-bar open, sem aplicação de SLIPPAGE+SPREAD no entry.
- `engines/medallion.py:438` — mesma linha, mesma ausência. Comentário
  inline diz "Identical to citadel/kepos — intentional" mas é enganoso:
  CITADEL baka slip dentro de `calc_levels` antes de passar adiante,
  KEPOS/MEDALLION passam open cru.
- `_pnl_with_costs()` em ambos aplica `slip_exit = SLIPPAGE + SPREAD`
  só no lado de saída e `COMMISSION` duas vezes. Entry é subestimado em
  ~0.03% por trade.

**Implicação:** o Sharpe in-sample inflado de KEPOS e MEDALLION é em
parte produto desse viés de custo (cada trade parece 3 bps mais
lucrativo do que seria com entry slip simétrico). Fix é tarefa separada
sob protocolo CORE — NÃO aplicar sem aprovação do Joao.

Evidência completa em `docs/audits/_revalidation_costs.txt`.

## Multi-Window Summary

| Engine | Regime | Sharpe | Sortino | ROI% | Trades |
| --- | --- | --- | --- | --- | --- |
| CITADEL | BEAR | 5.677 | 8.606 | 45.590 | 240 |
| RENAISSANCE | BEAR | 2.421 | 2.352 | 8.810 | 226 |
| JUMP | BEAR | 3.150 | 6.156 | 16.360 | 110 |
| DE SHAW | BEAR | -1.726 | -1.571 | -28.340 | 1819 |
| BRIDGEWATER | BEAR | 11.237 | 20.505 | 256.000 | 7564 |
| KEPOS | BEAR | 0.000 | 0.000 | 0.000 | 0 |
| MEDALLION | BEAR | -3.218 | -9.033 | -38.120 | 173 |

## Look-Ahead Scan

### Narrow scan (integrated in `tools/oos_revalidate.py`)

Regex estrito (`iloc[ i +`, só variável `i`): nenhum hit direto em nenhum
engine ou módulo core. Base negativa.

### Broader scan (`tools/lookahead_scan.py`)

Regex mais largo `iloc\s*\[\s*\w+\s*\+\s*\d+\]` captura também `iloc[t+1]`
usado nos engines KEPOS/MEDALLION. **9 hits totais, 9 classificados OK,
0 LEAK**:

| File | Hits | Classificação |
| --- | --- | --- |
| `engines/citadel.py` | 1 | OK (display/reporting, não decisão) |
| `engines/kepos.py` | 4 | OK (execução `open[t+1]` + slice pandas) |
| `engines/medallion.py` | 2 | OK (idem) |
| `core/signals.py` | 2 | OK (`idx+1` = próxima barra de execução) |
| renaissance, jump, deshaw, bridgewater, indicators, portfolio, htf, harmonics | 0 | clean |

Classificação detalhada inline em `docs/audits/_revalidation_lookahead.txt`.
Padrão dominante: `iloc[t+1]` em engines para ler `open[t+1]` como preço
de execução — arquiteturalmente correto (sinal decidido na barra `t`,
trade executa na abertura da `t+1`).

**Veredito look-ahead:** nenhum leak confirmado em nenhum engine.

## Methodology Risks

### CITADEL
- No additional engine-specific methodology risk detected by static scan.

### RENAISSANCE
- No additional engine-specific methodology risk detected by static scan.

### JUMP
- No additional engine-specific methodology risk detected by static scan.

### DE SHAW
- No additional engine-specific methodology risk detected by static scan.

### BRIDGEWATER
- LIVE_SENTIMENT_UNBOUNDED: funding/OI/LS fetches have no historical end/start parameter.

### KEPOS
- No additional engine-specific methodology risk detected by static scan.

### MEDALLION
- No additional engine-specific methodology risk detected by static scan.

## Final Revised Verdict

| Engine | Verdict |
| --- | --- |
| CITADEL | EDGE_DE_REGIME |
| RENAISSANCE | EDGE_DE_REGIME |
| JUMP | EDGE_DE_REGIME |
| DE SHAW | NO_EDGE_OU_OVERFIT |
| BRIDGEWATER | INVALID_OOS_LIVE_SENTIMENT |
| KEPOS | INSUFFICIENT_SAMPLE |
| MEDALLION | NO_EDGE_OU_OVERFIT |

## Deflated Sharpe Ratio (DSR) tooling

Função disponível em `analysis/dsr.py`:

```python
from analysis.dsr import deflated_sharpe_ratio
dsr = deflated_sharpe_ratio(
    sharpe=3.15,       # JUMP OOS BEAR
    n_trials=35,       # estimativa conservadora de iter_* trail
    skew=0.0,          # assume Gaussiano (refinar se trades.json disponível)
    kurtosis=3.0,
    n_obs=110,         # n_trades
)
```

Uso pretendido: aplicar em CITADEL e JUMP em cada janela OOS (BEAR/BULL/CHOP)
pós-multi-window runs. DSR > 0.95 confirma edge robusto; < 0.5 invalida
claim. Estimativa de `n_trials` pra pegar em git log + `iter_N WINNER` em
`config/params.py`.

Testes: `tests/test_dsr.py` (7/7 pass).

## Notes

- Reproducibility tolerance: `±0.1%` on normalized summary fields.
- `KEPOS` and `MEDALLION` use nested payloads in `summary.json`; the tool unwraps `summary` and enriches `period_days`, `interval`, and `basket` from `meta`/`params`.
- Missing baseline windows stay available for future expansion.
- **Multi-window (BULL 2020-07..2021-07 + CHOP 2019-06..2020-03) ainda pendente.** Orchestrator enhanced owns runs; veredito atual é provisório baseado em 1 janela (BEAR).
- **Co-autoria:** findings integrados desta sessão são fruto de trabalho paralelo entre Claude (cost asymmetry KEPOS/MEDALLION, broader look-ahead scan + classificação, DSR tooling) e Codex (pipeline integrado em `tools/oos_revalidate.py`, root cause BRIDGEWATER `LIVE_SENTIMENT_UNBOUNDED`, summary nested unwrap).
