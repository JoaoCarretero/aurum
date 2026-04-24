# Strategies Alignment + Anti-Overfit Hardening — Design
**Data:** 2026-04-17
**Contexto:** OOS audit 2026-04-16 testou 7 engines em janela pré-calibração
(2022-01 → 2023-01). Resultado: só 2 de 7 sobreviveram (CITADEL, JUMP).
3 colapsaram (DE SHAW, KEPOS, MEDALLION), 1 inflado 2× (RENAISSANCE),
1 suspect de bug (BRIDGEWATER). Ver
`docs/audits/2026-04-16_oos_verdict.md`.

**Gatilho meta disparado:** protocolo anti-overfit diz que 3 engines
consecutivos arquivados → PAUSAR e revisar método antes de recalibrar
qualquer coisa. DE SHAW + KEPOS + MEDALLION = 3. Este design responde ao
gatilho.

---

## Objetivo

1. **Validar** que o veredito OOS de ontem é metodologicamente honesto
   (audit-o-auditor) — antes de agir sobre ele.
2. **Alinhar** o estado do repo com o veredito (uma vez confirmado ou
   corrigido) — params.py honestos, quarentena dos quebrados.
3. **Fortalecer** o método anti-overfit (DSR, WF genuíno, flag
   EXPERIMENTAL, pre-commit hook) — antes de qualquer nova tentativa
   de recalibração. Sem isso, re-calibrar os colapsados vira fishing
   expedition.

## Princípio organizador

Quatro blocos em ordem estrita. **Bloco 0 é gate**: se invalidar o
audit, blocos 1-3 mudam.

0. **Validar o audit OOS** — audit-o-auditor. Antes de agir sobre o
   veredito de ontem, confirmar que ele é metodologicamente honesto.
1. **Método** — infra que torna overfit detectável/prevenível.
2. **Limpeza** — alinhar claims em `params.py` e quarentenar engines
   quebrados. Nenhum número inflado fica em FROZEN ou no registry default.
3. **Forense** — investigar BRIDGEWATER (11.04 Sharpe / 9194 trades tem
   cheiro de bug, não de edge).

**Recalibração dos quebrados = sessão separada, depois deste design.** Não
entra aqui por princípio.

---

## Bloco 0 — Validar o audit OOS (GATE)

Audit-o-auditor. Se qualquer etapa falhar, o veredito de ontem é
revisado **antes** de blocos 1-3 rodarem.

### 0.1 Reprodutibilidade bit-a-bit

- Script `tools/oos_revalidate.py` que:
  - Faz checkout do commit em que o audit original rodou
    (`6385565` ou o mais próximo com flag `--end` já mergeada).
  - Re-roda os 7 engines com **exatamente** os mesmos params/janela
    (`2022-01-01 → 2023-01-01`) e mesma seed.
  - Diffa report JSON: Sharpe/Sortino/ROI/MDD/n_trades batem ± 0.1%?
- Se divergir, investigar: seed não-determinística, data reload,
  params.py mudou, cache corrompido. **Não prossegue até bater.**

### 0.2 Simetria de custos

- Grep/audit em cada engine OOS-testado pra confirmar:
  - `SLIPPAGE`, `SPREAD`, `COMMISSION`, `FUNDING_PER_8H` aplicados
    no pipeline de PnL (não zerados, não pulados).
  - Nenhum código path de "backtest mode" que skipa custos.
- BRIDGEWATER é o primeiro suspeito (267% ROI). Se encontrar path
  sem custos, veredito "bug suspect" vira "bug confirmado", forense do
  Bloco 3 começa aqui mesmo.

### 0.3 Multi-janela OOS

Janela única é viés de amostragem. Rodar os 7 engines em:

- **BEAR puro:** 2022-01-01 → 2023-01-01 (já rodada).
- **BULL puro:** 2020-07-01 → 2021-07-01.
- **CHOP/transição:** 2019-06-01 → 2020-03-01.

