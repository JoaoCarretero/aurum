# AURUM PHI — Design Spec
**Data:** 2026-04-16
**Status:** Draft (aguardando review final do João antes de writing-plans)
**Engine ID:** `PHI`
**Classificação:** Backtest-first (fora de `FROZEN_ENGINES` até passar overfit_audit 6/6)

---

## 1. Contexto & Objetivo

PHI é o último engine do roadmap AURUM antes de consolidar a bateria. É uma
estratégia de **Fibonacci puro multi-fractal**: busca confluências de retração
0.618 em 5 timeframes simultâneos (1D / 4H / 1H / 15m / 5m) e executa quando
um Golden Trigger dispara no TF de execução (5m).

**Hipótese:** quando múltiplas camadas fractais concordam sobre um nível
Fibonacci (0.618 golden ratio) e o preço mostra rejeição forte no TF micro,
existe um edge mensurável contra pullbacks aleatórios.

**Saída esperada:** ou PHI passa overfit_audit 6/6 e entra na bateria oficial,
ou vira anti-padrão documentado (como KEPOS/GRAHAM) e o engine é arquivado.
Nos dois casos, o conhecimento fica.

---

## 2. Restrições & Invariantes

### CORE protegido (não tocar)
- `core/indicators.py`, `core/signals.py`, `core/portfolio.py`, `config/params.py`
- Indicadores (ATR, RSI, BB, ADX, EMA) são **recomputados localmente** dentro
  do engine, igual GRAHAM/KEPOS fazem. Nada de `from core.indicators import *`.

### Cost model
- Usa `TOTAL_ROUNDTRIP_COST` e `FUNDING_PER_8H` de `config.params` (C1+C2
  unificado). Não reimplementa custos.

### Sem lookahead
- Pivots de swing só contam como confirmados após N=2 barras à direita.
- HTFs forward-filled usando apenas candles **fechados** (shift de 1 barra HTF).

### Fibonacci puro
- Todo threshold numérico vem da série Fibonacci. Explicitamente:
  `0.236, 0.382, 0.500, 0.618, 0.786, 1.000, 1.272, 1.618, 2.618`
- Exceções documentadas: percentis estatísticos (`BB_width > p38.2`) usam
  lookback rolling; `ADX > 23.6` é Fibonacci (23.6% ≈ retração Fib).

---

## 3. Arquitetura

### 3.1 Arquivo
- **Novo:** `engines/phi.py` (~800-1000 linhas, self-contained)
- **Padrão:** espelhar layout de `engines/graham.py`:
  - `@dataclass PhiParams` com todos os thresholds Fib
  - `compute_features(df, params)` — ATR, RSI, BB, ADX, EMA200, zigzag, fibs
  - `detect_cluster(frames, t, params)` — lógica multi-TF
  - `decide_direction(...)`, `calc_levels(...)`, `update_trailing_stop(...)`
  - `scan_symbol(...)`, `run_backtest(...)`, `compute_summary(...)`
  - `main()` com `argparse` — CLI análogo ao GRAHAM

### 3.2 Registro
- `config/engines.py`: adicionar `PHI` ao registry
- **Fora de:** `FROZEN_ENGINES`, `ENGINE_INTERVALS`, `ENGINE_BASKETS`
- Só entra nessas listas depois do audit 6/6

### 3.3 Output
- `data/phi/{YYYY-MM-DD_HHMM}/` contendo:
  - `summary.json` — métricas agregadas (compat com `tools/reconcile_runs.py`)
  - `trades.json` — lista de trades serializáveis (schema compat com
    `overfit_audit` — confirmado no fix de 1ff8b18)
  - `config.json` — snapshot dos `PhiParams` usados
  - `logs/phi.log`

---

## 4. Pipeline de Dados

### 4.1 Fetch
- 5 TFs via `core.data.fetch_all`: `1d`, `4h`, `1h`, `15m`, `5m`
- Cache OHLCV local (implementado em ac4c276) é reaproveitado
- Universo: `UNIVERSE` padrão do AURUM (11 altcoins USDT)
- Janela: 2 anos rolling (mesmo padrão de GRAHAM/KEPOS)

### 4.2 Alinhamento
- Loop primário no **5m** (Ω5 = TF de execução)
- Para cada barra 5m no timestamp `t`:
  - `Ω1 (1D)`, `Ω2 (4H)`, `Ω3 (1H)`, `Ω4 (15m)` obtidos via forward-fill
    do último candle HTF **fechado** em `t`
  - Implementação: precompute `asof` merge usando `pd.merge_asof` com
    `direction='backward'` e `tolerance` apropriado
- Zero lookahead: se um candle 1D ainda não fechou, usa o de ontem

