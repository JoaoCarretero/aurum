# Launcher Screen Manager — Design Spec

**Date:** 2026-04-20
**Author:** Claude (sessão com João)
**Status:** Draft — awaiting user review
**Related:** Follow-up da sessão de limpeza-geral 2026-04-20 (este spec ataca lag percebido na navegação do launcher, não coberto pela limpeza anterior)

---

## Goal

Eliminar o lag "FPS baixo" na navegação entre telas do `launcher.py`,
trocando o pattern `destroy+rebuild` por um **ScreenManager** com cache
de widgets. Migração **híbrida** (incremental, telas não-migradas
continuam funcionando pelo caminho antigo).

**Entrega deste spec (primeiro incremento):**
1. Infra: `Screen` ABC + `ScreenManager` + métricas de timing
2. Instrumentação do caminho antigo (~10-15 call sites) pra gerar
   baseline comparável
3. Primeira screen migrada como piloto: **menu inicial**
4. Testes (unit + integration + regression do piloto)
5. Doc curto em `docs/architecture/screen_manager.md` pra orientar
   próximas migrações

Migrações subsequentes (cockpit, runs history, engines live, etc.) são
fora do escopo deste spec — cada uma ganha seu próprio plan.

## Problem

João relata que o launcher "lagga estilo FPS baixo ou jogo sem VSync"
ao **trocar de tela** (ex: menu → cockpit) e ao **navegar dentro de
telas com listas** (scroll, setas). Startup é OK (~2s cold). O que
dói é a **interação**.

### Evidence

Grep no `launcher.py`:

- **50 chamadas** de `.destroy()` — anti-pattern clássico Tk de
  destruir todos os children e reconstruir do zero
- **10 locais** com o pattern `for w in X.winfo_children(): w.destroy()`
  (L1383, L3977, L4350, L4486, L4613, L5842, L5859, L5934, L6058,
  L6753, L6836, L7174, ...)
- **77 `.after()` timers** — polling ativo. Callbacks síncronos
  pesados aqui somam frame-budget.
- **Zero `.update()` / `.update_idletasks()` manuais** — não é forçando
  redraw; o problema é rebuild puro.

### Root cause

Cada screen switch:
1. `.destroy()` em 40-200 widgets filhos (~50-150ms)
2. Recria tudo via `tk.Label/Frame/Button/...` (layout solver re-dispara)
3. Re-pack/grid triggera reflow global
4. Se há dados live, refetch síncrono agrega latência

Soma = 100-400ms por switch, sentido como "lag".

## Non-goals

- **Não** otimiza rendering do Tk em si (fora do controle — limitação do toolkit)
- **Não** troca Tk por outro framework (PyQt, web, etc — scope bomba)
- **Não** migra todas as ~15+ screens neste spec (migração incremental)
- **Não** refactora `launcher.py` pra reduzir tamanho (outro problema, outro spec)
- **Não** mexe em CORE PROTEGIDO (`core/indicators.py`, `core/signals.py`, `core/portfolio.py`, `config/params.py`)
- **Não** altera keybindings globais ou roteamento de menu principal
- **Não** altera modo "antigo" das telas não-migradas — convivência via subcontainer

## Architecture

### Conceito central

Separar **widgets** (criados uma vez) de **dados** (atualizados a cada
entrada na tela):

```
ScreenManager
├── _cache: dict[name → Screen]        # instâncias montadas
├── _current: Screen | None            # tela visível agora
├── _container: tk.Frame               # onde screens vivem
└── show(name, **kwargs) -> Screen
      ├── _current.on_exit() + pack_forget()
      ├── cache miss → Screen(parent=_container) + build()
      ├── screen.on_enter(**kwargs)  # refresh dado se mudou
      ├── screen.pack()
      └── metric: launcher.screen.<name>.{first_visit|reentry}_ms

Screen (ABC)
├── __init__(parent)
├── build()          # widgets uma vez (sem .destroy() futuro)
├── on_enter(**kw)   # cada vez que mostra (refresh dado)
├── on_exit()        # cada vez que esconde (para timers/bindings)
└── update_data()    # helper: configure() nos widgets existentes
```

### Por que híbrido

- **Não quebra nada hoje**: telas não-migradas seguem no caminho antigo
- **Ship incremental**: cada screen migrada = 1 PR com ganho medível
- **Risco controlado**: se uma migração der ruim, reverte só aquela
- **Parada honrada**: se nas 3 primeiras migrações o lag sumiu, pode
  parar sem migrar o resto (vai seguir o princípio YAGNI)

### Convivência antigo + novo

```
launcher.py
├── self.main                    # container principal (inalterado)
│   ├── <widgets antigos>        # telas não-migradas vivem aqui
│   └── self.screens_container   # novo: Frame dedicado ao ScreenManager
│       └── <screens migradas>   # pack/forget aqui, isolado do resto
```

