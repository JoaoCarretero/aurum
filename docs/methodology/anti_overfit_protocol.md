# Protocolo Anti-Overfit — AURUM Finance
# Criado em 2026-04-16 após OOS audit expor 5/7 engines com claims inflados

## Filosofia em uma frase

> **"Não existe edge que não sobrevive a uma janela que eu não vi."**

Se o backtest sobreviveu a dados que você **não tocou durante tuning**, é edge. Senão, é ruído que parece edge.

---

## Os 5 princípios

1. **Mecanismo > Iteração.** Antes de qualquer bateria, escrever 1 parágrafo: *"X acontece porque Y. Espero ver Z."* Sem hipótese mecânica, grid search encontra ruído por design.
2. **Split antes de código.** Decide train/test/holdout com datas ANTES de abrir qualquer engine. Hardcoded no script. Sem "ver como fica e ajustar".
3. **Grid fechado e pré-registrado.** Escreve a lista de N configs ANTES de rodar a primeira. Sem `iter20, iter21, iter22`. Budget fixo, ponto.
4. **DSR obrigatório.** Todo Sharpe reportado tem haircut por `n_trials`. Sharpe cru sem DSR é mentira disfarçada.
5. **Regra de parada honra.** Se o engine não sobrevive após o protocolo, **arquiva**. Não reformula, não ajusta, não "tenta uma última coisa". Arquiva.

---

## Protocolo de 8 passos (ordem obrigatória)

### Passo 1 — Hipótese mecânica (antes de código)

Escrever em `docs/engines/<engine_name>/hypothesis.md`:

```markdown
# Hipótese — <engine>

## Fenômeno de mercado
[1 parágrafo: que padrão real existe no mercado?]

## Por que funciona
[1 parágrafo: mecanismo — microestrutura? comportamento? estrutural?]

## Precedente acadêmico
[1 parágrafo: quem já validou isso? papers? mecanismo conhecido?]

## Falsificação
[1 parágrafo: o que provaria que NÃO funciona? Se Sharpe <1 no holdout, arquivo.]
```

Se você não consegue preencher essas 4 seções em 10min, **o engine não tem mecanismo** — arquiva antes de começar.

### Passo 2 — Split hardcoded

```python
# engines/<engine>.py — topo do arquivo
TRAIN_END = "2024-01-01"
TEST_END  = "2025-01-01"
# holdout: 2025-01-01 até hoje
# Estas datas NÃO mudam. Se mudarem, reset tudo.
```

### Passo 3 — Grid pré-registrado

Em `docs/engines/<engine>/grid.md`:

```markdown
# Grid pré-registrado — <engine>

- Budget: N configs (ex: 20)
- Registrado em: <data>
- Lista fechada:

| # | Param1 | Param2 | Param3 |
|---|---|---|---|
| 1 | ... | ... | ... |
| 2 | ... | ... | ... |
...
| 20 | ... | ... | ... |
```

**Depois de registrado, a lista não muda.** Commit ANTES de rodar.

### Passo 4 — Tune em train

- Rodar os N configs **só em janela train** (até `TRAIN_END`)
- Coletar Sharpe, Sortino, MDD, trades de cada
- **Nenhum olho no test set.**

### Passo 5 — DSR haircut

Fórmula simplificada (López de Prado 2014):

```python
def dsr(sharpe_best, n_trials, sharpe_std, skew=0, kurt=3, T=252):
    """Deflated Sharpe Ratio — penaliza best-Sharpe por número de tentativas.
    Retorna p-value; se p < 0.05, edge é estatisticamente distinguível de ruído."""
    from math import log, sqrt
    from scipy.stats import norm
    
    # Esperado do max Sharpe em N trials iid ~ N(0, sigma)
    e_max = sharpe_std * (
        (1 - 0.5772) * norm.ppf(1 - 1/n_trials)
        + 0.5772 * norm.ppf(1 - 1/(n_trials * 2.71828))
    )
    
    # Deflated Sharpe
    numerator = (sharpe_best - e_max) * sqrt(T - 1)
    denominator = sqrt(1 - skew * sharpe_best + (kurt-1)/4 * sharpe_best**2)
    dsr_z = numerator / denominator
    return norm.cdf(dsr_z)  # p-value
```

**Regra:** DSR p-value > 0.95 pra engine candidato sobreviver. Se p < 0.95, Sharpe é indistinguível de ruído com N tentativas.

### Passo 6 — Top-3 em test

- Pegar os top-3 configs por DSR-adjusted Sharpe (não por Sharpe cru)
- Rodar em **test set** (`TRAIN_END` → `TEST_END`)
- **Reportar pior dos 3**, não o melhor. Se o melhor parece muito melhor que os outros 2, é overfit mesmo assim.
- Se Sharpe pior-de-3 em test < 1.0 DSR-adjusted → **engine falha**, arquiva.