---

## 5. Zigzag & Fibonaccis por TF

### 5.1 Zigzag rolling
- Threshold por TF: `2.0 × ATR(14) / price` (spec literal)
- Algoritmo: percorre barras sequencialmente mantendo estado
  `(last_pivot_type, last_pivot_price, last_pivot_idx)`
- Pivot candidato = novo extremo relativo ao último pivot; vira **confirmado**
  depois de N=2 barras sem ser superado
- Saída por TF: array `(pivot_idx, pivot_price, pivot_type)` atualizado
  incrementalmente

### 5.2 Níveis Fibonacci
- Por TF, a cada barra: pega os **dois últimos pivots confirmados** (high→low
  ou low→high) e calcula:
  - Retrações: `0.382, 0.500, 0.618, 0.786` do range
  - Extensões: `1.000, 1.272, 1.618, 2.618` projetadas além do pivot final
- Expõe como `fib_levels[tf] = {0.382: price, 0.500: price, ...}`

---

## 6. PHI_CLUSTER

A cada barra 5m:
- Para cada TF ∈ {1D, 4H, 1H, 15m, 5m}: verificar se `|close - fib_0.618[tf]| < 0.5 × ATR(14, 5m)`
- `confluences = count of TFs that pass`
- **Cluster ativo** se `confluences ≥ 3`
- **Janela de validade:** o cluster permanece ativo por até **3 candles 5m**
  após a barra de detecção (implementado como `cluster_expiry_idx = t + 3`)
- Direção do cluster: determinada pela direção do swing dominante dos TFs
  confirmados (majority vote do último swing de cada TF contribuinte)

---

## 7. Scoring

### 7.1 Componentes
- **Phi_Score** ∈ [0, 1]
  - `(confluences / 5) × rejection_strength × trend_alignment`
  - `rejection_strength` = `wick / body` do candle **15m atual**, clamp [0, 1]
    via `min(wick/max(body, ε), 1.0)`
  - `trend_alignment`:
    - 1.0 se `EMA200_slope(1D) · EMA200_slope(4H) > 0` (mesmo sinal)
    - 0.5 se um é zero/flat (|slope| < tol)
    - 0.0 se sinais opostos

- **Rejection** = `rejection_strength` (reusa o termo do Phi_Score)
- **Volume** = 1 se `volume_5m > MA(20, 5m) × 1.272`, senão 0
- **Trend** = `trend_alignment` (reusa)
- **Regime** = 1 se todos os 3 gates de regime passam, senão 0

### 7.2 Fórmula mestra
```
Ω_PHI = 0.382·Phi_Score + 0.236·Rejection + 0.146·Volume + 0.146·Trend + 0.090·Regime
```
(Os pesos somam 1.000 — todos Fibonacci ratios.)

**Condição de entrada:** `Ω_PHI ≥ 0.618` **AND** Golden Trigger ativo
**AND** cluster dentro da janela de 3 candles.

---

## 8. Regime & Golden Trigger

### 8.1 Gates de Regime (todos devem passar, no 15m)
- `ADX(14) > 23.6`
- `BB_width(20, 2σ) > percentil_38.2` (rolling window 500 barras)
- `|close - EMA(200)| / ATR(14) > 0.618`

### 8.2 Regime-aware direction
- Macro regime detectado via `EMA200_slope(1D)`:
  - BULL (slope positivo forte) → só LONG
  - BEAR (slope negativo forte) → só SHORT
  - RANGE (|slope| < tol) → ambos permitidos, size × 0.618

### 8.3 Golden Trigger (no 5m, dentro da janela do cluster)
Todos devem passar:
- Pavio do candle 5m ≥ 61.8% do range do candle
- `volume_5m > MA(20, 5m) × 1.272`
- `RSI(14, 5m) < 38.2` (LONG) ou `> 61.8` (SHORT)

---

## 9. Sizing (Golden Convex)

```python
risk_usd = equity × 0.01 × Phi_Score²
size_units = risk_usd / abs(entry - SL)
notional = size_units × entry
notional = min(notional, 0.02 × equity)  # cap
```

- Unidade de risco local: 1% de equity × Phi_Score² (convexo — prioriza sinais fortes)
- Cap de notional em 2% de equity por trade
- Sem coupling com `core/portfolio.py` (Kelly, position_size) — PHI paga seu próprio risco

---

## 10. Trade Management

### 10.1 Níveis
- **SL:** `fib_0.786(Ω3 = 1H) ∓ 0.3 × ATR(14, 1H)` (abaixo pra LONG, acima pra SHORT)
- **TP1:** `fib_1.272(Ω3)` — parcial sai 38.2% da size
- **TP2:** `fib_1.618(Ω3)` — parcial sai 38.2% da size
- **TP3:** `fib_2.618(Ω3)` — runner com 23.6% da size restante

