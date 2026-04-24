# Screen Manager — Migration Guide

Infra: `launcher_support/screens/` package.
Spec: `docs/superpowers/specs/2026-04-20-launcher-screen-manager-design.md`.
First migration (piloto): `SplashScreen` (`launcher_support/screens/splash.py`).

## Why

`launcher.py` historically switches screens via `for w in X.winfo_children(): w.destroy()` + rebuild. With 40-200 widgets por tela, o destroy + re-layout custa 100-300ms — sentido como "FPS-low lag". `ScreenManager` mantém widgets vivos across visits; switch vira `pack_forget()` + `pack()` (sub-ms).

## Contrato da Screen

Toda screen migrada herda de `Screen` (veja `base.py`):

```python
from launcher_support.screens.base import Screen

class MyScreen(Screen):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app  # Terminal instance — drawing helpers, headers, etc.

    def build(self):
        # Cria widgets UMA VEZ. Sem fetch de dado aqui.
        self._label = tk.Label(self.container, text="...")
        self._label.pack()

    def on_enter(self, **kwargs):
        # Refresh de dados dinamicos.
        # Arma timers com self._after(ms, cb).
        # Registra bindings com self._bind(widget, seq, cb).
        self._after(500, self._refresh)
        self._bind(self._label, "<Button-1>", self._on_click)

    def on_exit(self):
        super().on_exit()  # cancela timers + bindings rastreados
        # Cleanup adicional se precisar.
```

**NUNCA** chame `.destroy()` dentro de `on_exit`. Todo o ponto é reuso.

## Timers & bindings

Helpers auto-cleanup:
- `self._after(ms, callback)` — arma `.after()`; auto-cancela em `on_exit`
- `self._bind(widget, seq, callback)` — bind; auto-unbind em `on_exit`

Direct `self.container.after()` ou `widget.bind()` é permitido mas **você** é responsável pelo cleanup.

## Wiring em launcher.py

No `Terminal.__init__` (já existe, adicionar entrada):

```python
self.screens.register(
    "my_screen",
    lambda parent: MyScreen(parent=parent, app=self),
)
```

No call site que mostra a tela:

```python
def _show_my_screen(self):
    self._clr()      # legacy cleanup (destruir widgets do self.main)
    self._clear_kb() # limpar keybindings globais
    # _clr ja desarmou current screen migrada e restaurou legacy mode.
    # Pra ir pra screens container, flip:
    if self.main.winfo_manager():
        self.main.pack_forget()
    if not self.screens_container.winfo_manager():
        self.screens_container.pack(fill="both", expand=True)
    self.screens.show("my_screen", run_id=run_id)  # kwargs -> on_enter
```

## Métricas

Cada `ScreenManager.show()` emite:
- **Counter**: `runtime_health.record("screen.<name>.first_visit" | "screen.<name>.reentry")`
- **Log**: logger `aurum.launcher.screens` INFO `"event=screen_switch name=<> phase=<> ms=<>"`

Legacy (não-migradas) screens podem ser instrumentadas com `@timed_legacy_switch("<name>")` de `_metrics.py` — emite `screen.<name>.legacy_rebuild` pra comparação.

## Quando migrar próxima tela

Após 1-2 dias de uso com a instrumentação, inspecionar:

```bash
python -c "
from core.ops.health import runtime_health
for k, v in sorted(runtime_health.snapshot().items()):
    if k.startswith('screen.'):
        print(f'{k}: {v}')
"
```

Ou greppar os logs por `event=screen_switch`. As screens top por `legacy_rebuild_ms` médio × frequência de acesso são candidatas naturais.

## O que NÃO migrar

- Screens com fetch de dado live em cada tick (migrar a container, manter o fetch path via `on_enter` refresh)
- Screens mostradas uma vez por sessão (não vale o esforço)
- Screens que dependem de estado global mutável entre visitas (primeiro refactor o estado)

## Rollback

Se uma screen migrada der ruim, reverter só o wrapper dela em `launcher.py` pro body pré-migration. O ScreenManager pode ficar registered — fica inerte se nada chamar `show()` pra esse nome.

## Convivência antigo + novo

```
launcher.py
├── self.main                  # container legacy — telas não-migradas vivem aqui
└── self.screens_container     # SIBLING de self.main — screens migradas aqui
```

`_clr` restaura LEGACY mode por default (self.main packed, screens_container forgot) + chama `on_exit` na current migrada. Wrapper da migrada flip: `self.main.pack_forget()` + `self.screens_container.pack(...)` antes do `screens.show(...)`.

## Exemplo de referência

Splash (piloto): `launcher_support/screens/splash.py`.
Tests de paridade: `tests/launcher/test_splash_screen.py`.
Integration (3-screen rotation): `tests/launcher/test_screen_integration.py`.

## Ordem de complexidade pra migrar as próximas

Baseado no grep de call sites de `destroy+rebuild`:

1. **Fácil (canvas simples, sem live data)**: splash ✅, `_funding_paint`
2. **Médio (lista, scroll, sem fetch)**: `_results_build_list_items`, `_results_render_tab`
3. **Médio-alto (charts matplotlib)**: `_results_render_chart`
4. **Alto (live data, timers, multi-panel)**: `_arb_show_detail`, `_eng_refresh`, cockpit
5. **Maior (menu bloomberg canvas 15+ methods acoplados)**: `_menu_main_bloomberg`

Sugestão: seguir ordem crescente de complexidade. Cada uma é seu próprio plan.