Qualquer tela antiga continua fazendo `for w in self.main.winfo_children(): w.destroy()` — não afeta o `screens_container` porque é independente.

## Components

### New files

```
launcher_support/screens/
├── __init__.py          # re-exports Screen, ScreenManager
├── base.py              # Screen ABC + ScreenManager (~200 linhas)
├── _metrics.py          # helpers de timing + runtime_health integration (~50 linhas)
└── menu.py              # piloto: MenuScreen migrado (~200-300 linhas)

tests/launcher/
├── __init__.py
├── test_screen_manager.py       # unit tests com mock Screen (~250 linhas)
└── test_menu_screen.py          # regression do piloto (~100 linhas)

docs/architecture/       # dir novo (criar no plan)
└── screen_manager.md    # guide curto pra migrações futuras
```

### Modified files

```
launcher.py
├── __init__: adicionar self.screens_container + self.screens = ScreenManager(...)
├── @timed_legacy_switch("name") nos ~10-15 sites de destroy+rebuild (2-3 linhas cada)
├── Remover código do menu inicial antigo (ou mantê-lo como fallback via feature flag)
└── Rotas "back to menu" / startup → self.screens.show("menu")
```

Impacto total em `launcher.py`: ~50-80 linhas modificadas (majoritariamente
decorators + remoção de bloco do menu antigo). NÃO é refactor massivo.

## Data Flow

### Primeira visita (cache miss)

```
user click/key "menu"
  ↓
ScreenManager.show("menu", from_screen="cockpit")
  ↓
_t0 = time.perf_counter()
  ↓
cache miss → MenuScreen(parent=self._container)
  ↓
menu.build()
  ├── cria todos os widgets (Labels, Buttons, Frames)
  └── configura layout (grid/pack) uma vez
  ↓
menu.on_enter(from_screen="cockpit")
  ├── atualiza dados iniciais (label com usuário, últimos runs, etc)
  └── registra timers via self._after(ms, cb)  [auto-cleanup]
  ↓
menu.pack(fill="both", expand=True)
  ↓
_current = menu; _cache["menu"] = menu
  ↓
runtime_health.record("launcher.screen.menu.first_visit_ms", (now - _t0)*1000)
```

### Visita subsequente (cache hit)

```
user click/key "menu"
  ↓
ScreenManager.show("menu", from_screen="cockpit")
  ↓
_t0 = time.perf_counter()
  ↓
_current.on_exit()
  ├── cancela _after timers (auto via base class)
  └── unbind widgets registrados via self._bind (auto)
  ↓
_current.pack_forget()
  ↓
cache hit → menu (reutiliza mesma instância)
  ↓
menu.on_enter(from_screen="cockpit")
  ├── refresh de dados dinâmicos (últimos runs mudaram?)
  └── re-registra timers se precisar
  ↓
menu.update_data()  # opcional — configure() em labels que mudaram
  ↓
menu.pack(fill="both", expand=True)
  ↓
_current = menu
  ↓
runtime_health.record("launcher.screen.menu.reentry_ms", (now - _t0)*1000)
```

### Baseline antigo (instrumentado)

```python
# Em cada call site de destroy+rebuild
@timed_legacy_switch("results")
def _render_results(self):
    for w in self._results_body.winfo_children(): w.destroy()
    # ... recria tudo ...

# Decorator registra:
#   runtime_health.record("launcher.screen.results.legacy_rebuild_ms", ms)
```

Isso permite comparar `legacy_rebuild_ms` vs `reentry_ms` no piloto
(ordem de grandeza esperada: 100-300ms → 5-20ms, **10-30× speedup**).

## Error Handling

| Falha                                     | Reação                                                                                                                  |
|-------------------------------------------|-------------------------------------------------------------------------------------------------------------------------|
| `Screen.build()` raise                    | Log `runtime_health.record("screen.<name>.build_error")`, fallback pra error screen ("falhou a montar — F5 pra retry") |
| `Screen.on_enter()` raise                 | Keep `_current` screen, toast no footer, log                                                                            |
| Cache instance corrupta (estado inválido) | Evict entry, rebuild from scratch na próxima `show()`, log warning                                                      |
| Timer `.after()` não cancelado            | Detectado em debug mode (`AURUM_SCREEN_DEBUG=1`), log assertion; em produção silencioso (não crasha)                    |
| `ScreenContextError` (kwargs faltando)    | Keep current, toast "tela X precisa de <param>", log                                                                    |
| Screen desconhecida (name não registrado) | `ValueError` ao chamar `show()`; call site é bug                                                                        |