### 10.2 Trailing no runner
- Após TP2, runner (23.6%) usa trailing adaptativo:
  - Trail = `novo fib_0.618` calculado no TF imediatamente menor (Ω4 = 15m)
  - Recalcula a cada barra 5m conforme novos swings 15m confirmam
  - Stop nunca retrocede (monotônico)

### 10.3 Exit resolution (prioridade por barra 5m)
1. SL hit → fecha posição inteira
2. TP1/TP2/TP3 hit → parcial conforme regra
3. Trailing hit (runner) → fecha runner

**Kill-switch** (Seção 11) **não força exit** — só bloqueia novas entradas.
Posições abertas seguem seu próprio management até SL/TP/trailing natural.

---

## 11. Kill-Switch (portfolio-level)

- **Daily:** se `equity_high_today - equity_now > 2.618% × equity_high_today` → **para novas entradas no dia**; posições abertas seguem até exit natural
- **Weekly:** se `equity_high_week - equity_now > 6.18% × equity_high_week` → **para novas entradas até o próximo segunda 00:00 UTC**

Tracking via `equity_curve` dentro do `run_backtest` loop.

---

## 12. Custos

- Roundtrip: `TOTAL_ROUNDTRIP_COST` de `config.params` (SLIPPAGE + SPREAD + 2×COMMISSION)
- Funding: `FUNDING_PER_8H × horas_em_trade / 8 × leverage` subtraído do PnL bruto
- Modelo idêntico ao GRAHAM (`_pnl_with_costs`)

---

## 13. CLI

```
python -m engines.phi \
  --symbols BNB,INJ,LINK,RENDER,NEAR,SUI,ARB,SAND,XRP,FET,OP \
  --start 2024-01-01 --end 2026-04-01 \
  --out data/phi
```

Flags adicionais (opcional, para grid search posterior):
- `--threshold-cluster 3` (default, mas permite 2 ou 4)
- `--omega-entry 0.618` (default)
- `--no-kill-switch` (debug)

Default sem flags = roda o universo completo com janela de 2 anos até hoje.

---

## 14. Critérios de Aceitação

### 14.1 Aspiracionais (do spec original)
- Sharpe > 1.618
- Sortino > 2.618
- Win Rate ≥ 38.2%
- Profit Factor ≥ 1.618
- Max Drawdown < 16.18%
- Expectancy > 0.618 R
- Bootstrap 1000x: Sharpe P5 > 0.618

### 14.2 Realistas (promoção à bateria)
- **overfit_audit 6/6** — walk-forward 6 janelas passa majoritariamente
- **≥100 trades** no período de teste (estatística mínima)
- **Sharpe OOS > 0.5** (barra baixa; se bater os aspiracionais, ótimo)
- **MaxDD OOS < 25%** (não explodir)

### 14.3 Se não passar
- PHI fica arquivado em `engines/phi.py` mas **nunca entra em FROZEN_ENGINES**
- Documentar findings em `docs/audits/phi-audit-YYYY-MM-DD.md` (padrão KEPOS)
- Atualizar memory com anti-padrão aprendido

---

## 15. Riscos Conhecidos

| Risco | Mitigação |
|---|---|
| **Signal sparsity** (5 TFs × confluência é raro) | Aceitar: se <100 trades, engine é arquivado |
| **Pivot confirmation lag** (2 barras) | Documentado, explícito no código, testado contra lookahead |
| **Runtime** (~3 min por backtest) | Aceitável pra audit; otimizar só se virar bottleneck |
| **Overfitting dos pesos Fib** | Pesos são fixos do spec (não calibrados); audit 6/6 testa estabilidade |
| **Correlação entre símbolos** | Kill-switch de portfolio + cap de 2% por trade limita blowup |

---

## 16. Fora do Escopo (YAGNI)

- Multi-exchange (só Binance Futures USDT-M, padrão AURUM)
- Live execution (backtest-first; live só depois de audit passar)
- Otimização de pesos Ω_PHI (usar os do spec; grid search é trabalho futuro)
- Integração com `live.py` / `MILLENNIUM` orchestrator
- Dashboard/UI específico no launcher (reusa padrão DATA/BACKTEST existente)

---

## 17. Próximos Passos

1. João revisa este spec
2. Se aprovado → `writing-plans` gera plano executável passo-a-passo
3. Implementação (`engines/phi.py`) via subagent-driven-development
4. Primeiro backtest puro em `UNIVERSE` padrão
5. Decisão: passa audit 6/6 ou arquiva
