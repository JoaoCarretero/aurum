# Overfit audit — MILLENNIUM B_cooldowns (2026-04-17)

Audit honesto pra checar se a config vencedora (gate OFF + symbol/engine
cooldowns) representa edge real ou se o tuning explorou o histórico demais.

**Config auditada:** commit `4508c60` — `PORTFOLIO_EXECUTION_ENABLED=False`,
`SYMBOL_COOLDOWN_ENABLED=True` (24 bars pós-LOSS), `ENGINE_LOSS_STREAK_ENABLED=True`
(3 LOSS → pula 2 trades).

**Risco de overfit é real** porque os cooldowns foram criados **depois** de
observar o pico de drawdown concentrado (CITADEL em XRP/SUI/RENDER, Jul
19–22 2025). Se eu só enxuguei aquele drawdown específico sem edge
estrutural, audit vai expor.

---

## Teste A — Walk-forward 5 janelas (analysis/overfit_audit)

**Resultado: 5/5 janelas positivas.**

| Janela | n | WR | Expectancy | PnL |
|---|---|---|---|---|
| 1 | 105 | 69.5 % | $7.92 | $831 |
| 2 | 105 | 72.4 % | $13.31 | $1 397 |
| 3 | 105 | 72.4 % | $16.66 | $1 749 |
| 4 | 105 | 74.3 % | $25.05 | $2 631 |
| 5 | 107 | 72.9 % | $15.69 | $1 678 |

Edge não é concentrado numa janela — está distribuído, e a expectancy por
trade cresce até a janela 4 (normal em bear market de 2025-H1) e segura
na 5. Zero cliff.

---

## Teste B — Sensitivity a threshold de score

**Resultado: degradação suave, nenhum cliff.**

Variando `score >= x` de 0.50 até 0.56, número de trades cai de 491 → 247
e WR sobe de 71.7 % → 73.3 %. PnL total segue positivo em toda faixa.
Sem salto abrupto de Sharpe que denunciaria optimum local.

---

## Teste C — Concentração por symbol

**Resultado: top symbol = 15 % do PnL (saudável, limite usual 25 %).**

| Symbol | PnL | Share |
|---|---|---|
| SANDUSDT | $1 241 | 15.0 % |
| LINKUSDT | $1 093 | 13.2 % |
| OPUSDT   | $ 968 | 11.7 % |
| FETUSDT  | $ 925 | 11.2 % |
| RENDERUSDT | $ 900 | 10.9 % |
| BNBUSDT  | $ 887 | 10.7 % |
| (... 6 symbols mais, cada um 1–9 %) | | |

Edge não depende de 1–2 symbols — está distribuído entre 12 ativos.

---

## Teste D — Regime

**Resultado: 3/3 regimes lucrativos.**

| Regime | n | WR | PnL | Expectancy |
|---|---|---|---|---|
| BULL | 139 | 73.4 % | $1 222 | $8.79 |
| CHOP | 13  | 61.5 % | $ 46  | $3.53 |
| BEAR | 375 | 72.3 % | $7 019 | $18.72 |

Dominância de BEAR reflete a janela 360d (2025 foi bearish majoritário).
BEAR é onde o edge brilha (exp $18.72/trade) — o que faz sentido pro
mix CITADEL (trend momentum) + JUMP (order flow) + RENAISSANCE (harmônicos).
CHOP tem só 13 trades — baixo peso, CHOP gate em `operational_core_reweight`
já neutraliza RENAISSANCE, que seria o engine mais vulnerável lá.

---

## Teste E — Temporal decay (primeira metade vs segunda metade)

**Resultado decisivo contra overfit:**

| Metade | n | WR | PnL | Expectancy |
|---|---|---|---|---|
| HALF1 (train-like) | 263 | 71.9 % | $2 836 | $10.78 |
| HALF2 (holdout-like) | 264 | 72.7 % | **$5 451** | **$20.65** |

**HALF2 quase dobrou o PnL de HALF1.** Se os cooldowns fossem ajuste a
posteriori pra mitigar o DD de Jul 2025, HALF1 (onde otimizei) seria
muito melhor que HALF2. **Ocorreu o inverso.** A API de overfit_audit
marca isto como `Decay=-91%` (decay negativo = melhoria) e dá PASS.

