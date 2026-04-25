# ORNSTEIN v2 — Validation & Disposition

> Spec de **procedimento de validação** (não de feature). Decide se o preset
> `robust` + wrapper `engines/ornstein_v2.py` viram canônico ou arquivam, com
> base em evidência OOS honesta e anti-overfit protocol (`docs/methodology/anti_overfit_protocol.md`).

## Contexto

- Commit `a1fb95e` introduziu ORNSTEIN v1 (mean-reversion engine, research-only).
- Sessão subsequente (Claude + Codex, 2026-04-17 tarde/noite) produziu WIP
  uncommitted com dois lanes misturadas:
  - **Lane 1 (objeto deste spec):** preset `robust` + `ornstein_v2.py` wrapper
    + registry entry + 3 testes. Adiciona 5 params novos:
    `require_bb_confirmation`, `min_deviation_abs`, `min_target_distance_atr`,
    `post_partial_stop_offset_atr`, `exit_on_divergence_flip`.
  - **Lane 2 (fora do escopo):** hardening de `run_manager.compare_runs`,
    VPS host normalize, cockpit KPI reorder.
- Codex rodou `ornstein_v2 --basket bluechip_active --days 360` e obteve
  **0 trades em 19 símbolos**. Top vetos: `no_divergence`, `rsi_block`, `hurst_block`.
- Codex não rodou baseline (v1 default na mesma janela). Não dá pra saber se
  v2 matou o sample ou se v1 também gera pouco trade ali.
- O `hurst_threshold: 0.42` do preset `robust` contradiz o próprio commit de v1,
  que documenta: "crypto 15m shows H in [0.77, 1.0] regardless of macro regime —
  the exploratory preset disables the Hurst gate with a comment explaining why."

## Goal

Decidir uma disposição definitiva pra ORNSTEIN v2:
- **Promove** pra canonical (seguido de `overfit_audit 6/6`), OU
- **Remove guard(s) estrutural(is)** e re-avalia, OU
- **Arquiva**, revertendo os 5 params novos de `engines/ornstein.py`, deletando
  `engines/ornstein_v2.py` e des-registrando de `config/engines.py`.

## Non-Goals

- Não tocar em `ornstein` v1 além de adicionar/remover os 5 params do `robust`.
- Não mudar `core/indicators.py`, `core/signals.py`, `core/portfolio.py` ou
  `config/params.py` (core de trading protegido).
- Não calibrar thresholds dos guards durante ablation (guards são on/off,
  não tuneados — caso contrário vira fishing expedition).
- Não mudar universe, window ou custos durante a validação (frozen).
- Lane 2 (run_manager, VPS, cockpit) é commit à parte, feito ANTES da validação
  começar. Fora do escopo deste spec.

---

## Protocol (4 etapas, execução linear)

### Etapa 0 — Prep (commit split)

Antes de qualquer backtest:

1. Stage e commit de Lane 2 sozinho (`run_manager._resolve_compare_run_dir`,
   VPS host normalize, cockpit KPI reorder + tests). Mensagem:
   `hardening: run_manager compare lookup + vps host parse + cockpit order`.
2. WIP de Lane 1 (ornstein_v2) fica unstaged.

Motivo: manter commits atômicos. Se Lane 1 for revertida, Lane 2 sobrevive.

### Etapa 1 — Baseline frozen

```
python -m engines.ornstein --preset default --basket bluechip_active --days 360 --no-menu
```

Registrar do `summary.json` do run dir: `n_trades, sharpe, max_dd, win_rate,
avg_r, total_return`. Computar DSR via `analysis/dsr.py` com `n_trials=1`.

Este é o número que v2 precisa bater. Frozen. Não se re-roda nem se retune
depois.

### Etapa 2 — Reprodução do Codex (sanity)

```
python -m engines.ornstein_v2 --basket bluechip_active --days 360 --no-menu
```

Confirmar que dá ~0 trades como Codex reportou. Inspecionar distribuição
COMPLETA de `vetos` no log final (não só top-3) pra ver qual combinação de
guards zerou o sample.

