# Hipótese — SUPERTREND FUT

**Engine:** `supertrend_futures`
**Registrada:** 2026-04-22
**Protocolo:** anti-overfit 8-passos (AURUM)
**Origem externa:** Juan Carlos Soriano (@juankysoriano) — Freqtrade
`user_data/strategies/futures/FSupertrendStrategy.py`

---

## Fenômeno de mercado

Crypto futures (perpetual swap, 1h TF) apresenta trends direcionais de média
duração (dezenas de horas a vários dias), especialmente em macro bull/bear.
Uma única leitura ATR-based pode dar falso sinal (whipsaw em chop), mas
**três Supertrends com parâmetros distintos** (period/multiplier diferentes)
raramente divergem durante um trend real — o "hit rate" do consenso é um
filtro natural contra flip-flop. O mecanismo funciona em futures por dois
motivos extras: (1) shorts simétricos capturam bear sem inversão discreta
de lógica; (2) liquidação L7 (fora deste engine, no labeler) remove
fat-tails.

## Por que funciona

**Mecanismo:** ATR trailing line = price ± (multiplier × ATR). Os 3
Supertrends usam params 8/3, 9/7, 8/1 (m/p). O mais apertado (m=1) é
reativo — pula pra `down` cedo em pullbacks leves. O mais largo (m=7) é
lento — só inverte em reversão estrutural. Exigir os 3 unânimes pra entrar
= filtro de kurtosis natural: só entra quando timescales curto, médio e
"volatility-adjusted" concordam. Saída exige só o supertrend #2 (o
"decisivo") flipar = captura trend cedo no fim, protege contra
sticky-consensus-near-reversal (assimetria clássica trend-follower).

## Precedente

- **Soriano/Freqtrade:** strategy publicada em 2020+, largamente replicada
  em comunidades. Variante mais popular do 3-Supertrend confluence.
- **Mecanismo ATR trailing:** Olivier Seban 2007, originalmente em equities;
  adaptado em crypto por centenas de bots Freqtrade/TradingView.
- **Lab externo AURUM (pré-2026-04-22):**
  - OOS 2024 (bull): Sharpe **+0.55**, ROI +7.95%, MDD 15.97%, 282 trades
  - Q4 2024 (stress): Sharpe **+0.82**, ROI +5.19%, MDD 15.97%, 140 trades
  - Bear 2022: Sharpe **-0.08**, ROI -1.73%, MDD 23.56%, 382 trades (captura
    via shorts — perda contida)
  - Universo lab: BTC/ETH/SOL futures perp, 1h, 2x lev, can_short=True

**Observação honesta:** Sharpe lab externo ≈ 0.5-0.8 em OOS. O protocolo
AURUM exige **train DSR-adjusted Sharpe ≥ 1.5**. Probabilidade ex-ante de
arquivar: **alta (60-70%)**. Rodar mesmo assim porque (a) mecanismo tem
precedente público sólido, (b) majors AURUM podem se comportar diferente
do universo lab, (c) comprar opção barata de sobreviver com grid enxuto.

## Falsificação

Arquivar se qualquer uma das condições abaixo acontecer:

1. **Train DSR-adjusted Sharpe < 1.5** ou DSR p-value < 0.95
2. **Test Sharpe pior-de-top-3 < 1.0**
3. **Holdout Sharpe < 0.8**
4. Trade count em train < 50 (amostra insuficiente)

Se sobreviver holdout, candidato a paper-forward 30-60d; se paper <
50% holdout, arquiva mesmo assim.

---

## Split (hardcoded em `engines/supertrend_futures.py`)

```python
TRAIN_START = "2022-01-01"   # inclui bear 2022 — lab externo mostrou sobrevida via shorts
TRAIN_END   = "2024-01-01"
TEST_END    = "2025-01-01"
HOLDOUT_END = "2026-04-22"   # hoje
```

## Universo

5 majors de alta liquidez: **BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT**.
Mesmo split universo PHI — coerência de comparação. Anti-cherry-pick:
reportar média ponderada de todos os 5.

## Timeframe

**1h** (fiel ao lab externo). Não grid-search.
