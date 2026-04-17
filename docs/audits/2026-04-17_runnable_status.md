# Engines — Runnable Status HOJE (2026-04-17)

**Mandato:** Joao 2026-04-17 — "deixar todas as estratégias rodáveis hoje,
nem que seja edge pior, mas condizentes com a realidade do mercado HOJE."

**Critério de "rodável":** roda sem crash, produz output coerente,
Sharpe documentado (pode ser negativo — é realidade).

**Janela de teste:** last 360 days ending 2026-04-17 (no `--end`).

---

## Resultados

| Engine | Sharpe | Trades | ROI% | MDD% | Status | Veredito |
|---|---|---|---|---|---|---|
| CITADEL | 2.958 | 300 | 22.09 | 6.36 | ✅ rodável | edge real |
| RENAISSANCE | 6.158 | 241 | 17.22 | 0.98 | ✅ rodável | edge forte (low DD) |
| JUMP | 3.737 | 129 | 19.00 | 2.04 | ✅ rodável | edge forte |
| BRIDGEWATER | 13.113 | 11165 | 355.29 | 6.73 | ⚠️ rodável | Sharpe alto suspeito — verificar se é regime atual ou bug residual |
| DE SHAW | ~-1.9 | ~300 | -19.45 | 30.7 | 🔴 rodável | edge negativo, quarentena |
| KEPOS | 0.000 | 0 | 0.00 | 0.00 | 🔴 rodável | 0 trades mesmo pós-fixes, quarentena |
| MEDALLION | -3.690 | 203 | -35.15 | 34.77 | 🔴 rodável | edge negativo, quarentena |

(DE SHAW run: `data/deshaw/2026-04-17_094931` — 2/7 overfit audit FAIL)

---

## Fixes aplicados hoje

| Commit | Fix | Impacto |
|---|---|---|
| `9b41c76` | `core/sentiment.py` aceita `end_time_ms` — funding/OI/LS bounded | **BRIDGEWATER BEAR 2022: 11.04 → 3.03 Sharpe** (bug era real) |
| `18db6dc` | KEPOS+MEDALLION cost asymmetry — entry com SLIPPAGE+SPREAD | ~3 bps/trade mais honesto; Sharpe in-sample deve cair alguns décimos |
| `55857f3` | `config/params.py` comentários honestos (RENAISSANCE 5.65→2.42, iter_N WINNER removidos) | Claims alinhados com OOS real |
| `55857f3` | `engines/kepos.py` eta_critical 0.95→0.75 | Reduz 1 dos 4 ANDs. Ainda 0 trades em last-360d. |
| `cc4a642` | `config/engines.py` EXPERIMENTAL_SLUGS flag criada | Quarentena formal pra engines sem edge confirmado |
| `d7d91bb` | `docs/methodology/anti_overfit_protocol.md` meta-trigger log | Registro do primeiro disparo (3 arquivados consecutivos) |
| (pendente) | `engines/kepos.py` eta_sustained_bars 10→5 | Afrouxa 2º AND. Esperado disparar trades. |

Paralelamente, Codex:
| Commit | Fix |
|---|---|
| `1085c32` | Security fixes — gitignore keys.json.enc, risk_gates defaults, telegram allowlist, Binance REST URL, audit chain default |
| `c1ab62d` | Refactor CORE — remove v3.7 dead code (`_omega_risk_mult`, `OMEGA_RISK_TABLE`), document `label_trade` off-by-one |
| `ae6dbde` | Full system audit doc + CLAUDE.md engines table update |

Refinou `engines/bridgewater.py` (sentiment limits dimensionados por `window_days`, alinhamento série→candles sem leak pre-série) — apenas trabalho dele, não commitado na cópia que eu vi mas provavelmente em arquivo uncommitted.

---

## Verdicts finais por engine

### ✅ Production-ready
- **CITADEL** — edge real confirmado OOS (3 janelas) + last-360d. Sharpe 2.96.
- **JUMP** — edge real confirmado OOS (BEAR 2022: 3.15) + last-360d (3.74).
- **RENAISSANCE** — edge moderado mas robusto. OOS 2.42, last-360d 6.16. MDD excepcional (<2%).

### ⚠️ Rodável com ressalva
- **BRIDGEWATER** — bug crítico de live sentiment fixado. BEAR 2022: Sharpe 3.03 (honesto). last-360d: 13.11 (suspeito — verificar se é edge real em regime atual ou residual). Monitorar próximo sweep.

### 🔴 Quarentena (EXPERIMENTAL_SLUGS)
- **DE SHAW** — cointegração crypto quebra em regime shifts. Rodável, edge -1.9 Sharpe last-360d. Precisa rework (regime filter? apenas CHOP?).
- **KEPOS** — 4 ANDs rígidos nos gates de entrada. eta 0.95→0.75 + sustained 10→5 planejado. 0 trades mesmo pós-fixes. Engine genuinamente rare-signal.
- **MEDALLION** — grid-best in-sample foi overfit canônico (Codex audit). Pós-cost-fix, -3.69 Sharpe. Não carrega edge fora do train.
- **GRAHAM** — arquivado.

### ⚪ Fora de escopo do audit
- **AQR, TWO SIGMA, MILLENNIUM** — meta-engines, dependem dos directional. Rodam se os directional rodam.
- **JANE STREET** — arb, categoria separada. Redesign backlog próprio (Fase A-E).
- **PHI** — novo, scaffold 23 tests pass, gatekept até 6/6 overfit pass.
- **WINTON** — meta regime analysis, não é signal engine.
- **LIVE** — runtime, não é signal engine.

---

## Próximos passos sugeridos

1. **Re-test KEPOS** pós `eta_sustained_bars` 10→5 — verificar se dispara trades.
   Se ainda 0, remover da EXPERIMENTAL_SLUGS e arquivar (como GRAHAM).
2. **Investigar BRIDGEWATER** last-360d Sharpe 13.11 — distinguir entre:
   (a) edge real em regime atual (bull top → muitos overleverage setups);
   (b) algum outro leak residual (position sizing? aggregate cap?);
   (c) matemática legítima de high-frequency contrarian.
3. **Fix DE SHAW**: regime filter via HMM — só operar em CHOP.
4. **Decidir**: MEDALLION — arquivar (como GRAHAM) ou reformular mecanismo?
5. **Bloco 2-3 da spec original** (limpeza de claims + forense BRIDGEWATER)
   — em grande parte endereçado, resta atualizar `FROZEN_ENGINES` (tirar RENAISSANCE, que OOS não justifica FROZEN).

## Arquivos modificados por Claude (esta onda)

- `core/sentiment.py` — end_time_ms parameter
- `engines/bridgewater.py` — pass END_TIME_MS (Codex refinou depois)
- `engines/kepos.py` — cost fix + threshold defaults
- `engines/medallion.py` — cost fix
- `config/params.py` — comentários honestos, iter_N WINNER cleanup
- `config/engines.py` — EXPERIMENTAL_SLUGS flag
- `docs/methodology/anti_overfit_protocol.md` — meta-trigger log
- `docs/audits/2026-04-17_runnable_status.md` — este doc
