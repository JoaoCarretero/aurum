# Audit BRIDGEWATER — bugs estruturais

**Data:** 2026-04-17 (~15:45)
**Branch:** `feat/phi-engine`
**Motivação:** bateria MILLENNIUM (ver `2026-04-17_millennium_readiness.md` e `battery_2026-04-17_1521/battery_summary.md`) revelou que BRIDGEWATER dominava massivamente (88-90% dos trades, 99% shorts, avg R 0.12-0.15, Sharpe inflado 7.93). João pediu audit pra responder: está bugada ou não?

**Veredito:** **SUSPEITA — bugs estruturais graves que inflaram silenciosamente as métricas**. Não há um bug único que derrube o engine; há 3 problemas em camada que fabricam sinal e enviesam direção. Métricas reportadas pré-fix NÃO podem ser tomadas como edge real.

---

## Bugs confirmados

### Bug 1 — Alinhamento posicional (não-temporal) de LS/Funding [ALTO, 95%]

**Arquivos:** `core/sentiment.py:320-332` (`ls_ratio_signal`) + `core/sentiment.py:275-285` (`funding_zscore`) + `engines/bridgewater.py:283-322` (`_align_series_to_candles`)

**Problema:** `ls_ratio_signal` retorna `pd.Series(signal, index=ls_df.index)` onde `ls_df.index` é um `RangeIndex` inteiro (0..499), porque `fetch_long_short_ratio` chama `reset_index(drop=True)`. Idem `funding_zscore`. Quando `_align_series_to_candles` recebe Series sem DatetimeIndex (`is_datetime64_any_dtype == False`), cai no branch fallback POSICIONAL (linhas 297-302):

```python
values = pd.to_numeric(series, errors="coerce").fillna(default).to_numpy(dtype=float)
n = min(len(values), len(aligned))
aligned[:n] = values[:n]
if n and n < len(aligned):
    aligned[n:] = values[n - 1]
```

**Efeito:** os 500 ticks de LS (5d de cobertura, 15m) são mapeados posição-a-posição sobre os ~4000+ candles do backtest. Candles antigos recebem valores sem correspondência temporal; candles novos recebem propagação do último valor (`aligned[n:] = values[n - 1]`). **Fabricação de sinal silenciosa.**

**OI está correto** — usa `_align_oi_signal_to_candles` com `merge_asof`. Só LS e funding estão quebrados.

**Fix (1-line cada):**
- `ls_ratio_signal`: `pd.Series(signal, index=pd.to_datetime(ls_df["time"]))` no return
- `funding_zscore`: `z.index = pd.to_datetime(funding_df["time"])` antes do return

---

### Bug 2 — Fallback live sem end_time_ms quando cache parcial [ALTO, 90%]

**Arquivo:** `core/sentiment.py:104-120` (`_slice_cached_history`)

**Problema:**
```python
if len(subset) < limit:
    return None
first_ts = subset["time"].iloc[0]
if first_ts > window_start_ts:
    return None
```

Se cache tem menos rows que `limit` OU não cobre o window_start, retorna `None`. Então `fetch_open_interest`/`fetch_long_short_ratio` caem em fetch live nas linhas 193-216 que constroem `params = {"symbol", "period", "limit"}` — **sem `endTime`**. Binance retorna os ticks mais recentes, não os do ponto OOS.

**Efeito:** em qualquer backtest com `--end` passando data passada (OOS rigoroso), Bug 2 vira look-ahead puro. No contexto MILLENNIUM atual (janela recente terminando hoje), o efeito é mínimo — mas materializa completamente em OOS histórico delimitado.

**Fix:** se `end_time_ms is not None` e cache insuficiente, propagar None / raise. Nunca cair em fetch sem endTime.

---

### Bug 3 — Threshold LS assimétrico enviesa pra BEARISH [MÉDIO, 85%]

**Arquivo:** `core/sentiment.py:328-331` (`ls_ratio_signal`)

```python
signal = np.where(ratio > 2.0, -1.0,
         np.where(ratio > 1.5, -0.5,   # BEARISH dispara em 1.5+ (comum em cripto bull)
         np.where(ratio < 0.5,  1.0,
         np.where(ratio < 0.67, 0.5, 0.0))))  # BULLISH exige < 0.67 (raro)
```