### Passo 7 — Holdout final

- Se sobreviveu ao test, pega **o único config escolhido** (pior-de-top3 do test)
- Roda em holdout (`TEST_END` → hoje)
- Se Sharpe holdout < 0.8 → **arquiva**. Mesmo que test tenha passado.

### Passo 8 — Paper forward

- Se sobreviveu a tudo, roda em paper 30-60 dias
- Se Sharpe em paper < 50% do holdout Sharpe, **arquiva**. Provavelmente era sorte.
- Só depois disso, vira candidato a FROZEN / capital real.

---

## Regras de parada

Cada uma é uma condição SUFICIENTE pra arquivar:

1. Hipótese não preenche as 4 seções
2. DSR-adjusted Sharpe em train < 1.5 (nada pra continuar)
3. DSR-adjusted Sharpe em test < 1.0
4. Sharpe em holdout < 0.8
5. Sharpe em paper < 50% do holdout

**Regra meta:** 3 engines consecutivos arquivados → **PAUSAR e revisar método**. Se 3 hipóteses falharam, ou o método de formar hipótese tá errado, ou você tá escolhendo mecanismos fracos.

---

## Anti-patterns a reconhecer e evitar

### 🚫 Anti-pattern 1 — "Só mais um iter"
```
iter1: Sharpe 0.8  "hmm, vou tentar mais params"
iter2: Sharpe 0.9  "quase lá"
iter3: Sharpe 1.1  "pode melhorar"
...
iter19: Sharpe 2.65  "WINNER!"
```
**Por que falha:** cada iter vê o mesmo histórico. Eventualmente encontra combo que encaixa no ruído específico daquela amostra. Colapso garantido OOS.

**Fix:** grid fechado + DSR desde o começo.

### 🚫 Anti-pattern 2 — "Reformular universo até achar"
```
bluechip falhou → tenta majors → falha → tenta tier1 → achou Sharpe 3 → WINNER
```
**Por que falha:** universo é só mais uma dimensão de busca. 5 baskets × 20 params × 7 engines = 700 tentativas. DSR haircut pesado.

**Fix:** pre-registrar UM universo por hipótese. Falhou, arquiva.

### 🚫 Anti-pattern 3 — "Mesmos dados pra tune e report"
```
"Sharpe 5.65 (360d bluechip, longrun 2026-04-14)"
```
**Por que falha:** janela de calibração = janela de report. Zero informação sobre OOS.

**Fix:** sempre reportar Sharpe em 3 janelas: train, test, holdout. Nunca omitir.

### 🚫 Anti-pattern 4 — "Comment tattoo"
```python
STOP_ATR_M = 2.8  # grid 2026-04-14 · stops mais largos Sharpe 4.49 WINNER
```
**Por que falha:** o valor vira sagrado porque comentário afirma que é. Ninguém volta pra questionar. Eventualmente `params.py` vira museum de overfits.

**Fix:** comentário tem que incluir **train/test/holdout Sharpes**. Se só tem IS, é mentira.

### 🚫 Anti-pattern 5 — "Cherry-pick melhor symbol"
```
"CITADEL achou Sharpe 4 em SOL mas -1 em BTC. Vou reportar SOL only."
```
**Por que falha:** per-symbol cherry-pick é survivorship embaixo de outro nome.

**Fix:** reportar **média ponderada de todos** no universo, ou reformular hipótese pra explicar por que só 1 símbolo.

---

## Exemplo concreto — MEDALLION refeito corretamente

**Hipótese original (falhou):** grid search de 144+48 configs em bluechip → Sharpe alto in-sample, -3.22 OOS.

**Hipótese refeita:**

```markdown
# Hipótese — MEDALLION

## Fenômeno
Mean-reversion de curto prazo (1-4h) é mais forte durante horário asiático
(00:00-08:00 UTC), quando liquidez é menor e order books mais finos.

## Mecanismo  
Liquidity providers menos presentes → market orders empurram preço além
de valor justo → reversão ocorre quando mercado americano/europeu volta
e restaura liquidez.

## Precedente
Harris (2003) documenta padrão em equities; Menkveld (2013) em FX;
sem paper específico em crypto altcoin.

## Falsificação
Se Sharpe em horário asiático < Sharpe em 24h total, hipótese falsa.
```

**Split:**
- Train: 2021-05-01 → 2024-01-01
- Test: 2024-01-01 → 2025-01-01
- Holdout: 2025-01-01 → hoje

**Grid pré-registrado (10 configs):**
- 5 thresholds de z-score (1.0, 1.5, 2.0, 2.5, 3.0)
- 2 janelas de detecção (30min, 1h)

**Tune em train:** roda 10 configs, coleta Sharpe.

