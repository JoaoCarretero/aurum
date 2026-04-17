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

## Próximos passos pra trabalhar no Millennium

1. **Baseline fresh 60–90 d com pesos atuais** — em execução agora em
   background (`echo '1\n60\n...' | python engines/millennium.py`).
   Esperado: Sharpe positivo, sem domínio de uma engine só, MDD saudável.
2. **Rodar shadow 24 h no VPS** — com MILLENNIUM CORE OPERATIONAL para
   validar edge ao vivo sem capital real.
3. **Refinar ENGINE_NATIVE_INTERVALS** se baseline mostrar alguma
   engine colocando trades em intervalo não validado OOS.
4. **Decidir fate dos pesos fantasmas (R3)** — remover
   `CITADEL_CAPITAL_WEIGHT` + `RENAISSANCE_CAPITAL_WEIGHT` da seção
   legada de `ensemble_reweight`.
5. **Avaliar streaming adapters pra JUMP e RENAISSANCE** — pré-requisito
   pra shadow virar execução real.

---

**Branch:** `feat/phi-engine` (12 commits hoje, 1 push ao remote)
**Suite:** 1103 passed, 7 skipped
