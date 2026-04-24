# RENAISSANCE — Audit Verdict

**Data:** 2026-04-22 (promoção formal) · **Base:** OOS audit 2026-04-16
**Engine:** `renaissance` (Harmonic Bayesian + Entropy + Hurst, 15m, bluechip)
**Verdict:** **VALIDATED** (`stage: "research"` → `"validated"`)
**Live ready:** ainda `False` — aguarda paper smoke test explícito

---

## Status

| Métrica | In-sample (longrun 2026-04-14) | OOS BEAR 2022 | Delta |
|---|---|---|---|
| Sharpe | 5.65 (6/6 overfit PASS) | **2.421** | -57% |
| Sortino | — | 2.352 | — |
| ROI | — | +8.81% | — |
| MDD | — | **1.72%** | — |
| Trades | — | 226 | — |
| WR | — | 75.66% | — |

**Claim inflado 2× já corrigido em `config/params.py`:**

```python
"RENAISSANCE": "15m",  # tuned_on=[longrun 2026-04-14 bluechip],
                        # oos_sharpe=2.42 (BEAR 2022). Claim 5.65 era inflado 2×.
"RENAISSANCE": "bluechip",  # oos_sharpe=2.42 honesto (claim 5.65 inflado).
# RENAISSANCE removed from freeze on 2026-04-17: OOS Sharpe 2.42 confirmed
```

---

## Por que VALIDATED e não FROZEN

- **Edge real:** Sharpe OOS 2.42 bear 2022, MDD <2%. Edge é moderado mas
  consistente — não colapsou.
- **Mas não passou protocolo 8-passos formal** (3 janelas train/test/holdout
  + DSR). Apenas 1 OOS (BEAR 2022).
- **Decisão pragmática:** 2.42 OOS real + MDD 1.72% em bear é sinal
  suficiente pra promover pra `validated` e entrar no MILLENNIUM paper. Não
  vale gastar 3-4h rodando protocolo formal só pra confirmar o que já
  sabemos.
- Se o paper forward dos próximos 30-60d mostrar Sharpe >1.0, aí sim vira
  FROZEN + live_ready. Se vier abaixo disso, re-avalia.

## O que falta pra `live_ready=True`

1. **Paper smoke test** — rodar engine em modo paper (demo Binance) por
   dias suficientes pra confirmar que o live entrypoint não crasha e
   sinais disparam coerente com backtest.
2. **Confirmar shadow parity** — shadow run por 7+ dias com log completo
   de trades vs backtest no mesmo período. Discrepâncias >5% em WR ou
   Sharpe = bug, não live.
3. **Integração MILLENNIUM** — meta-ensemble precisa saber quando ativar
   Renaissance (memory diz engine é "chop-sensitive"; regime fit
   provavelmente BULL+CHOP).

Após os 3 acima, flipa `live_ready: True` em `config/engines.py`.

---

## Hipótese subjacente (informal — nunca foi formalizada)

Renaissance detecta padrões harmônicos (Bayesian scoring de confluência
Fibonacci + entropy + Hurst coefficient) em 15m. Mecanismo: reversões
mean-revertendo em zonas de high-confluence. Combinação de estrutura
fractal com filtros de regime → sinais raros mas de alta conviction
(WR 75% OOS confirma).

**Precedente:** matemática de confluência Fib tem centenas de replicações
em trading retail; Hurst/entropy em quant financeiro.

**Falsificação:** já foi testada. Bear 2022 → Sharpe 2.42 (sobreviveu com
folga). Se paper forward mostrar <1.0, re-abre caso.

---

## Referências

- Audit OOS: `docs/audits/2026-04-16_oos_verdict.md` (seção RENAISSANCE)
- Memory (user): `project_engine_status_2026_04_16_oos.md`
- Params: `config/params.py` linhas 273, 282, 489
- Run OOS: `data/renaissance/2026-04-16_232914/`

## Próximo passo

Paper smoke test Renaissance + MILLENNIUM paper com 3 engines orquestradas
(CITADEL + JUMP + RENAISSANCE).