**Exceções definidas em `launcher_support/screens/base.py`:**
- `ScreenError(Exception)` — base
- `ScreenBuildError(ScreenError)` — raised when `build()` falha
- `ScreenContextError(ScreenError)` — raised pelo próprio Screen quando kwarg obrigatório falta (ex: `run_id` não passou mas tela espera)

## Testing Strategy

### Unit — `tests/launcher/test_screen_manager.py`

Sem Tk real. Usa mock `FakeScreen` com contadores.

- `test_first_show_creates_and_caches`
- `test_second_show_reuses_cache`
- `test_show_exits_previous_before_enter_next`
- `test_on_enter_receives_kwargs`
- `test_build_error_falls_back_to_error_screen`
- `test_on_enter_error_keeps_current`
- `test_after_timer_canceled_on_exit`
- `test_unknown_screen_raises`
- `test_metric_recorded_on_show`

### Integration — `tests/launcher/test_menu_screen.py`

Tk real com `root.withdraw()`. Fixture `tk_root` session-scoped.

- `test_menu_builds_expected_children_structure` (compara count + tipo com baseline do menu antigo)
- `test_menu_shortcuts_still_work` (dispara hotkeys, confere callback chamado)
- `test_menu_reentry_is_faster_than_first_visit` (timing relative, não absoluto)
- `test_menu_after_cockpit_navigation_ok` (sanity: show("cockpit"), show("menu"), back)

Marcador `@pytest.mark.gui` pra skip condicional se `DISPLAY` ausente (CI linux).

### Regression

Menu inicial migrado deve ter paridade funcional com antigo:
- Mesmos botões (compare label text)
- Mesmos keybindings (compare via `widget.bind()` dump)
- Navegação daqui pra outros screens inalterada
- Visual paridade não-regressão via screenshot opcional (descontado do spec; fica pra depois)

## Success Criteria

1. **Quantitativo**: menu inicial `reentry_ms` ≤ 50ms **E** delta vs
   `legacy_rebuild_ms` ≥ 3× (ambas condições). Target suave pra
   acomodar variação de máquina — o delta é o que vale. Baseline
   esperado: 100-300ms no antigo.
2. **Qualitativo**: João navega main→menu→main e **não sente lag**.
3. **Zero regressão**: smoke test 178/178, suite full passa com os novos testes.
4. **Infra pronta**: migrar a 2ª screen é trabalho de 30min (só estender `Screen`, registrar no manager).
5. **Documentação**: `docs/architecture/screen_manager.md` descreve o pattern pra próximas migrações.

## Risks

| Risco                                                                    | Mitigação                                                                                                   |
|--------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------|
| Menu inicial tem acoplamento cross-screen (CodeViewer, globals)          | Primeira task da implementação é LER o código atual do menu antes de refactor                               |
| `.after()` timers vazando                                                | Base class oferece `self._after(ms, cb)` com cleanup auto em `on_exit`                                     |
| Keybindings registrados no escopo da screen                              | Base class oferece `self._bind(widget, seq, cb)` com unbind auto em `on_exit`                              |
| Testing Tk flaky em Windows                                              | Unit tests com mock (maioria); integration marcado `@pytest.mark.gui` — opcional                            |
| Convivência antigo + novo confusa                                        | `screens_container` isolado em subcontainer; nunca mexer em `self.main.winfo_children()` do ScreenManager  |
| Cache sem eviction                                                       | Documentar em doc; ~20 screens desktop OK. Se virar problema, LRU depois                                   |
| João migra só o piloto e deixa 90% das screens no caminho antigo         | Aceitável — princípio híbrido. Instrumentação ainda dá valor pra priorização futura                        |
| Regressão silenciosa na UX do menu                                       | Regression test compara estrutura + shortcuts; João usa uma vez antes de merge                              |

## Migration Plan (beyond this spec)

**Após este spec entregar**, próximas migrações seguem ordem baseada em
dados coletados pela instrumentação do caminho antigo:

1. Coletar 1-2 dias de uso normal com a instrumentação
2. Ranquear screens por `legacy_rebuild_ms` médio × frequência de acesso
3. Top 3 viram planos individuais, cada um segue o mesmo pattern do piloto
4. Parar quando lag não for mais perceptível (YAGNI)

Cada migração adicional toca ~1-2 arquivos + ~200-400 linhas novas em
`launcher_support/screens/<name>.py`.

## References

- Session log fonte: `docs/sessions/2026-04-20_1337.md`
- Sub-B do limpeza-geral (perf base): `8936fdb` (lazy core init)
- CLAUDE.md (CORE PROTEGIDO, keys.json rules)
- `launcher.py` call sites de `destroy()` — grep cited in Evidence section
- `core/ops/health.py` — `runtime_health.record()` API usado pra métricas

---

*Spec end. Implementation plan será gerado via `writing-plans` skill
após aprovação deste documento.*
