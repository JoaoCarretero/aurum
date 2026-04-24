# Audit — Engines Live Rebuild Salvage

**Data:** 2026-04-23
**Branch:** `feat/research-desk`
**Escopo:** Decidir o que, do package `launcher_support/engines_live/` (rebuild
abandonado depois de rejeição UX), merece migrar pro cockpit legacy
`launcher_support/engines_live_view.py`.

## Contexto

Epic de rebuild R1–R5 completou 29 tasks, mas a UX do novo orquestrador
(cards V3 + layout D2 + hold-to-confirm) foi rejeitada pelo usuário
com "ficou muito ruim" (2026-04-23 ~19:24). O screen `screens/engines_live.py`
foi revertido pra chamar `engines_live_view.render` de novo (commits `b3795be` +
`7d59aaa`).

Esta auditoria avalia cada módulo do package rebuild contra o legacy, separando
o que é ganho real vs refactor de ego.

## Inventário do package rebuild (antes da deleção)

| Módulo | Linhas | Substitui legacy? | Veredito |
|--------|--------|-------------------|----------|
| `data/log_tail.py` | 69 | Adiciona `classify_level()` — legacy só dumpa texto | **✅ PORTADO** |
| `data/cockpit.py` | 149 | Dup de `_load_cockpit_runs_cached` | ❌ duplicata |
| `data/procs.py` | 87 | Dup de `_list_procs_cached` | ❌ duplicata |
| `data/aggregate.py` | 150 | `EngineCard` — só útil se renderizar cards | ❌ consumidor rejeitado |
| `widgets/pill_segment.py` | 78 | Dedup dos 2 pill handcrafted do legacy | ⚠️ refactor risk > ganho |
| `widgets/hold_button.py` | 114 | Hold-to-confirm (1.5s) | ❌ type-to-confirm legacy é mais seguro |
| `widgets/engine_card.py` | 145 | Card V3 | ❌ layout rejeitado |
| `panes/header.py` | 103 | Header do rebuild | ❌ layout rejeitado |
| `panes/strip_grid.py` | 168 | Grid de cards | ❌ layout rejeitado |
| `panes/research_shelf.py` | 210 | Shelf de engines não-rodando | ❌ layout rejeitado |
| `panes/detail*.py` | 620 | Detail pane D2 | ❌ layout rejeitado |
| `panes/footer.py` | 44 | Footer hints | ❌ layout rejeitado |
| `dialogs/new_instance.py` | 197 | Novo dialog | ❌ legacy tem equivalente |
| `dialogs/live_ritual.py` | 146 | Hold-to-confirm ritual | ❌ type-to-confirm é melhor |
| `state.py` | 80 | StateSnapshot + reducers | ❌ retrofit invasivo |
| `keyboard.py` | 156 | Routing table | ❌ retrofit invasivo |
| `view.py` | 329 | Orquestrador | ❌ rejeitado |
| `helpers.py` | 39 | Re-export shim | ❌ obsoleto |

Total: **~2950 linhas deletadas**, **1 win portado** (classifier de log).

## Ganhos integrados

### 1. Color log tail (`e377b6e`)

Portou `classify_level()` pro legacy como `_classify_log_level`. Adicionou
tabela de cores + Text tags no `_render_log_panel`. Substituiu dump de texto
monocromático por render por-linha com tag.

**Impacto:** log tail do cockpit agora destaca ERROR/WARN/EXIT/FILL/ORDER/SIGNAL
por cor. Zero mudança de layout ou interação — puramente aditivo.

### 2. Deleção do package órfão (`4535e23`)

Removeu 48 arquivos (26 do package + 22 testes órfãos + 1 integration test).
Nenhum consumidor externo — tudo self-referential dentro do package.

**Impacto:** −4836 linhas de código morto.

### 3. Refinamento do palette + classifier test (`0f34612`)

- Mudou `_LOG_LEVEL_COLORS` pra `_LOG_LEVEL_STYLE` com `(foreground, bold)`.
- INFO agora dimmed (noise fade atrás); SIGNAL/EXIT/ERROR bold (operator's eye).
- Collapsou branching no `_schedule_log_tail` — toda linha recebe tag da
  classe dela, INFO aplica DIM por design.
- Teste unitário lock-in do classifier: priority order
  (ERROR > WARN > EXIT > FILL > ORDER > SIGNAL > INFO), 18 casos.

## Métricas

- **Commits:** 3 (feature, chore, refactor)
- **Arquivos tocados:** 49 (1 modified, 48 deleted) + 1 novo teste
- **Linhas:** −4836 / +62
- **Suite launcher:** 233 passed, 12 skipped, 0 regressões
- **Core de trading tocado?** NÃO (`engines/`, `core/`, `config/` intocados)

## Decisões rejeitadas (por quê)

- **PillSegment:** dedup ~60 linhas de pills inline, mas o widget introduz uma
  abstração nova onde o código hardcoded já tá testado e funcional. Ganho
  modesto, risco real. Anti-pattern "refactor for its own sake."
- **HoldButton:** type-to-confirm do legacy é UX mais defensiva pra LIVE —
  obriga operador a digitar nome do engine. Hold 1.5s pode ser acidental.
- **State/keyboard refactor:** retrofit do reducer pattern no 4000-line view
  exige reescrever praticamente tudo. User já disse "ficou muito ruim" do
  rebuild completo — refazer meio caminho não dá.
- **EngineCard + aggregate:** sem consumer (cards rejeitados) = código morto.

## Notas operacionais

- IDE do usuário auto-staged WIP de `research_desk` durante a sessão — exigiu
  um `--force-with-lease` no terceiro commit pra separar. Commit final limpo.
- 2 failures pré-existentes em `tests/test_engines_live_view_cockpit.py`
  (unrelated — lambda signature issues e registry ordering) não causadas por
  esta sessão.

## Recomendação pós-audit

Fechar PR #2 (engines-frontend-rebuild) sem merge — todo ganho relevante
já foi portado. O branch fica como arquivo de design caso futuras iterações
do cockpit queiram revisitar UX alternativa.
