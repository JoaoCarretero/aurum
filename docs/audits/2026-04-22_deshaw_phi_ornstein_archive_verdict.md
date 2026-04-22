# Veredito de Arquivamento — DESHAW · PHI · ORNSTEIN
**Data**: 2026-04-22  
**Auditor**: 3 agentes independentes (Claude Explore) + consolidacao  
**Protocolo**: anti-overfit (CLAUDE.md + `docs/methodology/anti_overfit_protocol.md`)

## Contexto

Joao requisitou "trabalhar nas metricas ate achar edge" em DESHAW, PHI
e ORNSTEIN. A resposta honesta ao pedido, dentro do protocolo
anti-overfit, foi disparar 3 agentes **audit-only** (sem rodar codigo)
pra avaliar:

1. Mecanismo da engine e defensavel?
2. Grid esgotado ou ha direcao honesta nao tentada?
3. Se houver direcao, propor UM grid fechado ≤20 configs com DSR
4. Recomendacao: ARCHIVE ou ONE MORE DISCIPLINED ROUND

Os 3 retornaram **ARCHIVE** de forma consensual. Este documento
registra os achados.

## DESHAW — ARCHIVED

**Mecanismo**: Engle-Granger pairs cointegration em bluechip crypto.

**Diagnose**: Nao defensavel em crypto. Cointegracao pressupoe
relacao estrutural persistente e regime-independente, mas:
- BEAR: correlacoes colapsam
- BULL: spreads desacoplam permanentemente
- CHOP: reversion e fragil

**Evidencias de ausencia de edge (backtest 360d bluechip 1h
2026-04-22)**:
- Sharpe: **−0.19**
- ROI: **−0.33%**
- Walk-forward FAIL: 3/5 windows negativas (W2: −1.43, W5: −4.29)
- Regime concentration FAIL: 98/101 trades em BULL (esperado
  CHOP-only per tese)
- Symbol concentration FAIL: remover FETUSDT inverte conta
  (−32 → +86) — edge era 1 simbolo
- Temporal decay FAIL: 246% deterioracao entre halves
- Slippage breakeven: 1bp (frageis)

**Grid esgotado**:
- z-entry: 2.0 → 4.0 (testado)
- pvalue cointegration: 0.05 → 0.15 (testado)
- half-life: 100 → 300 (testado)
- regime gates: CHOP, CHOP+BULL (testado)
- HMM thresholds: multiplas combos (testado)

**Historico anterior**: OOS 2026-04-16 ja flagava Sharpe −1.73 BEAR
2022 (cointegracao quebra em regime shifts). Checklist 2026-04-21
Passo 4 (train): Sharpe DSH01_chop_only −0.46, DSH00_baseline −0.73
— **ambos negativos**. Nunca validou OOS. Passo 5 DSR p-value 0.000.

**Falhas contabilizadas**: 4 gates do audit (walk-forward,
concentration symbol, concentration regime, temporal decay). Per
protocolo "falhou 1 etapa → arquiva", DESHAW falhou **4**.

**Veredito**: `ARCHIVE`. Nao reformular, nao re-tunar. O mecanismo
de cointegracao nao sobrevive ao regime-dependence de crypto.

## ORNSTEIN — ARCHIVED (confirma archive anterior)

**Mecanismo**: OU process (AR(1) + 5 testes estatisticos: OU fit,
Hurst H<0.5, ADF p<0.05, Variance Ratio <1, Bollinger %B extreme) +
fractal divergence 5 TF.

**Diagnose**: Academicamente solido, operacionalmente morto em
crypto. Janelas curtas (15m) em crypto sao trending (H ~0.8+).
Janelas 2025-2026 foram bull/acumulacao, nao ranging.

**Evidencias (salvage round 2026-04-21)**:
- Strict filter: **0 trades** (testes em cascata zeram sample)
- Exploratory filter (relaxado): **Sharpe −31.98, PF 0.307,
  MaxDD 8.92%** — colapso catastrofico