### Etapa 3 — Ablation do `robust` (universo reduzido pra iteração rápida)

Universo fixo: `--symbols BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT`.
Janela: `--days 180`.

Ablation = **1 run de referência + 7 variantes**:

| Run | Preset base | Mudança |
|-----|-------------|---------|
| B_MAJORS | `default` (v1) | baseline reduzido — comparador pras 7 variantes |
| R0  | `robust`    | nenhuma (reprodução local de `robust` no universo reduzido) |
| R1  | `robust`    | `hurst_threshold = 0.55` (volta default v1) |
| R2  | `robust`    | `require_bb_confirmation = False` |
| R3  | `robust`    | `min_deviation_abs = 0.0` |
| R4  | `robust`    | `min_target_distance_atr = 0.0` |
| R5  | `robust`    | `exit_on_divergence_flip = False` |
| R6  | `robust`    | `post_partial_stop_offset_atr = -1.0` (flag off) |

Comando referência:

```
python -m engines.ornstein --preset default --symbols BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT --days 180 --no-menu
```

Pra cada run, preencher a tabela de resultados em `docs/engines/ornstein_v2/2026-04-17_validation.md`:

| Variant | N_trades | Sharpe | MaxDD | WinRate | Δ Sharpe vs B_MAJORS |
|---------|----------|--------|-------|---------|----------------------|
| B_MAJORS (v1 default / majors / 180d) | — | — | — | — | 0.00 |
| R0 robust_full | — | — | — | — | — |
| R1 no_hurst | — | — | — | — | — |
| R2 no_bb | — | — | — | — | — |
| R3 no_min_dev | — | — | — | — | — |
| R4 no_target_dist | — | — | — | — | — |
| R5 no_div_flip | — | — | — | — | — |
| R6 no_stop_lock | — | — | — | — | — |

Objetivo: identificar qual(is) guard(s) individualmente zera(m) sample ou
destroem Sharpe. Hurst é suspeito #1 (ver contexto).

**Engenharia da ablation:** os guards atuais são campos de `OrnsteinParams`,
não CLI flags. Criar script efêmero `tools/ornstein_v2_ablation.py` que:
- importa `ornstein.main` diretamente,
- aplica `robust` preset + 1 override por variant (via kwargs em `OrnsteinParams`),
- roda os 8 runs sequencialmente,
- escreve uma tabela CSV em `data/ornstein_v2/ablation_2026-04-17/results.csv`.

Isolar aqui, não poluir `engines/ornstein.py` com presets temporários
(`robust_no_hurst` etc). Script é deletável depois, o código do engine não.

### Etapa 4 — Decision (regra pré-registrada)

Após Etapa 3, escolher a MELHOR variant entre R0..R6 pelo score
`Sharpe / (1 + MaxDD)` exigindo `N_trades ≥ 20` na janela reduzida. Rodar
ELA + `ornstein --preset default` em `--basket bluechip_active --days 360`
(janela full). O baseline full já foi medido na Etapa 1 — re-uso, não re-roda.

Aplicar decision matrix:

| Condição | Ação |
|----------|------|
| `DSR(best) > DSR(default)` **E** `N_trades(best) ≥ 30` **E** `Sharpe(best) > Sharpe(default) × 1.10` | **Promove.** Preset final (só com os guards que sobreviveram) substitui `robust`. Próximo: overfit_audit 6/6 em janelas OOS distintas. |
| Ablation mostra 1 guard sozinho zera sample **E** removendo ele uma variant bate critério acima | Remove esse guard do preset. Promove sem ele. |
| Nenhuma variant bate critério | **Arquiva v2.** Ações de arquivamento abaixo. |

**Ações de arquivamento (se decisão = arquiva):**

1. Em `engines/ornstein.py`: remover os 5 campos novos de `OrnsteinParams`,
   remover preset `robust` de `ORNSTEIN_PRESETS`, remover lógica de
   `post_partial_stop_offset_atr`, `exit_on_divergence_flip`, `min_deviation_abs`,
   `min_target_distance_atr`, `require_bb_confirmation` de `_resolve_ornstein_exit`
   e `scan_symbol`. Reverter assinatura de `main()` pra sem `default_preset`/
   `default_out` kwargs (ou manter se for usado por outros wrappers — checar).
