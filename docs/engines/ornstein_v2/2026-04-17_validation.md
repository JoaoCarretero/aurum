# ORNSTEIN v2 — Validation Report (2026-04-17)

> Resultado da execução do protocolo em `docs/superpowers/specs/2026-04-17-ornstein-v2-validation-design.md`.

## Contexto

Preset `robust` + wrapper `engines/ornstein_v2.py` foram adicionados na
sessão Claude+Codex de 2026-04-17. 5 params novos em `OrnsteinParams`.
Codex rodou `ornstein_v2 --basket bluechip_active --days 360` e obteve
0 trades. Este doc valida/arquiva a variante com evidência honesta.

## Etapa 1 — Baseline (v1 default / bluechip_active / 360d)

Run dir: `data/ornstein/2026-04-17_2333`

Comando: `python -m engines.ornstein --preset default --basket bluechip_active --days 360 --no-menu`

Universo: 19 símbolos (BNBUSDT, INJUSDT, LINKUSDT, RENDERUSDT, NEARUSDT, SUIUSDT, ARBUSDT, SANDUSDT, XRPUSDT, FETUSDT, OPUSDT, BTCUSDT, ETHUSDT, SOLUSDT, ADAUSDT, AVAXUSDT, DOTUSDT, ATOMUSDT, AAVEUSDT).

Janela: 2025-04-18 → 2026-04-17 (360d).

| Métrica | Valor |
|---------|-------|
| N_trades | **0** |
| Sharpe | 0.000 |
| MaxDD | 0.00% |
| WinRate | 0.00% |
| Expectancy (R) | 0.000 |
| Total return | 0.00% (final_equity = initial_equity = $10,000) |
| DSR (n_trials=1) | N/A — insufficient_sample |
| ratio_status | insufficient_sample |

Distribuição de vetos (total 660,991 barras rejeitadas em 19 símbolos × 5 TFs × 360d):

```
  no_divergence       316,766   (47.9%)
  rsi_block           306,119   (46.3%)
  hurst_block          36,945   ( 5.6%)
  halflife_outside      1,151   ( 0.2%)
  ou_nan                   10   (<0.1%)
```

**ATENÇÃO — ACHADO CRÍTICO:** o engine v1 em config default também zera sample
nesta janela. O problema não está no preset `robust` (v2). Está upstream, nos
filtros estruturais do próprio v1 (divergence + RSI rejeitam 94% das barras
sozinhos; Hurst rejeita outros 6%). Ver seção "Achados" abaixo.

## Etapa 2 — Reprodução do Codex (v2 robust / bluechip_active / 360d)

**NÃO EXECUTADA.** Redundante: Etapa 1 já mostrou que v1 default = 0 trades no
mesmo universo/janela. Adicionar os guards do preset `robust` só pode
**reduzir** sample, nunca aumentá-lo. Confirmação de "0 trades em v2" não
adiciona evidência acima de "0 trades em v1".

(Histórico: Codex rodou ontem e obteve 0 trades — consistente com o que v1
default agora também mostrou em base limpa.)

## Etapa 3 — Ablation (majors / 180d)

**NÃO EXECUTADA.** O ablation pressupõe um baseline com sample > 0 pra comparar
variantes. Com v1 default zerando no universo completo, a projeção pra
majors/180d (subconjunto + janela menor) tende a zerar também, dado que os 2
vetos dominantes (no_divergence 48% e rsi_block 46%) são independentes de
tamanho de universo — são estruturais por barra.

Mesmo que alguma variant produzisse 1-2 trades em majors/180d, não haveria
DSR-significância nem base válida pra generalizar.

## Etapa 4 — Final comparison

**NÃO EXECUTADA.** Sem best variant selecionado.

## Decisão

**ARCHIVE.**

Justificativa per spec + anti-overfit protocol:

1. **Regra de parada honrada** (regra 5 do `docs/methodology/anti_overfit_protocol.md`):
   Etapa 1 falhou (sample 0). Sem reformular universo, sem trocar janela,
   sem relaxar thresholds. Arquiva.

2. **Sem número pra bater.** O critério de promote do spec (`DSR(best) >
   DSR(default)` E `N_trades(best) >= 30` E `Sharpe(best) > Sharpe(default) * 1.10`)
   é logicamente impossível com `DSR(default) = N/A` e `Sharpe(default) = 0`.

3. **Premissa original invalidada.** O preset `robust` foi adicionado
   assumindo que v1 produzia trades que precisavam ser filtrados mais
   rigorosamente. A evidência mostra que v1 default já está em zero — os
   guards extras não podiam adicionar edge.

4. **Contradição documental confirmada.** O commit `a1fb95e` do v1 já
   documentava: "crypto 15m shows H in [0.77, 1.0] regardless of macro regime —
   the exploratory preset disables the Hurst gate with a comment explaining
   why." O `hurst_threshold=0.42` do preset `robust` aprofundaria isso. Mas
   como o maior peso de veto é `no_divergence` (48%) e `rsi_block` (46%),
   Hurst é só o terceiro — mesmo desligando Hurst, zero continua.

## Achados (v1 core, fora do escopo deste spec)

Este audit expôs um problema em v1 que não era objeto da validação de v2:

- **ORNSTEIN v1 em config default produz 0 trades em janelas recentes de cripto.**
  Universo diversificado (19 símbolos), 360d (1 ano inteiro de 2025-2026).
- **Vetos dominantes são divergence (48%) e RSI (46%)**, não as features
  estatísticas (OU / Hurst / ADF / VR) que são o diferencial conceitual do
  engine. Isso sugere que os filtros de "trigger" estão estrangulando o sinal
  antes da bateria estatística sequer avaliar.
- O commit `a1fb95e` marca o engine como "research-only until an
  overfit_audit 6/6 passes on a live OOS window". Este audit confirma que
  está longe disso — não tem nem sample pra fazer overfit_audit.

**Recomendação (followup, escopo separado):** antes de qualquer validação
OOS do v1, revisar os filtros de `compute_fractal_divergence` e
`compute_rsi_consensus`. O engine pode ter thresholds herdados da spec
original que não se traduzem pro universo crypto de 2025-2026.

## Próximos passos executados

- Archive via `git checkout HEAD -- engines/ornstein.py config/engines.py tests/test_ornstein.py`.
- `rm engines/ornstein_v2.py` (era untracked).
- Tarefas Task 4 (ablation runner), Task 5 (execução), Task 6 (compile), Task 7 (final comparison) do plano **não foram executadas** — protocolo curto-circuitado na Etapa 1 conforme regra de parada.
- Commit único com título `revert(ornstein): archive v2 robust preset — baseline produces 0 trades`.
- Este validation doc fica como registro histórico permanente.

## Próximos passos não executados (backlog)

- **Investigar v1 core signal generator** — issue separada, escopo próprio.
  Os 2 filtros que rejeitam 94% das barras (`no_divergence`, `rsi_block`)
  merecem audit antes de qualquer outro sweep no ornstein.
- Não abrir overfit_audit 6/6 do v1 enquanto não houver sample > 0.