Cripto em bull regime vive com LS > 1.5 (mais longs que shorts). Threshold bearish é permissivo, bullish é estreito. Combinado com Bug 1 (propagação do LS recente para toda a série), causa o **99% shorts estrutural** observado na bateria.

**Fix:** revisar thresholds. Melhor mecânica seria percentis históricos da própria série em vez de valores absolutos — mas isso requer protocolo anti-overfit (mecanismo + grid fechado).

---

## Direcional skew — 99% shorts explicado

Três fatores em camada:

1. **Bug 1:** LS atual (~1.9, bearish) propagado para toda a série → contamina candles históricos
2. **Bug 3:** threshold assimétrico dispara bearish em 60% dos casos
3. **Lógica permissiva em `scan_thoth:490-495`**: quando `sent_score < -_dir_thresh`, aceita struct neutro como confirmação bearish

---

## Cobertura OI/LS atual

Cache real em `data/sentiment/{open_interest,long_short_ratio}/`:

- **19 símbolos** (11 AURUM + BTC/ETH/SOL/ADA/AVAX/DOT/ATOM/AAVE)
- **OI e LS**: 2026-04-12 11:15 → 2026-04-17 17:00 = **~5 dias, 500 rows**
- **Funding**: ~66 dias (200 ticks × 8h)

Qualquer backtest > 5d de OI/LS cai em Bug 2 (fetch live sem endTime) ou em Bug 1 (propagação posicional).

---

## Critério de re-julgamento

**Não antes de 2026-07-17.** Requisitos:

1. Cache de OI e LS com cobertura contínua ≥ 90 dias por símbolo do basket (prewarm diário rodando desde hoje)
2. Bugs 1 e 2 corrigidos (DatetimeIndex + fallback honesto)
3. Bug 3 calibrado (thresholds revisados com mecanismo, não arbitrários)
4. Validação OOS 30d holdout após 60d de "treino", com end_time_ms binding em todos os símbolos

---

## Edge real vs cost-fitting

Avg R-multiple 0.12-0.15 com WR 56% requer **volume muito alto** pra converter. Com custos SLIPPAGE+SPREAD+COMMISSION ~0.10-0.15%/lado e trades de 2-4 candles de duração, o edge pode estar sendo consumido pelos custos. Sharpe 7.93 em 90d é **estruturalmente suspeito** — o Bug 1 fabrica autocorrelação artificial nos sinais que pode inflar Sharpe via WR>50% em volume alto.

**Conclusão:** até Bugs 1-2 corrigidos, **NÃO confirmar edge real**.

---

## Ação tomada 2026-04-17

BRIDGEWATER **removida** do `OPERATIONAL_ENGINES` em `engines/millennium.py`. Peso 0.30 redistribuído: JUMP 0.30→0.40, RENAISSANCE 0.25→0.40, CITADEL 0.15→0.20. Caps e floors atualizados. `_collect_operational_trades` ignora BRIDGEWATER. Op=1 agora é "CITADEL + RENAISSANCE + JUMP".

BRIDGEWATER standalone (ops 6/7/8) mantida — usuário pode rodar direto pra análise, mas o output agora carrega o contexto deste audit.

---

## Follow-up pendente

- [ ] Corrigir Bug 1 em `core/sentiment.py` (one-line em cada função) — requer aprovação do João (toca CORE-adjacente)
- [ ] Corrigir Bug 2 em `core/sentiment.py` (raise em cache insuficiente com end_time_ms)
- [ ] Revisar thresholds LS (Bug 3) via protocolo anti-overfit
- [ ] Agendar prewarm diário pra construir histórico OI/LS
- [ ] Re-habilitar BRIDGEWATER após 2026-07-17 com OOS holdout

---

## Referências

- Bateria que expôs os números: `data/millennium/battery_2026-04-17_1521/battery_summary.md`
- Audit MILLENNIUM-readiness: `docs/audits/2026-04-17_millennium_readiness.md`
- Agent report ID interno: a26bdec32ba650b2c
- Commits relacionados: `9b41c76` (fix LIVE_SENTIMENT_UNBOUNDED), c91d5df (false-positive fix), R2 fix (sessão atual — `end_time_ms` em millennium)