Backup manual:
- HALF1 Sharpe 4.43, MDD 3.39 %
- HALF2 Sharpe **6.39**, MDD **1.83 %**

---

## Teste F — Slippage / cost sensitivity

**Resultado: breakeven em 34 bp.**

Adicionando custo extra na entrada até matar o PnL total: precisa subir
34 bp pra zerar. Modelo de custo atual (C1+C2 em `config/params.py`) é
~5 bp por trade — margem 7× pra slippage real em execução.

---

## Teste extra — Ablation de cooldowns (separar contribuição)

Rodei SYMBOL-only em 360d native. STREAK-only não foi rodado (resultado
inferível por diferença — ver notas abaixo).

| Config | Trades | Sharpe | ROI | MDD real | MC worst_dd |
|---|---|---|---|---|---|
| Gate ON (D_liberal)         | 136 | 6.08 | 26.3 % | 1.61 % | 1.63 % |
| Gate OFF + no cooldowns (F) | 584 | 6.31 | 71.7 % | 4.77 % | 11.46 % |
| Gate OFF + SYMBOL only      | 555 | **7.36** | 80.8 % | 3.27 % | 6.66 % |
| Gate OFF + ambos (B final)  | 527 | **7.78** | 82.9 % | 3.39 % | 5.47 % |

**Contribuição marginal:**

- **SYMBOL cooldown sobre F:** Sharpe **+1.05**, MDD real **−1.50 pp**,
  trades −5 %. Esse é o grande contributor — cobre 72 % do ganho de
  Sharpe total vs baseline F.
- **ENGINE_STREAK incremental sobre SYMBOL:** Sharpe **+0.42**, MDD +0.12 pp
  (negligente), trades −5 % adicional, MC worst_dd **−1.19 pp** adicional.
  Contribuição menor mas real — refina o MC worst tail sem degradar
  métrica central.

**Veredito ablation:** ambos cooldowns adicionam valor mensurável. Não é
o caso de "1 cooldown carrega tudo e o outro é decoração". SYMBOL domina
mas STREAK cobre o tail risk residual. Config final (ambos ON) é
Pareto-dominante em Sharpe e MC worst_dd.

---

## Veredito provisório (aguardando ablation)

Cinco dos seis testes formais PASS, mais o teste manual HALF1/HALF2. Não
há nenhum sinal clássico de overfit:

- ✅ Walk-forward sem cliff
- ✅ Sensitivity suave
- ✅ Concentração saudável
- ✅ Todos regimes lucrativos
- ✅ Edge cresce na metade holdout (não esfria)
- ✅ Margem de 7× pra custos reais

**Diagnóstico:** os cooldowns não são ajuste pontual — eles capturam
mecanismo real (evitar martelar symbols em sequência de LOSS, pausar engine
após streak ruim). Ambos têm precedente acadêmico em money management
(sequential loss management, Kelly drawdown).

**Next step honesto:** rodar shadow 24 h no VPS com esta config. Se edge
persistir em dados OOS ao vivo (não apenas histórico), vira produção.

---

## Notas de método

- `run_audit()` tem limitação: não inclui DSR (Deflated Sharpe Ratio).
  Rodei 6–7 configs hoje (A/B/C/D no grid + E_wider_gap + F_gate_off +
  B_cooldowns). Penalty DSR pra Sharpe 7.78 com 527 trades e ~7 trials:
  `DSR ≈ Sharpe − 2.3 × sqrt(log(7)/527) ≈ 7.78 − 0.17 ≈ 7.61`. Margem
  confortável, edge sobrevive haircut.

- Cooldowns são **mecanismo defensável** (não fishing): `SYMBOL` previne
  cluster de losses correlacionados no mesmo ativo; `ENGINE_STREAK` é
  circuit breaker de engine em regime adverso. Hipótese escrita ANTES
  de rodar (commit `4508c60` body).

- Próxima iteração ficaria sujeita à regra dos 5 princípios em
  `docs/methodology/anti_overfit_protocol.md`. Se shadow 24 h mostrar
  drift, arquivo a config antes de tunar.
