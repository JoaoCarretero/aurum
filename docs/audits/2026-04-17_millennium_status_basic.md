# Audit básico — MILLENNIUM (2026-04-17 fim de dia)

Status consolidado antes de voltar a trabalhar no engine. Complementa
`docs/audits/2026-04-17_millennium_readiness.md` (de cedo) com o que
mudou depois + o que foi empurrado pro remote.

---

## Config operacional atual (código no repo, pós-commits 2026-04-17)

**Engines ativos no CORE OPERATIONAL (op=1)** — `engines/millennium.py:86`
```
OPERATIONAL_ENGINES = ("CITADEL", "RENAISSANCE", "JUMP")
```
BRIDGEWATER saiu em `a351184` (domínio excessivo, 88–90 % dos trades).

**Pesos base** — `engines/millennium.py:97-101`
```
JUMP:        0.40
RENAISSANCE: 0.40
CITADEL:     0.20
```
Redistribuição dos 0.30 que eram BRIDGEWATER: JUMP +0.10, RENAISSANCE
+0.15, CITADEL +0.05.

**Pisos e tetos** — mantidos pra permitir a banda reagir a regime:
```
floors:  JUMP 0.20 · RENAISSANCE 0.10 · CITADEL 0.05
caps:    JUMP 0.50 · RENAISSANCE 0.50 · CITADEL 0.25
```

**Intervalos nativos** — `ENGINE_NATIVE_INTERVALS` em `millennium.py:87-90`
lê de `config/params.ENGINE_INTERVALS`. Cada engine roda no timeframe
que validou OOS.

---

## Veredicto por engine (OOS 2026-04-16 + pós-fix 2026-04-17)

| Engine | OOS | Observação |
|---|---|---|
| CITADEL | ✅ edge de regime | Dominante em 360d, decay em 180d recente |
| JUMP | ✅ edge | 6/6 PASS, Sharpe 4.68, DSR ~1.0 |
| RENAISSANCE | ⚠ edge real ~2.42 | Regime-sensitive (CHOP 2019 −0.04) |
| BRIDGEWATER | 🔴 removido | Bug-suspect, dominância excessiva |
| DE SHAW | 🔴 quarantined | Cointegration colapsa em regime shift |
| KEPOS | 🔴 quarantined | Fade extensions sem edge no mercado atual |
| MEDALLION | 🔴 quarantined | Grid-best foi overfit canônico |
| GRAHAM | 🔴 arquivado | 4h value — overfit honesto |
| PHI | 🔴 arquivado hoje | `2026-04-17_phi_overfit_followup.md` |

**No cockpit ENGINES LIVE**, engines quarantined (`EXPERIMENTAL_SLUGS`)
agora ficam em bucket dedicado **EXPERIMENTAL**, separado de
**RESEARCH** honesta.

---

## Ressalvas do audit anterior — status atual

| ID | Tópico | Status |
|---|---|---|
| R1 | FROZEN_ENGINES vs OPERATIONAL_ENGINES | Parcial — comentário atualizado em `config/params.py:486` mas flag ainda existe decorativa |
| R2 | `end_time_ms` no sentiment | **Mitigado** — BRIDGEWATER removida, call-site quente já estava OK |
| R3 | Pesos fantasmas (`CITADEL_CAPITAL_WEIGHT`) | Não removido — cleanup de baixo impacto pro próximo ciclo |

---

## Última run full-engine no disco (`data/millennium/`)

`multistrategy_2026-04-17_143920` — **pré-remoção BRIDGEWATER**, não
reflete o código atual. Números pra referência histórica apenas:

```
n_trades=4116   BW 3729 (90%) · JUMP 316 · CITADEL 41 · RENAISSANCE 30
sharpe=-3.28    ROI=-13.1%    MDD=68.9%
```

O colapso desse run foi o sinal que tirou o BRIDGEWATER. Próxima baseline
é rodar Millennium op=1 de novo com o código atual.

---

## Shadow runner

`tools/millennium_shadow.py` validado hoje (commits `6869d8d` +
`f9199cf`):

- Smoke 2 min 120 s · **3 ticks, 0 falhas**, 625 trades históricos
  capturados, dedup confirmado (tick 2+ = 0 novos).
- Artefatos em `data/millennium_shadow/<RUN_ID>/` — JSONL append-only +
  heartbeat + logs. Kill flag via arquivo `.kill`.
- Systemd unit pronta (`deploy/millennium_shadow.service`,
  `deploy/README.md`) pra 24 h no VPS.
- Widget no detail do Millennium no cockpit, auto-refresh 5 s.

---

## Baseline 360d · config atual pós-grid (D_liberal)

Commit `<TBD>` — gate afrouxado depois de sweep de 4 configs via
`tools/millennium_gate_grid.py`.

Comparação 360d native side-by-side:

| Métrica    | A_baseline | D_liberal | Δ |
|------------|-----------:|----------:|---:|
| trades     | 117        | **136**   | +19 (+16 %) |
| WR         | 84.6 %     | 82.4 %    | −2.2 pp |
| Sharpe     | 5.69       | **6.08**  | +0.39 |
| Sortino    | 7.85       | **8.89**  | +1.05 |
| Calmar     | 28.6       | **29.9**  | +1.3 |
| ROI        | 22.3 %     | **26.3 %**| +4.0 pp |
| MDD        | 1.61 %     | 1.63 %    | +0.02 pp |
| PnL        | $2 231     | **$2 633**| +18 % |
| MC pct_pos | 100 %      | 100 %     | = |
| MC worst_dd| 1.61 %     | 1.63 %    | = |
| RoR        | 0 %        | 0 %       | = |

Por engine em D_liberal:
- CITADEL      n=16  WR=81.2 %  PnL +$490
- JUMP         n=46  WR=73.9 %  PnL +$1 116
- RENAISSANCE  n=74  WR=87.8 %  PnL +$1 027

Parâmetros afrouxados (vs Codex original):
- `JUMP_MIN_SCORE_BASE`      0.80 → 0.79
- `JUMP_MIN_SCORE_WEAK`      0.82 → 0.80  (era kill-switch de facto)
- `JUMP_MIN_SCORE_STRESSED`  0.84 → 0.81  (só 2 % de score passava)
- `PORTFOLIO_MIN_WEIGHT.JUMP`        0.32 → 0.25
- `PORTFOLIO_CHALLENGER_RATIO`       0.92 → 0.85
- `PORTFOLIO_REGIME_COOLDOWN_MULT.CHOP` 2.0 → 1.5
- `PORTFOLIO_MIN_ACCEPTED_SHARE.JUMP`  0.25 → 0.35

---

## Próximos passos pra trabalhar no Millennium

1. **Rodar shadow 24 h no VPS com a config D_liberal** — validar
   edge ao vivo sem capital real.
2. **Refinar ENGINE_NATIVE_INTERVALS** se shadow mostrar engine
   colocando trades em intervalo não validado OOS.
3. **Decidir fate dos pesos fantasmas (R3)** — remover
   `CITADEL_CAPITAL_WEIGHT` + `RENAISSANCE_CAPITAL_WEIGHT` da seção
   legada de `ensemble_reweight`.
4. **Avaliar streaming adapters pra JUMP e RENAISSANCE** — pré-requisito
   pra shadow virar execução real.
5. **Segundo grid fechado** se shadow apontar vazamento de edge
   específico (apenas com hipótese escrita antes, anti-fishing).

---

**Branch:** `feat/phi-engine` (12 commits hoje, 1 push ao remote)
**Suite:** 1103 passed, 7 skipped