- 5 configs O00-O04 fechados: nenhum bate sample minimo + Sharpe
  positiva

**Grid esgotado**: halflife band, Hurst threshold, ADF p,
divergence on/off, todas as combinacoes razoaveis testadas.

**Joao's memory "filters mal calibrados, tunar"**: testado. Nao e
calibracao, e **anti-edge estrutural** — filtros relaxados liberam
sinais ruidosos que geram losses catastroficos.

**Veredito**: `ARCHIVE`. Se aparecerem evidencias novas (post-crash
bounces em alts, data pre-2024 com H<0.5 confirmado), reabrir com
NOVA hipotese, nao novo grid.

## PHI — RUN BATTERY + HONOR VERDICT

**Mecanismo**: Fibonacci 0.618 retracement multi-TF confluence +
Golden Trigger em 5m.

**Diagnose**: Pattern matching puro. Fibonacci e "profecia
auto-realizavel" sem causalidade economica. Multi-TF confluence
pode adicionar robustez OU grau de liberdade (risco de fishing
expedition).

**Estado do protocolo**:
- `tools/batteries/phi_reopen_protocol.py` existe, 16 configs
  fechados, splits train/test/holdout hardcoded (2023-01-01 →
  2024-01-01 → 2025-01-01 → 2026-04-21)
- Criterios de passagem:
  - Train: deflated Sharpe ≥ 1.5, DSR p-value ≥ 0.95
  - Test: min(top-3 Sharpe) ≥ 1.0
  - Holdout: Sharpe ≥ 0.8
- Status de execucao previo: **desconhecido** (sem artifacts
  encontrados)

**Acao tomada**: battery executada 2026-04-22 antes do arquivamento
final. Resultado anexado abaixo.

**Criterio de veredito**:
- Passou os 3 gates → reopen com live_bootstrap
- Falhou 1 gate → `ARCHIVE` per stop rule

### Resultado PHI battery (anexo)

```
[PENDENTE — resultado a ser anexado apos execucao]
```

## Meta-rule ativada

Per CLAUDE.md: *"3 engines consecutivos arquivados → PAUSAR e
revisar metodo, nao continuar batendo"*.

DESHAW + ORNSTEIN arquivados confirma 2/3. Se PHI tambem falhar,
**3/3 = pause triggered**. Isso indica que:

1. O universo de testes (bluechip crypto, 15m/1h TFs, 360-720d
   windows) tem edge limitado a CITADEL/JUMP/RENAISSANCE.
2. Proxima rodada de research nao deve ser "mais uma engine" mas
   sim:
   - Revisao da baseline de dados (mais basket, mais TF, mais time)
   - Revisao de mecanismos testados (momentum, micro-structure,
     harmonics ja funcionam — o que mais?)
   - Possivel limite de alpha em crypto spot/perp tradicional;
     explorar arb (JANE STREET) ou allocator (AQR) em vez de mais
     direcionais.

## Acoes concretas pos-veredito

1. **DESHAW**: docstring `__doc__` atualizado com verdict +
   `config/engines.py` mantido em EXPERIMENTAL_SLUGS (ja estava).
2. **ORNSTEIN**: docstring atualizado idem + mantido em
   EXPERIMENTAL_SLUGS.
3. **PHI**: apos battery, se falhar, adicionar ao EXPERIMENTAL_SLUGS.
4. **Este documento** committed pra registro.

## Nota filosofica

A honestidade do arquivamento **e** o edge do sistema. Sem protocolo
anti-overfit, engines com Sharpe in-sample alto sobreviveriam ate
live, onde colapsariam. A disciplina que arquiva 3 engines seguidas
e a mesma disciplina que validou CITADEL/JUMP/RENAISSANCE honestos.

> "A espiral e continua. O disco gira e se reescreve."
> — AURUM Mandamento 6