Veredito revisado:
- ✅ edge real: sobrevive (Sharpe > 0) em 2+ janelas com sample
  significativo (>50 trades).
- ⚠️ edge de regime: sobrevive em 1 janela clara, degrada noutras.
- 🔴 overfit: colapsa em 2+ janelas ou não-disparou.

CITADEL já foi em 2 janelas (2022 BEAR + 2021 BULL). Falta 1 (CHOP).
JUMP, RENAISSANCE, BRIDGEWATER, DE SHAW, KEPOS, MEDALLION: 2 janelas
extras cada.

### 0.4 Sample-size floor

- Qualquer engine com `n_trades < 50` numa janela recebe veredito
  `INSUFFICIENT_SAMPLE`, não `COLLAPSED`.
- KEPOS com 0 trades não é "quebrado", é "não-disparou com defaults" —
  distinção importante pra decisão de quarentena.

### 0.5 DSR nos sobreviventes

Aplicar deflated Sharpe (Bailey & López de Prado) nos que passaram:

- Estimar `n_trials` histórico pra cada engine (git log + grep por
  `iter_` em params.py + memória de sessões).
- Calcular DSR pra CITADEL e JUMP nas janelas OOS positivas.
- DSR > 0 com p < 0.05 → edge robusto. DSR < 0 → claim inflado por
  multiple testing.

### 0.6 Look-ahead bias scan

Grep nos 7 engines + `core/` por padrões suspeitos:

- `.shift(-` (uso de valor futuro)
- `iloc[i+` com leitura
- `close` do candle atual usado em decisão que executa no mesmo candle
- `future_` / `ahead_` / `peek_` em nomes

Cada hit vira auditoria manual. Se confirmar leak, invalida o
backtest inteiro do engine.

### 0.7 Output do Bloco 0

`docs/audits/2026-04-17_oos_revalidation.md` com:
- Tabela reprodutibilidade (bate/não-bate por engine).
- Tabela custos (todos aplicados? sim/não por engine).
- Tabela multi-janela (Sharpe em cada regime).
- DSR pros sobreviventes.
- Lista de look-ahead hits.
- **Veredito final revisado por engine**, substituindo o de ontem.

**Gate:** se veredito mudar pra algum engine, blocos 1-3 são re-escritos
antes de executar. Se confirmar ontem, blocos 1-3 seguem como estão.

---

## Bloco 1 — Método (infra anti-overfit)

### 1.1 `EXPERIMENTAL_ENGINES` flag

- Em `config/engines.py`, adicionar `EXPERIMENTAL_SLUGS = frozenset(...)`
  análogo a `LIVE_READY_SLUGS`.
