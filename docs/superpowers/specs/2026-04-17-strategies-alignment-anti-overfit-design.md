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

Alinhar o estado do repo com a realidade OOS **e** fortalecer o método
anti-overfit **antes** de qualquer nova tentativa de recalibração. Sem
isso, re-calibrar os colapsados vira fishing expedition.

## Princípio organizador

Três blocos em ordem estrita:

1. **Método** — infra que torna overfit detectável/prevenível.
2. **Limpeza** — alinhar claims em `params.py` e quarentenar engines
   quebrados. Nenhum número inflado fica em FROZEN ou no registry default.
3. **Forense** — investigar BRIDGEWATER (11.04 Sharpe / 9194 trades tem
   cheiro de bug, não de edge).

**Recalibração dos quebrados = sessão separada, depois deste design.** Não
entra aqui por princípio.

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

1. EXPERIMENTAL_SLUGS + banner warning nos 4 engines (Bloco 1.1 + 2.3)
2. Comentários params.py limpos (Bloco 2.1 + 2.2)
3. DSR em overfit_audit.py + plumbing save_run (Bloco 1.2)
4. Pre-commit hook (Bloco 1.4)
5. walkforward_v2.py esqueleto (Bloco 1.3)
6. Meta-trigger log (Bloco 1.5)
7. Forensic BRIDGEWATER (Bloco 3) — por último, rodada longa

---

## Notas

- Toda mudança no OneDrive-safe por força de `core/fs.robust_rmtree`
  se tocar dirs.
- Session log obrigatório ao final (`docs/sessions/...` + `docs/days/...`).
- Commits atômicos por bloco.