**DSR:** Sharpe best = 3.2; n_trials = 10; std_sharpe = 1.5; p = 0.93 — **falha** (< 0.95). Ruído. **Arquiva MEDALLION.**

OU: DSR p = 0.97 — passa. Top-3 em test.

Test Sharpe pior-de-3 = 1.3. Passa (> 1.0).

Holdout Sharpe = 0.9. Passa (> 0.8).

Paper 30 dias Sharpe = 0.7. Passa (50% de 0.9 = 0.45, 0.7 > 0.45). **MEDALLION vira candidato a FROZEN.**

Se parar em qualquer etapa → arquiva. Sem retry.

---

## Implementação técnica

Para a próxima sessão de battery:

1. **`analysis/dsr.py`** — implementar DSR conforme Passo 5
2. **`analysis/walkforward.py`** — reescrever para ser WF genuíno (folds cronológicos + re-fit de params)
3. **`core/validation.py`** — decorator `@requires_oos(train_end, test_end)` que força split
4. **`save_run()`** em cada engine — incluir automaticamente `n_trials`, DSR p-value, train/test/holdout Sharpes no JSON
5. **Pre-commit hook** — rejeitar comentários `iter_N WINNER` em `config/params.py`

Tudo isso pode ser feito numa sessão dedicada antes de retomar sweeps.

---

## Hipóteses candidatas pra bateria disciplinada (pra discussão)

Após OOS audit de 2026-04-16, sobrou curiosidade sobre:

| Engine | Hipótese candidata | Universo | Probabilidade subjetiva |
|---|---|---|---|
| DE SHAW | Cointegração só funciona em pares fundamentais | BTC/ETH, ETH/BNB | 30% |
| MEDALLION | Mean-reversion em horário asiático | bluechip, filtro UTC 00-08 | 25% |
| PHI | Fib confluências em majors de alta liquidez | BTC/ETH/BNB/SOL/XRP | 20% |
| MILLENNIUM | Diversificação real entre alphas confirmadas | orquestra só CITADEL + JUMP | 60% |

**Ordem recomendada (pelo custo-benefício):**

1. **MILLENNIUM** primeiro (alta probabilidade, fácil testar — só encadear CITADEL + JUMP)
2. **DE SHAW** com BTC/ETH (custo baixo, conceito claro)
3. **MEDALLION** com hipótese asiática (se tiver energia)
4. **PHI** por último (mecanismo mais fraco)

---

## Meta-trigger log

Registro das vezes em que a regra meta do protocolo foi disparada
("3 engines consecutivos arquivados → PAUSAR e revisar método").

### 2026-04-17 — primeiro disparo

**Engines arquivados/colapsados consecutivos:** DE SHAW (OOS Sharpe
-1.73 BEAR 2022), KEPOS (0 trades com defaults), MEDALLION (OOS Sharpe
-3.22).

**Ação tomada (respeita o protocolo — método antes de re-calibração):**

1. **Audit-o-auditor** (Bloco 0 plano 2026-04-17) — revalidar se o
   veredito OOS era metodologicamente honesto antes de agir.
   Resultado: 6/7 reprodutibilidade exata; BRIDGEWATER divergiu em
   n_trades e Codex track'd root cause `LIVE_SENTIMENT_UNBOUNDED`.
2. **Bugs funcionais encontrados e fixados:**
   - `core/sentiment.py` — funding/OI/LS fetches não respeitavam
     `end_time_ms` em backtest (commit `9b41c76`). BRIDGEWATER Sharpe
     cai de 11.04 → 3.03 após fix (73% era bug, 3.03 é edge real).
   - `engines/kepos.py` + `engines/medallion.py` — entry cost
     asymmetry: aplicava SLIPPAGE+SPREAD só no exit (commit `18db6dc`).
     ~3 bps/trade subestimados.
   - `engines/kepos.py` — `eta_critical=0.95` unreachable em candle
     data (commit `55857f3`). Baixado pra 0.75.
3. **Quarentena formal** via `EXPERIMENTAL_SLUGS` em `config/engines.py`
   (commit `cc4a642`) — DE SHAW e GRAHAM inicial; KEPOS/MEDALLION
   pendem re-avaliação OOS pós-fixes.

**Lição registrada:** o gatilho meta funcionou. Não foi "mais um iter"
nos engines que falharam — foi investigação forense que revelou que
parte do "colapso" era bug de código (BRIDGEWATER especialmente), e
parte era limite de mercado genuíno (DE SHAW cointegração crypto).

---

## Referências

- López de Prado, M. (2014). *Deflated Sharpe Ratio*. Journal of Portfolio Management
- Harvey & Liu (2015). *Backtesting*. Journal of Portfolio Management
- Bailey, Borwein, López de Prado, Zhu (2014). *Pseudo-Mathematics and Financial Charlatanism*. Notices of AMS