- Engines em EXPERIMENTAL:
  - não aparecem por default em launcher/cockpit
  - recebem banner warning explícito quando rodados ("OOS failed /
    non-functional defaults / overfit confirmed")
  - podem rodar, mas runs não são salvos como "calibration runs"
- Inicial: `DESHAW`, `KEPOS`, `MEDALLION`, `GRAHAM` (docstring já marca
  arquivado).

### 1.2 DSR em `analysis/overfit_audit.py`

- Adicionar `deflated_sharpe_ratio(sharpe, n_trials, skew, kurtosis, n)`
  seguindo Bailey & López de Prado.
- `save_run()` do cada engine passa a aceitar `n_trials` (default=1) e
  registra DSR junto do Sharpe bruto.
- Quando `n_trials > 1`, report exibe ambos (Sharpe raw / DSR) e flag
  visual se DSR < 0.
- **Não** reescrever nenhum engine. Só a função + plumbing.

### 1.3 Walk-forward genuíno — `analysis/walkforward_v2.py`

- Novo arquivo, não quebrar o atual (launcher/reports consomem).
- API: `run_genuine_wf(engine_slug, train_windows, test_windows, param_grid)`
  que re-fit em cada train e reporta metrics só do test.
- Hoje: **esqueleto + stub + doctring + testes de caracterização**, sem
  implementação real do re-fit. Issue criada pra sessão dedicada.
  Justificativa: re-fit genuíno requer refatorar como cada engine expõe
  params; escopo de 1-2 dias, não cabe na sessão de alinhamento.

### 1.4 Pre-commit hook contra `iter_N WINNER`

- `tools/hooks/pre-commit-no-winner.sh` + linha no
  `.git/hooks/pre-commit` (ou `pre-commit-config.yaml` se já houver).
- Rejeita commit que introduza comentário matching `iter\d+.*WINNER`
  em `config/params.py`.
- Mensagem de erro aponta pro protocolo e diz o formato correto:
  `tuned_on=[period], oos_sharpe=X`.

### 1.5 Protocolo anti-overfit — gatilho meta documentado

- `docs/methodology/anti_overfit_protocol.md` já existe. Adicionar
  subseção "Meta-trigger log" listando quando o gatilho foi disparado e
  qual revisão de método ocorreu. Hoje é o primeiro registro.

---

## Bloco 2 — Limpeza de claims

### 2.1 `config/params.py` — comentários inflados

Substituições exatas:

- Linha ~275: `RENAISSANCE: "15m", # Sharpe +5.65 @ 15m bluechip` →
  `RENAISSANCE: "15m", # tuned_on=[2023-05..2026-04], oos_sharpe=2.42 (2022-01..2023-01). Claim in-sample 5.65 era inflado 2×. Ver docs/audits/2026-04-16_oos_verdict.md`
- Linha ~284: idem em `ENGINE_BASKETS`.
- Linhas 396/401/403/409/416 (NEWTON/MERCURIO `iter_N WINNER`):
  substituir por `tuned_on=[last 1080d], status=pre-OOS-audit. Ver oos_verdict 2026-04-16`.

### 2.2 `FROZEN_ENGINES` — remover inflados

- Linha 502: `FROZEN_ENGINES = ["TWOSIGMA", "AQR", "RENAISSANCE"]` →
  **remover RENAISSANCE** do FROZEN. Motivo: edge real ~2.4 não justifica
  status FROZEN (que exige robustness clara). Vira engine normal com
  comentário honesto.

### 2.3 Quarentena via EXPERIMENTAL_ENGINES

- DE SHAW, KEPOS, MEDALLION entram em EXPERIMENTAL_SLUGS (ver 1.1).
- `engines/deshaw.py`, `engines/kepos.py`, `engines/medallion.py`:
  adicionar banner de warning no start que imprime status OOS e data
  do audit. Em modo `--ci` ou `--quiet` suprimir, mas logar.

---

## Bloco 3 — Forense BRIDGEWATER

Script único `tools/forensic_bridgewater.py` que:

1. Roda BRIDGEWATER na janela OOS 2022-01 → 2023-01 com trade-level
   logging completo (entry, exit, size, fees, funding, PnL, notional
   concorrente).
2. Valida:
   - custos C1+C2 foram aplicados a cada trade (não zero)
   - cap agregado L6 (`MAX_AGGREGATE_NOTIONAL`) não foi violado
   - posições sobrepostas não duplicam contribuição em PnL
3. Output: `docs/audits/2026-04-17_bridgewater_forensic.md` com
   veredito: "bug confirmado em X" ou "edge real assimétrico confirmado,
   mas implausível sem leverage alto".
4. **Sem fix**: se bug for encontrado, vira tarefa separada. Hoje só
   diagnóstico.

---

## Critérios de sucesso

- [ ] `tools/oos_revalidate.py` existe, roda, produz
      `docs/audits/2026-04-17_oos_revalidation.md` com veredito final
      por engine.
- [ ] Reprodutibilidade: todos os 7 engines batem ± 0.1% vs audit de
      ontem **ou** divergência investigada e resolvida.
- [ ] Simetria custos: tabela confirma C1+C2 aplicado em 7/7 (ou bug
      localizado pra um engine específico).
- [ ] Multi-janela: Sharpe reportado em 3 janelas (BEAR/BULL/CHOP) pros
      7 engines.
- [ ] DSR computado pra CITADEL e JUMP.
- [ ] Look-ahead scan concluído, hits documentados.
- [ ] `config/engines.py` tem `EXPERIMENTAL_SLUGS`, com 4 engines dentro.
- [ ] `config/params.py` não tem nenhuma linha matching `iter\d+.*WINNER`
      nem claim `+5.65` pra RENAISSANCE.
- [ ] `analysis/overfit_audit.py` exporta `deflated_sharpe_ratio` e tem
      pelo menos 1 teste unitário (paper de referência fixture).
- [ ] `analysis/walkforward_v2.py` existe com API definida, stub
      levantando `NotImplementedError("genuine WF — scope sessão
      dedicada, ver plan 2026-04-17")` + docstring.
- [ ] Pre-commit hook bloqueia `iter_N WINNER`. Teste manual: tentar
      commitar linha com o padrão → rejeita.
- [ ] `tools/forensic_bridgewater.py` rodado, output em
      `docs/audits/2026-04-17_bridgewater_forensic.md`.
- [ ] `docs/methodology/anti_overfit_protocol.md` tem seção
      "Meta-trigger log" com entrada de 2026-04-17.
- [ ] Suite existente: `python smoke_test.py --quiet` 100% pass.

## Out of scope (explícito)

- **Recalibrar** DE SHAW, KEPOS, MEDALLION. Protocolo proíbe até método
  estar pronto.
- **Implementar** o WF genuíno de fato. Só esqueleto + issue.
- **Fix** de eventual bug do BRIDGEWATER. Só diagnóstico.
- **Tocar no CORE protegido** (`core/indicators.py`, `core/signals.py`,
  `core/portfolio.py`, `config/params.py` valores numéricos). Só
  comentários de `params.py` mudam — nenhum número.
- PHI, AQR, TWO SIGMA, MILLENNIUM — não foram auditados OOS ainda.
  Ficam como estão, vão numa sessão separada.

## Testing

- Unit test `deflated_sharpe_ratio` contra exemplo do paper de referência.
- Teste de integração: rodar CITADEL curto → `save_run` grava DSR no
  report JSON. Verificar chave existe.
- Teste manual: pre-commit hook rejeita linha com `iter99 WINNER:`
  adicionada num `params.py` scratch.
- Smoke test completo: `python smoke_test.py --quiet` continua 100%.

## Ordem de build (sugerida)

### Gate — Bloco 0 primeiro

1. `tools/oos_revalidate.py` — reprodutibilidade (0.1)
2. Simetria de custos — audit estático do código (0.2)
3. DSR function em `overfit_audit.py` (0.5 precisa dela — antecipa 1.2)
4. Multi-janela runs — 6 engines × 2 janelas novas = 12 runs (0.3)
5. Look-ahead scan (0.6)
6. Consolidar `docs/audits/2026-04-17_oos_revalidation.md` (0.7)

**CHECKPOINT:** user revisa veredito. Se veredito mudar pra algum
engine, blocos 1-3 reescritos antes de seguir.

### Se veredito confirmado

7. EXPERIMENTAL_SLUGS + banner warning (Bloco 1.1 + 2.3)
8. Comentários params.py limpos (Bloco 2.1 + 2.2)
9. DSR plumbing no save_run (Bloco 1.2 — função já existe do passo 3)
10. Pre-commit hook (Bloco 1.4)
11. walkforward_v2.py esqueleto (Bloco 1.3)
12. Meta-trigger log (Bloco 1.5)
13. Forensic BRIDGEWATER (Bloco 3) — rodada longa, por último

---

## Notas

- Toda mudança no OneDrive-safe por força de `core/fs.robust_rmtree`
  se tocar dirs.
- Session log obrigatório ao final (`docs/sessions/...` + `docs/days/...`).
- Commits atômicos por bloco.