2. Deletar `engines/ornstein_v2.py`.
3. Remover entry `ornstein_v2` de `config/engines.py`.
4. Remover 3 testes novos em `tests/test_ornstein.py`
   (`test_resolve_exit_locks_stop_after_partial`,
   `test_resolve_exit_on_divergence_flip`,
   `test_robust_preset_enables_harder_guards`).
5. Commit atômico: `revert(ornstein): archive v2 robust preset — failed honest OOS validation`.
6. Preservar no commit body um resumo quantitativo (tabela da Etapa 3) e link
   pro validation doc.

---

## Output Artifacts

| Artifact | Path | Criado em |
|----------|------|-----------|
| Run dirs v1 default | `data/ornstein/<run_id>/` | Etapas 1, 3 (baseline), 4 |
| Run dirs v2 variants | `data/ornstein_v2/<run_id>/` | Etapas 2, 3, 4 |
| Ablation script | `tools/ornstein_v2_ablation.py` (novo, efêmero — pode ser removido no commit final se arquivar) | Etapa 3 |
| Validation report | `docs/engines/ornstein_v2/2026-04-17_validation.md` | Etapa 4 (antes do decision commit) |
| Decision commit | git | Etapa 4 |

`2026-04-17_validation.md` deve conter:
- Contexto (1 parágrafo).
- Tabela baseline vs Codex repro (Etapas 1-2).
- Tabela ablation completa (Etapa 3).
- Tabela final best variant vs baseline em 360d (Etapa 4).
- Decisão explícita + justificativa + próximos passos.

---

## Anti-overfit Guarantees

Cada item abaixo é uma pré-commitment. Se violar, PARA e re-lê o spec.

1. **Baseline (v1 default) imutável.** Não se re-roda nem se re-tune. Primeiro
   valor medido é o valor usado.
2. **Universe e window congelados.** Full: `bluechip_active / 360d`. Fast-iter:
   `BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT / 180d`. Trocar universe pra achar
   número bonito é cherry-pick.
3. **Guards on/off, nunca calibrados.** Ablation testa binário (presente vs
   ausente), não varia threshold. Se a lógica é "guard X ajuda com threshold
   Y", cria issue separada pra próximo sweep com grid fechado — não mistura
   aqui.
4. **Decision rule pré-registrada.** Tabela acima. Critérios numéricos
   (`DSR > baseline`, `N_trades ≥ 30`, `Sharpe × 1.10`) são fixos. Se não
   bater, arquiva. Sem "mas quase bateu, vamos iterar mais uma".
5. **Regra de parada honrada.** Se Etapa 4 → arquiva, ARQUIVA. Sem
   "reformular universo", sem "testar janela diferente", sem "trocar símbolo".
   Isso é a regra 5 do anti-overfit protocol.
6. **Sem DSR handwave.** DSR computado com `n_trials = 1` na baseline (roda
   única) e `n_trials = 7` em Etapa 3 (7 runs de ablation). DSR haircut por
   trials é obrigatório — Sharpe "puro" não conta.
7. **Tudo documentado em `validation.md` antes do commit final.** Auditável.

---

## Scope Check

Single implementation plan? Sim — protocolo é linear, 4 etapas sequenciais,
output é uma decisão binária (promote/archive) com um caminho residual
(remove-guard-and-retest). Não precisa decomposição.

## Testing

- Testes unitários dos guards novos (`test_resolve_exit_*`,
  `test_robust_preset_enables_harder_guards`) já existem. Passa/falha é
  função do código, não da validação.
- `pytest tests/test_ornstein.py` roda verde em todos os passos (antes e
  depois de cada commit).
- Se decisão = arquiva, rodar `pytest tests/test_ornstein.py` após a remoção
  pra confirmar que remoção dos 3 testes novos não quebra outros.

## Open Questions (travadas antes de começar)

- Nenhuma. Universo, janela, critério, decision rule, artifacts — tudo
  fechado neste spec.
