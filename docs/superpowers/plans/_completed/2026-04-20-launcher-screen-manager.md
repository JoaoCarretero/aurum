# Launcher Screen Manager — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminar lag FPS-baixo na navegação do launcher construindo infra `Screen`+`ScreenManager` (cache de widgets, sem `destroy+rebuild`), instrumentando o caminho antigo, e migrando **1 screen piloto (`_splash` / "menu inicial")** como prova do padrão. Migrações subsequentes ficam pra planos futuros.

**Architecture:** Novo package `launcher_support/screens/` com `Screen` ABC + `ScreenManager`. ScreenManager isolado em subcontainer `self.screens_container` dentro de `self.main`. Telas não-migradas continuam no caminho antigo (convivência híbrida). Métricas via `runtime_health.record` (counters) + `logging.info` (timings ms).

**Tech Stack:** Python 3.14 (sem venv), stdlib `tkinter`, `tkinter.ttk`, `tkinter.font`, `logging`, `pytest`.

**Protected files — DO NOT modify:** `core/indicators.py`, `core/signals.py`, `core/portfolio.py`, `config/params.py`, `config/keys.json`.

**Nota sobre o piloto:** spec diz "menu inicial". Per memory do João (PT-BR), "menu inicial/introdutório" = `_splash` (landing antes do main menu Bloomberg), **não** `_menu_main_bloomberg`. Splash é mais simples (~120 linhas numa função, canvas-based, sem live-data fetch síncrono) — piloto natural. Menu Bloomberg fica pra plano subsequente.

**Spec:** `docs/superpowers/specs/2026-04-20-launcher-screen-manager-design.md`.

---

## File Structure

**Create (new):**
- `launcher_support/screens/__init__.py` — re-exports `Screen`, `ScreenManager`, exceptions
- `launcher_support/screens/base.py` — `Screen` ABC + helpers `_after`/`_bind` com auto-cleanup
- `launcher_support/screens/exceptions.py` — `ScreenError`, `ScreenBuildError`, `ScreenContextError`
- `launcher_support/screens/manager.py` — `ScreenManager` class
- `launcher_support/screens/_metrics.py` — `emit_switch_metric(name, phase, ms)` + `@timed_legacy_switch(name)` decorator
- `launcher_support/screens/splash.py` — `SplashScreen` piloto
- `tests/launcher/__init__.py`
- `tests/launcher/test_screen_exceptions.py`
- `tests/launcher/test_screen_base.py`
- `tests/launcher/test_screen_manager.py`
- `tests/launcher/test_screen_metrics.py`
- `tests/launcher/test_screen_integration.py` — Tk real, marker `@pytest.mark.gui`
- `tests/launcher/test_splash_screen.py` — regression do piloto
- `docs/architecture/screen_manager.md` — guide curto pra migrações futuras

**Modify:**
- `launcher.py`:
  - Terminal `__init__` (~L1327): adicionar `self.screens_container` + `self.screens = ScreenManager(...)`
  - Aplicar `@timed_legacy_switch("<name>")` em ~10 sites de `destroy+rebuild`
  - `_splash` (L2250): virar wrapper thin chamando `self.screens.show("splash")`
- `pyproject.toml`: adicionar marker `gui` em `[tool.pytest.ini_options]`

---

## Task 1: Prep — package skeletons + dirs

**Files:**
- Create: `launcher_support/screens/__init__.py`
- Create: `tests/launcher/__init__.py`
- Create: `docs/architecture/screen_manager.md` (stub)

- [ ] **Step 1: Create package dirs and stub files**

```bash
mkdir -p launcher_support/screens tests/launcher docs/architecture
```

- [ ] **Step 2: Write `launcher_support/screens/__init__.py`**

```python
"""Screen manager infrastructure for the launcher.

See docs/architecture/screen_manager.md for the migration pattern.
Specs: docs/superpowers/specs/2026-04-20-launcher-screen-manager-design.md
"""
from launcher_support.screens.exceptions import (
    ScreenError,
    ScreenBuildError,
    ScreenContextError,
)
from launcher_support.screens.base import Screen
from launcher_support.screens.manager import ScreenManager

__all__ = [
    "Screen",
    "ScreenManager",
    "ScreenError",
    "ScreenBuildError",
    "ScreenContextError",
]
```

**Note:** The `exceptions`, `base`, `manager` modules don't exist yet — imports will fail until Task 2+. That's fine; nothing imports `launcher_support.screens` until Task 10.

- [ ] **Step 3: Write `tests/launcher/__init__.py`** (empty marker file)

```python
```

(Zero bytes or just a blank line.)

- [ ] **Step 4: Write `docs/architecture/screen_manager.md` stub**

```markdown
# Screen Manager — Migration Guide

*Stub — content populated in Task 11.*
```

- [ ] **Step 5: Commit**

```bash
git add launcher_support/screens/__init__.py tests/launcher/__init__.py docs/architecture/screen_manager.md
git commit -m "chore(launcher): scaffold screens package + tests/launcher dir"
```

Expected: commit succeeds. Pre-commit hook validates keys.json.

---

## Task 2: Exception hierarchy

**Files:**
- Create: `launcher_support/screens/exceptions.py`
- Create: `tests/launcher/test_screen_exceptions.py`

- [ ] **Step 1: Write failing test**

File: `tests/launcher/test_screen_exceptions.py`

```python
"""Exception hierarchy for launcher_support.screens."""
from __future__ import annotations

import pytest

from launcher_support.screens.exceptions import (
    ScreenError,
    ScreenBuildError,
    ScreenContextError,
)


def test_screen_error_is_base():
    assert issubclass(ScreenBuildError, ScreenError)
    assert issubclass(ScreenContextError, ScreenError)


def test_screen_error_is_exception():
    assert issubclass(ScreenError, Exception)


def test_screen_build_error_carries_screen_name():
    err = ScreenBuildError("splash", original=ValueError("boom"))
    assert err.screen_name == "splash"
    assert isinstance(err.original, ValueError)
    assert "splash" in str(err)


def test_screen_context_error_carries_missing_keys():
    err = ScreenContextError("results", missing=["run_id", "mode"])
    assert err.screen_name == "results"
    assert err.missing == ["run_id", "mode"]
    assert "run_id" in str(err)
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/launcher/test_screen_exceptions.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'launcher_support.screens.exceptions'`.

- [ ] **Step 3: Implement `launcher_support/screens/exceptions.py`**

```python
"""Exception hierarchy for screen lifecycle errors."""
from __future__ import annotations


class ScreenError(Exception):
    """Base exception for screen-related failures."""


class ScreenBuildError(ScreenError):
    """Raised when Screen.build() fails during first mount."""

    def __init__(self, screen_name: str, *, original: BaseException | None = None):
        super().__init__(f"screen {screen_name!r} failed to build: {original!r}")
        self.screen_name = screen_name
        self.original = original


class ScreenContextError(ScreenError):
    """Raised when on_enter() is missing required kwargs."""

    def __init__(self, screen_name: str, *, missing: list[str]):
        super().__init__(
            f"screen {screen_name!r} missing required kwargs: {missing}"
        )
        self.screen_name = screen_name
        self.missing = missing
```

- [ ] **Step 4: Run tests to verify pass**

```bash
python -m pytest tests/launcher/test_screen_exceptions.py -v
```

Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add launcher_support/screens/exceptions.py tests/launcher/test_screen_exceptions.py
git commit -m "feat(launcher): ScreenError hierarchy (Build + Context)"
```

---

## Task 3: Screen ABC — lifecycle shell

**Files:**
- Create: `launcher_support/screens/base.py`
- Create: `tests/launcher/test_screen_base.py`

**Context:** Screen ABC defines the lifecycle: `build()`, `on_enter(**kwargs)`, `on_exit()`, `update_data(**kwargs)`, and `pack()/pack_forget()`. This task keeps the class minimal — helpers `_after`/`_bind` come in Task 4.

- [ ] **Step 1: Write failing test**

File: `tests/launcher/test_screen_base.py`

```python
"""Unit tests for Screen ABC lifecycle."""
from __future__ import annotations

import pytest
import tkinter as tk

from launcher_support.screens.base import Screen


class _FakeScreen(Screen):
    def __init__(self, parent):
        super().__init__(parent)
        self.build_count = 0
        self.enter_calls: list[dict] = []
        self.exit_count = 0

    def build(self) -> None:
        self.build_count += 1
        self._label = tk.Label(self.container, text="fake")
        self._label.pack()

    def on_enter(self, **kwargs) -> None:
        self.enter_calls.append(kwargs)

    def on_exit(self) -> None:
        self.exit_count += 1


@pytest.fixture(scope="module")
def tk_root():
    root = tk.Tk()
    root.withdraw()
    yield root
    try:
        root.destroy()
    except Exception:
        pass


def test_screen_creates_container_frame(tk_root):
    s = _FakeScreen(parent=tk_root)
    assert s.container is not None
    assert isinstance(s.container, tk.Frame)
    assert str(s.container.master) == str(tk_root)


def test_screen_build_is_invoked_once(tk_root):
    s = _FakeScreen(parent=tk_root)
    s.mount()
    assert s.build_count == 1
    # mount() a second time is a no-op (container already built)
    s.mount()
    assert s.build_count == 1


def test_screen_pack_and_unpack(tk_root):
    s = _FakeScreen(parent=tk_root)
    s.mount()
    s.pack()
    tk_root.update_idletasks()
    assert s.container.winfo_manager() == "pack"
    s.pack_forget()
    tk_root.update_idletasks()
    assert s.container.winfo_manager() == ""


def test_on_enter_receives_kwargs(tk_root):
    s = _FakeScreen(parent=tk_root)
    s.mount()
    s.on_enter(run_id="abc", mode="paper")
    assert s.enter_calls == [{"run_id": "abc", "mode": "paper"}]


def test_on_exit_invoked(tk_root):
    s = _FakeScreen(parent=tk_root)
    s.mount()
    s.on_enter()
    s.on_exit()
    assert s.exit_count == 1


def test_abstract_build_raises_if_not_overridden(tk_root):
    class _Incomplete(Screen):
        pass

    with pytest.raises(TypeError):
        _Incomplete(parent=tk_root)
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/launcher/test_screen_base.py -v
```

Expected: FAIL with `ModuleNotFoundError` or abstract-class related errors.

- [ ] **Step 3: Implement `launcher_support/screens/base.py`**

```python
"""Screen ABC — base class for migrated launcher screens.

A Screen owns a tk.Frame (self.container). build() creates widgets once;
on_enter(**kwargs) refreshes data; on_exit() releases timers/bindings.
pack()/pack_forget() control visibility without destroying widgets.

Lifecycle helpers (_after, _bind) are added in Task 4.
"""
from __future__ import annotations

import tkinter as tk
from abc import ABC, abstractmethod
from typing import Any


class Screen(ABC):
    def __init__(self, parent: tk.Misc):
        self._parent = parent
        self.container: tk.Frame = tk.Frame(parent)
        self._built = False

    @abstractmethod
    def build(self) -> None:
        """Create widgets once inside self.container. No data fetch here."""
        raise NotImplementedError

    def on_enter(self, **kwargs: Any) -> None:
        """Called each time the screen is shown. Refresh dynamic data here."""

    def on_exit(self) -> None:
        """Called each time the screen is hidden. Cancel timers/bindings here."""

    def update_data(self, **kwargs: Any) -> None:
        """Helper for refreshing widget .configure() without rebuilding."""

    def mount(self) -> None:
        """Ensure build() has been called exactly once."""
        if not self._built:
            self.build()
            self._built = True

    def pack(self, **opts: Any) -> None:
        opts.setdefault("fill", "both")
        opts.setdefault("expand", True)
        self.container.pack(**opts)

    def pack_forget(self) -> None:
        self.container.pack_forget()
```

- [ ] **Step 4: Run tests to verify pass**

```bash
python -m pytest tests/launcher/test_screen_base.py -v
```

Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add launcher_support/screens/base.py tests/launcher/test_screen_base.py
git commit -m "feat(launcher): Screen ABC with mount/pack/pack_forget lifecycle"
```

---

## Task 4: Screen lifecycle helpers — `_after` and `_bind` with auto-cleanup

**Files:**
- Modify: `launcher_support/screens/base.py`
- Create: additional tests in `tests/launcher/test_screen_base.py`

**Context:** Screens must not leak `.after()` timers or widget bindings when hidden. Base class provides tracked helpers; `on_exit()` cancels them automatically.

- [ ] **Step 1: Append failing tests**

Append to `tests/launcher/test_screen_base.py`:

```python

class _TimerScreen(Screen):
    def __init__(self, parent):
        super().__init__(parent)
        self.tick_count = 0
        self.click_count = 0

    def build(self) -> None:
        self._btn = tk.Button(self.container, text="go")
        self._btn.pack()

    def on_enter(self, **kwargs) -> None:
        self._after(10, self._tick)
        self._bind(self._btn, "<Button-1>", self._click)

    def _tick(self) -> None:
        self.tick_count += 1

    def _click(self, _event) -> None:
        self.click_count += 1


def test_after_timer_cancelled_on_exit(tk_root):
    s = _TimerScreen(parent=tk_root)
    s.mount()
    s.on_enter()
    # Before on_exit, the timer is armed
    assert len(s._tracked_after_ids) == 1
    s.on_exit()
    # After on_exit, timer list cleared
    assert s._tracked_after_ids == []
    # Sleep past the scheduled firing — tick must NOT have fired
    tk_root.after(30, lambda: None)
    tk_root.update()
    tk_root.after(30, lambda: None)
    tk_root.update()
    assert s.tick_count == 0


def test_binding_cleared_on_exit(tk_root):
    s = _TimerScreen(parent=tk_root)
    s.mount()
    s.on_enter()
    # Before on_exit, binding tracked
    assert len(s._tracked_bindings) == 1
    s.on_exit()
    assert s._tracked_bindings == []


def test_auto_cleanup_is_idempotent(tk_root):
    s = _TimerScreen(parent=tk_root)
    s.mount()
    s.on_enter()
    s.on_exit()
    s.on_exit()  # second call is safe no-op
    assert s.tick_count == 0
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/launcher/test_screen_base.py::test_after_timer_cancelled_on_exit -v
```

Expected: FAIL with `AttributeError: 'Screen' object has no attribute '_after'` or similar.

- [ ] **Step 3: Extend `launcher_support/screens/base.py`**

Replace the `Screen` class with this extended version:

```python
"""Screen ABC — base class for migrated launcher screens.

A Screen owns a tk.Frame (self.container). build() creates widgets once;
on_enter(**kwargs) refreshes data; on_exit() releases timers/bindings.
pack()/pack_forget() control visibility without destroying widgets.

Helpers _after/_bind register callbacks with automatic cleanup in on_exit.
"""
from __future__ import annotations

import tkinter as tk
from abc import ABC, abstractmethod
from typing import Any, Callable


class Screen(ABC):
    def __init__(self, parent: tk.Misc):
        self._parent = parent
        self.container: tk.Frame = tk.Frame(parent)
        self._built = False
        self._tracked_after_ids: list[str] = []
        self._tracked_bindings: list[tuple[tk.Misc, str, str]] = []

    @abstractmethod
    def build(self) -> None:
        """Create widgets once inside self.container."""
        raise NotImplementedError

    def on_enter(self, **kwargs: Any) -> None:
        """Refresh dynamic data / arm timers / register bindings."""

    def on_exit(self) -> None:
        """Cancel tracked timers and unbind tracked sequences."""
        for aid in list(self._tracked_after_ids):
            try:
                self.container.after_cancel(aid)
            except Exception:
                pass
        self._tracked_after_ids.clear()
        for widget, seq, funcid in list(self._tracked_bindings):
            try:
                widget.unbind(seq, funcid)
            except Exception:
                pass
        self._tracked_bindings.clear()

    def update_data(self, **kwargs: Any) -> None:
        """Configure() existing widgets without rebuilding."""

    def mount(self) -> None:
        if not self._built:
            self.build()
            self._built = True

    def pack(self, **opts: Any) -> None:
        opts.setdefault("fill", "both")
        opts.setdefault("expand", True)
        self.container.pack(**opts)

    def pack_forget(self) -> None:
        self.container.pack_forget()

    # ── lifecycle helpers ─────────────────────────────────────────

    def _after(self, ms: int, callback: Callable[[], Any]) -> str:
        """Schedule a callback and track the id for cleanup in on_exit."""
        aid = self.container.after(ms, callback)
        self._tracked_after_ids.append(aid)
        return aid

    def _bind(
        self,
        widget: tk.Misc,
        sequence: str,
        callback: Callable[[tk.Event], Any],
    ) -> str:
        """Bind a callback and track for cleanup in on_exit."""
        funcid = widget.bind(sequence, callback, add="+")
        self._tracked_bindings.append((widget, sequence, funcid))
        return funcid
```

- [ ] **Step 4: Run full test file to verify pass**

```bash
python -m pytest tests/launcher/test_screen_base.py -v
```

Expected: 9 tests pass (6 from Task 3 + 3 new).

- [ ] **Step 5: Commit**

```bash
git add launcher_support/screens/base.py tests/launcher/test_screen_base.py
git commit -m "feat(launcher): Screen._after and Screen._bind with auto-cleanup on_exit"
```

---

## Task 5: ScreenManager — cache miss path (first visit)

**Files:**
- Create: `launcher_support/screens/manager.py`
- Create: `tests/launcher/test_screen_manager.py`

**Context:** First screen visit flow: instantiate → build → on_enter → pack. Track as `_current`. Register the screen via `ScreenManager.register(name, factory)`.

- [ ] **Step 1: Write failing test**

File: `tests/launcher/test_screen_manager.py`

```python
"""Unit tests for ScreenManager — cache miss path first."""
from __future__ import annotations

import pytest
import tkinter as tk

from launcher_support.screens.base import Screen
from launcher_support.screens.manager import ScreenManager


class _Recording(Screen):
    def __init__(self, parent):
        super().__init__(parent)
        self.events: list[tuple[str, dict]] = []

    def build(self) -> None:
        self.events.append(("build", {}))

    def on_enter(self, **kwargs) -> None:
        self.events.append(("enter", dict(kwargs)))

    def on_exit(self) -> None:
        super().on_exit()
        self.events.append(("exit", {}))


@pytest.fixture
def tk_root():
    root = tk.Tk()
    root.withdraw()
    yield root
    try:
        root.destroy()
    except Exception:
        pass


def test_register_screen_factory(tk_root):
    mgr = ScreenManager(parent=tk_root)
    mgr.register("foo", _Recording)
    assert "foo" in mgr.registered_names()


def test_first_show_instantiates_builds_enters_and_packs(tk_root):
    mgr = ScreenManager(parent=tk_root)
    mgr.register("foo", _Recording)

    screen = mgr.show("foo", x=1)

    assert isinstance(screen, _Recording)
    assert [e[0] for e in screen.events] == ["build", "enter"]
    assert screen.events[1][1] == {"x": 1}
    tk_root.update_idletasks()
    assert screen.container.winfo_manager() == "pack"
    assert mgr.current_name() == "foo"


def test_unknown_screen_raises(tk_root):
    mgr = ScreenManager(parent=tk_root)
    with pytest.raises(ValueError, match="unknown screen"):
        mgr.show("nonexistent")
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/launcher/test_screen_manager.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'launcher_support.screens.manager'`.

- [ ] **Step 3: Implement `launcher_support/screens/manager.py`**

```python
"""ScreenManager — central orchestrator for migrated launcher screens.

Usage:
    mgr = ScreenManager(parent=root_frame)
    mgr.register("splash", SplashScreen)
    mgr.show("splash")            # first visit: instantiate + build + enter
    mgr.show("cockpit")           # hide splash, show cockpit
    mgr.show("splash")            # cache hit: just on_enter + pack

Screens live in a single shared parent (usually `root.screens_container`).
Only one screen is visible at a time; others are pack_forget-ed but kept
in memory for instant re-entry.
"""
from __future__ import annotations

import tkinter as tk
from typing import Any, Callable, Type

from launcher_support.screens.base import Screen

ScreenFactory = Callable[[tk.Misc], Screen]


class ScreenManager:
    def __init__(self, parent: tk.Misc):
        self._parent = parent
        self._factories: dict[str, ScreenFactory] = {}
        self._cache: dict[str, Screen] = {}
        self._current_name: str | None = None

    def register(self, name: str, factory: ScreenFactory) -> None:
        """Register a Screen class or factory callable."""
        self._factories[name] = factory

    def registered_names(self) -> list[str]:
        return list(self._factories.keys())

    def current_name(self) -> str | None:
        return self._current_name

    def show(self, name: str, **kwargs: Any) -> Screen:
        """Show the named screen, creating it on first access."""
        if name not in self._factories:
            raise ValueError(f"unknown screen: {name!r}")
        screen = self._cache.get(name)
        if screen is None:
            screen = self._factories[name](self._parent)
            self._cache[name] = screen
        screen.mount()
        screen.on_enter(**kwargs)
        screen.pack()
        self._current_name = name
        return screen
```

- [ ] **Step 4: Run tests to verify pass**

```bash
python -m pytest tests/launcher/test_screen_manager.py -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add launcher_support/screens/manager.py tests/launcher/test_screen_manager.py
git commit -m "feat(launcher): ScreenManager with cache-miss path (first visit)"
```

---

## Task 6: ScreenManager — cache hit path (exit previous, enter next)

**Files:**
- Modify: `launcher_support/screens/manager.py`
- Modify: `tests/launcher/test_screen_manager.py` (append tests)

- [ ] **Step 1: Append failing tests**

Append to `tests/launcher/test_screen_manager.py`:

```python

def test_second_show_same_name_reuses_cached_instance(tk_root):
    mgr = ScreenManager(parent=tk_root)
    mgr.register("foo", _Recording)
    a = mgr.show("foo")
    b = mgr.show("foo", y=2)
    assert a is b
    # build called once; enter called twice (one per show)
    assert [e[0] for e in a.events] == ["build", "enter", "exit", "enter"]
    assert a.events[-1][1] == {"y": 2}


def test_switch_exits_previous_before_enter_next(tk_root):
    mgr = ScreenManager(parent=tk_root)
    mgr.register("foo", _Recording)
    mgr.register("bar", _Recording)

    foo = mgr.show("foo")
    bar = mgr.show("bar", mode="live")

    foo_events = [e[0] for e in foo.events]
    bar_events = [e[0] for e in bar.events]
    assert foo_events == ["build", "enter", "exit"]
    assert bar_events == ["build", "enter"]
    assert mgr.current_name() == "bar"


def test_current_screen_pack_forget_on_switch(tk_root):
    mgr = ScreenManager(parent=tk_root)
    mgr.register("foo", _Recording)
    mgr.register("bar", _Recording)

    foo = mgr.show("foo")
    tk_root.update_idletasks()
    assert foo.container.winfo_manager() == "pack"

    bar = mgr.show("bar")
    tk_root.update_idletasks()
    assert foo.container.winfo_manager() == ""
    assert bar.container.winfo_manager() == "pack"
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/launcher/test_screen_manager.py -v
```

Expected: at least `test_second_show_same_name_reuses_cached_instance` fails — the current `show()` doesn't invoke on_exit on the previous screen.

- [ ] **Step 3: Update `show()` in `launcher_support/screens/manager.py`**

Replace the `show` method with:

```python
    def show(self, name: str, **kwargs: Any) -> Screen:
        """Show the named screen, creating it on first access."""
        if name not in self._factories:
            raise ValueError(f"unknown screen: {name!r}")

        # Hide current screen first (if any)
        if self._current_name is not None:
            prev = self._cache.get(self._current_name)
            if prev is not None:
                try:
                    prev.on_exit()
                except Exception:
                    pass
                prev.pack_forget()

        screen = self._cache.get(name)
        if screen is None:
            screen = self._factories[name](self._parent)
            self._cache[name] = screen
        screen.mount()
        screen.on_enter(**kwargs)
        screen.pack()
        self._current_name = name
        return screen
```

- [ ] **Step 4: Run tests to verify pass**

```bash
python -m pytest tests/launcher/test_screen_manager.py -v
```

Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add launcher_support/screens/manager.py tests/launcher/test_screen_manager.py
git commit -m "feat(launcher): ScreenManager cache-hit path — exit prev, enter next"
```

---

## Task 7: ScreenManager — error paths

**Files:**
- Modify: `launcher_support/screens/manager.py`
- Modify: `tests/launcher/test_screen_manager.py`

**Context:** Three error cases:
1. Factory raises → wrap in `ScreenBuildError`, keep current screen
2. `on_enter()` raises `ScreenContextError` (bubble up after reverting), or any other exception → keep current screen, log
3. Already tested: unknown screen raises `ValueError`

- [ ] **Step 1: Append failing tests**

Append to `tests/launcher/test_screen_manager.py`:

```python
from launcher_support.screens.exceptions import (
    ScreenBuildError,
    ScreenContextError,
)


class _BuildFails(Screen):
    def build(self) -> None:
        raise RuntimeError("nope")

    def on_enter(self, **kwargs) -> None:
        pass


class _EnterFails(Screen):
    def build(self) -> None:
        pass

    def on_enter(self, **kwargs) -> None:
        if "run_id" not in kwargs:
            raise ScreenContextError("pic", missing=["run_id"])


def test_build_failure_raises_screen_build_error(tk_root):
    mgr = ScreenManager(parent=tk_root)
    mgr.register("bad", _BuildFails)
    with pytest.raises(ScreenBuildError) as excinfo:
        mgr.show("bad")
    assert excinfo.value.screen_name == "bad"
    assert isinstance(excinfo.value.original, RuntimeError)


def test_build_failure_keeps_previous_current(tk_root):
    mgr = ScreenManager(parent=tk_root)
    mgr.register("foo", _Recording)
    mgr.register("bad", _BuildFails)
    mgr.show("foo")
    with pytest.raises(ScreenBuildError):
        mgr.show("bad")
    # Previous screen is still logically current
    assert mgr.current_name() == "foo"


def test_on_enter_context_error_propagates_and_keeps_current(tk_root):
    mgr = ScreenManager(parent=tk_root)
    mgr.register("foo", _Recording)
    mgr.register("pic", _EnterFails)
    mgr.show("foo")
    with pytest.raises(ScreenContextError):
        mgr.show("pic")  # missing run_id
    assert mgr.current_name() == "foo"


def test_on_enter_arbitrary_error_propagates_and_keeps_current(tk_root):
    class _Boom(Screen):
        def build(self):
            pass

        def on_enter(self, **kwargs):
            raise RuntimeError("boom")

    mgr = ScreenManager(parent=tk_root)
    mgr.register("foo", _Recording)
    mgr.register("boom", _Boom)
    mgr.show("foo")
    with pytest.raises(RuntimeError):
        mgr.show("boom")
    assert mgr.current_name() == "foo"
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/launcher/test_screen_manager.py -v
```

Expected: at least 3 new tests fail (`ScreenBuildError` not raised, etc.).

- [ ] **Step 3: Update `show()` in `manager.py`** to wrap errors + restore previous on failure

Replace the class body (keep init + register + registered_names + current_name; replace `show`):

```python
    def show(self, name: str, **kwargs: Any) -> Screen:
        """Show the named screen, creating it on first access.

        On build/on_enter failure, keeps the previously-current screen
        logically current (it was already pack_forget-ed, so caller must
        re-pack or show another screen to recover UX).
        """
        if name not in self._factories:
            raise ValueError(f"unknown screen: {name!r}")

        prev_name = self._current_name
        prev_screen = self._cache.get(prev_name) if prev_name else None
        if prev_screen is not None:
            try:
                prev_screen.on_exit()
            except Exception:
                pass
            prev_screen.pack_forget()

        screen = self._cache.get(name)
        is_first_visit = screen is None
        if is_first_visit:
            try:
                screen = self._factories[name](self._parent)
                screen.mount()
            except Exception as exc:
                self._current_name = prev_name
                raise ScreenBuildError(name, original=exc) from exc
            self._cache[name] = screen
        else:
            screen.mount()

        try:
            screen.on_enter(**kwargs)
        except Exception:
            self._current_name = prev_name
            raise
        screen.pack()
        self._current_name = name
        return screen
```

Also add the import at the top of the file:

```python
from launcher_support.screens.exceptions import ScreenBuildError
```

- [ ] **Step 4: Run tests to verify pass**

```bash
python -m pytest tests/launcher/test_screen_manager.py -v
```

Expected: 10 tests pass.

- [ ] **Step 5: Commit**

```bash
git add launcher_support/screens/manager.py tests/launcher/test_screen_manager.py
git commit -m "feat(launcher): ScreenManager error paths — ScreenBuildError + keep-current semantics"
```

---

## Task 8: Metrics — `emit_switch_metric` + timing in `show()`

**Files:**
- Create: `launcher_support/screens/_metrics.py`
- Create: `tests/launcher/test_screen_metrics.py`
- Modify: `launcher_support/screens/manager.py`

**Context:** Every `show()` logs `ms` (wall-time) at phase `first_visit` or `reentry`. Counter via `runtime_health.record("screen.<name>.<phase>")`. Timing via `logging.info` on logger `aurum.launcher.screens`.

- [ ] **Step 1: Write failing test**

File: `tests/launcher/test_screen_metrics.py`

```python
"""Tests for screen metrics emission (logs + counters)."""
from __future__ import annotations

import logging

import pytest

from core.ops.health import runtime_health
from launcher_support.screens._metrics import emit_switch_metric


@pytest.fixture(autouse=True)
def _reset_counters():
    runtime_health.counters.clear()
    yield
    runtime_health.counters.clear()


def test_emit_records_counter_first_visit():
    emit_switch_metric("splash", "first_visit", ms=42.0)
    assert runtime_health.snapshot().get("screen.splash.first_visit") == 1


def test_emit_records_counter_reentry():
    emit_switch_metric("splash", "reentry", ms=5.0)
    emit_switch_metric("splash", "reentry", ms=6.0)
    assert runtime_health.snapshot().get("screen.splash.reentry") == 2


def test_emit_logs_ms(caplog):
    caplog.set_level(logging.INFO, logger="aurum.launcher.screens")
    emit_switch_metric("menu", "first_visit", ms=123.4)
    records = [r for r in caplog.records if r.name == "aurum.launcher.screens"]
    assert len(records) == 1
    assert "menu" in records[0].getMessage()
    assert "first_visit" in records[0].getMessage()
    assert "123.4" in records[0].getMessage()


def test_emit_validates_phase():
    with pytest.raises(ValueError, match="phase"):
        emit_switch_metric("x", "bogus", ms=1.0)
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/launcher/test_screen_metrics.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'launcher_support.screens._metrics'`.

- [ ] **Step 3: Implement `launcher_support/screens/_metrics.py`**

```python
"""Metrics emission for screen switches.

emit_switch_metric(name, phase, ms) — logs timing + increments counter.
@timed_legacy_switch(name) — decorator for instrumenting legacy
destroy+rebuild call sites in launcher.py (used in Task 9).
"""
from __future__ import annotations

import functools
import logging
import time
from typing import Any, Callable

from core.ops.health import runtime_health

_log = logging.getLogger("aurum.launcher.screens")

_ALLOWED_PHASES = {"first_visit", "reentry", "legacy_rebuild"}


def emit_switch_metric(name: str, phase: str, *, ms: float) -> None:
    """Record a screen switch metric.

    - Increments counter ``screen.<name>.<phase>`` in runtime_health.
    - Emits INFO log via logger ``aurum.launcher.screens``.
    """
    if phase not in _ALLOWED_PHASES:
        raise ValueError(
            f"phase must be one of {sorted(_ALLOWED_PHASES)}, got {phase!r}"
        )
    runtime_health.record(f"screen.{name}.{phase}")
    _log.info(
        "event=screen_switch name=%s phase=%s ms=%.1f",
        name, phase, ms,
    )


def timed_legacy_switch(name: str) -> Callable:
    """Decorator for legacy destroy+rebuild sites in launcher.py.

    Usage:
        @timed_legacy_switch("results")
        def _render_results(self): ...

    Measures wall-time and emits as phase="legacy_rebuild". Exceptions in
    the wrapped function re-raise after the metric is recorded (so we see
    timing even for failed renders).
    """
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            t0 = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                ms = (time.perf_counter() - t0) * 1000.0
                emit_switch_metric(name, "legacy_rebuild", ms=ms)
        return wrapper
    return decorator
```

- [ ] **Step 4: Run metric tests to verify pass**

```bash
python -m pytest tests/launcher/test_screen_metrics.py -v
```

Expected: 4 tests pass.

- [ ] **Step 5: Wire metrics into `ScreenManager.show()`**

Edit `launcher_support/screens/manager.py`. Add import:

```python
import time
from launcher_support.screens._metrics import emit_switch_metric
```

Replace `show()` with instrumented version:

```python
    def show(self, name: str, **kwargs: Any) -> Screen:
        if name not in self._factories:
            raise ValueError(f"unknown screen: {name!r}")

        t0 = time.perf_counter()
        prev_name = self._current_name
        prev_screen = self._cache.get(prev_name) if prev_name else None
        if prev_screen is not None:
            try:
                prev_screen.on_exit()
            except Exception:
                pass
            prev_screen.pack_forget()

        screen = self._cache.get(name)
        is_first_visit = screen is None
        if is_first_visit:
            try:
                screen = self._factories[name](self._parent)
                screen.mount()
            except Exception as exc:
                self._current_name = prev_name
                raise ScreenBuildError(name, original=exc) from exc
            self._cache[name] = screen
        else:
            screen.mount()

        try:
            screen.on_enter(**kwargs)
        except Exception:
            self._current_name = prev_name
            raise
        screen.pack()
        self._current_name = name

        ms = (time.perf_counter() - t0) * 1000.0
        phase = "first_visit" if is_first_visit else "reentry"
        emit_switch_metric(name, phase, ms=ms)
        return screen
```

- [ ] **Step 6: Add a test in `test_screen_manager.py` for the metric wiring**

Append:

```python
def test_show_emits_first_visit_then_reentry_metric(tk_root):
    runtime_health.counters.clear()
    mgr = ScreenManager(parent=tk_root)
    mgr.register("foo", _Recording)
    mgr.show("foo")
    mgr.show("foo")
    snap = runtime_health.snapshot()
    assert snap.get("screen.foo.first_visit") == 1
    assert snap.get("screen.foo.reentry") == 1
```

Add imports at the top of the file:

```python
from core.ops.health import runtime_health
```

- [ ] **Step 7: Run full tests/launcher/ to verify pass**

```bash
python -m pytest tests/launcher/ -v
```

Expected: all tests pass (11 unit tests after this task + 4 metrics + earlier ones).

- [ ] **Step 8: Commit**

```bash
git add launcher_support/screens/_metrics.py launcher_support/screens/manager.py tests/launcher/test_screen_metrics.py tests/launcher/test_screen_manager.py
git commit -m "feat(launcher): ScreenManager timing metrics (first_visit / reentry)"
```

---

## Task 9: Instrument legacy rebuild sites with `@timed_legacy_switch`

**Files:**
- Modify: `launcher.py` (10 call sites)

**Context:** Add `@timed_legacy_switch("<name>")` to ~10 methods that do `for w in X.winfo_children(): w.destroy()` + rebuild. Names are stable strings used in metric keys.

**Target sites** (from grep in spec Evidence section — confirm with `grep -n "winfo_children" launcher.py` before editing):

| Line  | Method                              | Metric name              |
|-------|-------------------------------------|--------------------------|
| ~1383 | main body clear (inside `_clr`)    | — (not a method, skip)   |
| ~3977 | `_results_render_tab` body         | `results_tab`            |
| ~4350 | `_results_render_list_inner`       | `results_list`           |
| ~4486 | `_results_render_chart`            | `results_chart`          |
| ~4613 | `_results_render_data_panel`       | `results_data_panel`     |
| ~6058 | (grep to identify enclosing def)   | `body_6058`              |
| ~6753 | (grep to identify)                 | `inner_6753`             |
| ~6836 | (grep to identify)                 | `inner_6836`             |
| ~7174 | (grep to identify)                 | `inner_7174`             |

The `_clr` path at L1383 is the global teardown, not a single screen — do NOT decorate; instead, `emit_switch_metric` inside each caller of `_clr` is handled by the callers (they each do their own rebuild).

- [ ] **Step 1: Identify the enclosing method for each line**

```bash
for L in 3977 4350 4486 4613 6058 6753 6836 7174; do
  echo "=== line $L ==="
  awk "NR>=$L-40 && NR<=$L { if (/def /) def=\$0 } END { print def }" launcher.py
done
```

Expected: prints the `def ...` preceding each line. Record the method name for each.

- [ ] **Step 2: Add import of `timed_legacy_switch` at top of `launcher.py`**

Find an appropriate import block (near other `launcher_support.*` imports, around L24-L48) and add:

```python
from launcher_support.screens._metrics import timed_legacy_switch
```

- [ ] **Step 3: Decorate each identified method**

For each `def _foo(self, ...)` identified in Step 1, add `@timed_legacy_switch("<name>")` immediately above. Example for `_results_render_tab`:

```python
    @timed_legacy_switch("results_tab")
    def _results_render_tab(self, tab):
        for w in self._results_body.winfo_children():
            try: w.destroy()
            except: pass
        # ... existing body unchanged ...
```

Repeat for all 8 methods. **Do not** change any logic inside the methods — only add the decorator.

- [ ] **Step 4: Run smoke test to verify no regression**

```bash
python smoke_test.py --quiet
```

Expected: 178/178 pass.

- [ ] **Step 5: Run full pytest suite**

```bash
python -m pytest tests/ -q 2>&1 | tail -10
```

Expected: same pass count as before this task (decorators don't change behavior). If a launcher contract test fails, inspect — a decorator missing the original return value is possible (the implementation in Task 8 uses `try/return/finally` which preserves return).

- [ ] **Step 6: Commit**

```bash
git add launcher.py
git commit -m "feat(launcher): instrument legacy destroy+rebuild sites with @timed_legacy_switch"
```

---

## Task 10: Integration test — Tk real with 3 screens

**Files:**
- Create: `tests/launcher/test_screen_integration.py`
- Modify: `pyproject.toml` (register `gui` marker)

**Context:** End-to-end test with real Tk that validates: switching between 3 screens works, cache reuse happens, timers/bindings don't leak, metrics are recorded. Marker `@pytest.mark.gui` lets CI skip in headless envs.

- [ ] **Step 1: Register `gui` marker in `pyproject.toml`**

Find `[tool.pytest.ini_options]` (around line 46) and add a `markers` key if absent, or extend:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-p no:cacheprovider"
markers = [
    "gui: requires a Tk-capable display (opt-in via -m gui or run all)",
]
norecursedirs = [
    # ... existing entries unchanged ...
]
```

- [ ] **Step 2: Write integration test**

File: `tests/launcher/test_screen_integration.py`

```python
"""Integration: Tk-real switching between 3 fake screens.

Marker `@pytest.mark.gui` — runs by default in local/normal CI.
Skip with `-m "not gui"` in a truly headless env that lacks tk.
"""
from __future__ import annotations

import tkinter as tk

import pytest

from core.ops.health import runtime_health
from launcher_support.screens.base import Screen
from launcher_support.screens.manager import ScreenManager


class _Counter(Screen):
    def __init__(self, parent):
        super().__init__(parent)
        self.enter_count = 0
        self.exit_count = 0
        self.tick_count = 0

    def build(self):
        self._lbl = tk.Label(self.container, text=f"counter {id(self) % 1000}")
        self._lbl.pack()

    def on_enter(self, **kwargs):
        self.enter_count += 1
        self._after(10, self._tick)

    def on_exit(self):
        super().on_exit()
        self.exit_count += 1

    def _tick(self):
        self.tick_count += 1


@pytest.fixture
def gui_root():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("tk unavailable")
    root.withdraw()
    yield root
    try:
        root.destroy()
    except Exception:
        pass


@pytest.mark.gui
def test_3_screen_rotation_caches_and_cleans_up(gui_root):
    runtime_health.counters.clear()
    container = tk.Frame(gui_root)
    container.pack()
    mgr = ScreenManager(parent=container)
    mgr.register("a", _Counter)
    mgr.register("b", _Counter)
    mgr.register("c", _Counter)

    a = mgr.show("a")
    b = mgr.show("b")
    c = mgr.show("c")
    a_again = mgr.show("a")

    # Cache reused
    assert a is a_again
    # Counts: a entered 2x, exited 1x; b entered 1x, exited 1x; c entered 1x, exited 1x
    assert a.enter_count == 2
    assert a.exit_count == 1
    assert b.enter_count == 1
    assert b.exit_count == 1
    assert c.enter_count == 1
    assert c.exit_count == 1

    # Metrics
    snap = runtime_health.snapshot()
    assert snap.get("screen.a.first_visit") == 1
    assert snap.get("screen.a.reentry") == 1
    assert snap.get("screen.b.first_visit") == 1
    assert snap.get("screen.c.first_visit") == 1


@pytest.mark.gui
def test_after_timer_does_not_fire_on_hidden_screen(gui_root):
    container = tk.Frame(gui_root)
    container.pack()
    mgr = ScreenManager(parent=container)
    mgr.register("a", _Counter)
    mgr.register("b", _Counter)

    a = mgr.show("a")
    # Timer was armed; switch before it fires
    mgr.show("b")
    # Pump events a few times well past the 10ms threshold
    for _ in range(10):
        gui_root.after(5, lambda: None)
        gui_root.update()
    assert a.tick_count == 0, "a's _after timer leaked past on_exit"
```

- [ ] **Step 3: Run integration tests to verify pass**

```bash
python -m pytest tests/launcher/test_screen_integration.py -v
```

Expected: 2 tests pass (or skip if tk unavailable).

- [ ] **Step 4: Commit**

```bash
git add tests/launcher/test_screen_integration.py pyproject.toml
git commit -m "test(launcher): Tk-real integration — 3-screen rotation + timer cleanup"
```

---

## Task 11: SplashScreen — migração piloto

**Files:**
- Create: `launcher_support/screens/splash.py`
- Create: `tests/launcher/test_splash_screen.py`
- Modify: `launcher.py` (Terminal `__init__` + `_splash` wrapper)

**Context:** Port of `launcher.py:_splash` (L2250-L2365). The screen class receives the Terminal app instance to reuse existing drawing helpers (`_draw_panel`, `_draw_kv_rows`, `_draw_aurum_logo`, `_apply_canvas_scale`) and global state (header labels `h_path`, `h_stat`, `f_lbl`, nav handlers `_splash_on_click`, `_bind_global_nav`, config loader `_load_json`).

**Key simplifications during migration:**
- `_clr()` + `_clear_kb()` are called by the ScreenManager's previous-screen `on_exit` or by the caller before `show()`. The splash itself doesn't call them inside `build`.
- The `.after(500, self._splash_pulse_tick)` timer uses `self._after(...)` helper (auto-cleanup).
- Click/keyboard bindings tracked via `self._bind(...)`.

- [ ] **Step 1: Write regression test**

File: `tests/launcher/test_splash_screen.py`

```python
"""Regression tests for SplashScreen (pilot migration).

These tests check structural parity with the old _splash() function:
- canvas is created with same design W/H
- session overview panel has 4 kv rows on each column
- prompt text "[ ENTER TO ACCESS DESK ]_" is present
- logo is drawn
"""
from __future__ import annotations

import tkinter as tk
from unittest.mock import MagicMock

import pytest

from launcher_support.screens.splash import SplashScreen


@pytest.fixture
def gui_root():
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("tk unavailable")
    root.withdraw()
    yield root
    try:
        root.destroy()
    except Exception:
        pass


@pytest.fixture
def fake_app(gui_root):
    """Stub of the launcher Terminal app exposing the methods SplashScreen uses."""
    app = MagicMock()
    app._SPLASH_DESIGN_W = 920
    app._SPLASH_DESIGN_H = 640
    app.h_stat = tk.Label(gui_root)
    app.h_path = tk.Label(gui_root)
    app.f_lbl = tk.Label(gui_root)
    app._draw_aurum_logo = MagicMock()
    app._draw_panel = MagicMock()
    app._draw_kv_rows = MagicMock()
    app._apply_canvas_scale = MagicMock(return_value=((0, 0, 920, 640), 1.0))
    app._load_json = MagicMock(return_value={
        "telegram": {"bot_token": "x"},
        "demo": {"api_key": "y"},
    })
    app._splash_on_click = MagicMock()
    app._bind_global_nav = MagicMock()
    return app


@pytest.fixture
def fake_conn():
    """Stub of the connection manager — just enough for SplashScreen."""
    conn = MagicMock()
    conn.status_summary.return_value = {"market": "demo"}
    return conn


@pytest.mark.gui
def test_splash_builds_canvas(gui_root, fake_app, fake_conn):
    s = SplashScreen(parent=gui_root, app=fake_app, conn=fake_conn, tagline="TEST TAGLINE")
    s.mount()
    assert s.canvas is not None
    assert s.canvas.winfo_reqwidth() > 0


@pytest.mark.gui
def test_splash_draws_logo_panel_rows(gui_root, fake_app, fake_conn):
    s = SplashScreen(parent=gui_root, app=fake_app, conn=fake_conn, tagline="TEST TAGLINE")
    s.mount()
    s.on_enter()
    # Session overview panel = 1 draw
    assert fake_app._draw_panel.call_count >= 1
    # Two kv rows (left + right columns)
    assert fake_app._draw_kv_rows.call_count >= 2
    # Logo drawn
    assert fake_app._draw_aurum_logo.call_count >= 1


@pytest.mark.gui
def test_splash_pulse_timer_cancelled_on_exit(gui_root, fake_app, fake_conn):
    s = SplashScreen(parent=gui_root, app=fake_app, conn=fake_conn, tagline="TEST TAGLINE")
    s.mount()
    s.on_enter()
    assert len(s._tracked_after_ids) >= 1
    s.on_exit()
    assert s._tracked_after_ids == []


@pytest.mark.gui
def test_splash_header_labels_set_on_enter(gui_root, fake_app, fake_conn):
    s = SplashScreen(parent=gui_root, app=fake_app, conn=fake_conn, tagline="TEST TAGLINE")
    s.mount()
    s.on_enter()
    assert fake_app.h_stat.cget("text") == "READY"
    assert "ENTER proceed" in fake_app.f_lbl.cget("text")
```

- [ ] **Step 2: Run to verify failure**

```bash
python -m pytest tests/launcher/test_splash_screen.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'launcher_support.screens.splash'`.

- [ ] **Step 3: Implement `launcher_support/screens/splash.py`**

```python
"""SplashScreen — pilot migration of launcher._splash.

Original function: launcher.py:_splash (L2250-L2365).
This class encapsulates the same visual output but with:
  - widgets built once in build(); subsequent visits only refresh data
  - pulse timer + click/key bindings auto-cancelled in on_exit

SYSTEM_TAGLINE and the connection manager are module-level in launcher.py,
so they are passed through the factory lambda at register() time (see
launcher.py wiring in Step 5). The screen receives the launcher Terminal
`app` to reuse drawing helpers (_draw_panel, _draw_kv_rows, etc.) and
header labels (h_stat, h_path, f_lbl).
"""
from __future__ import annotations

import tkinter as tk
from typing import Any

from core.ui.ui_palette import (
    AMBER, AMBER_B, AMBER_D, BG, BORDER, DIM, DIM2, FONT,
    GREEN, RED, WHITE,
)

from launcher_support.screens.base import Screen


class SplashScreen(Screen):
    def __init__(self, parent: tk.Misc, app: Any, conn: Any, tagline: str):
        super().__init__(parent)
        self.app = app
        self.conn = conn
        self.tagline = tagline
        self.canvas: tk.Canvas | None = None
        self._pulse_cursor_on = True
        self._design_w = app._SPLASH_DESIGN_W
        self._design_h = app._SPLASH_DESIGN_H

    def build(self) -> None:
        f = tk.Frame(self.container, bg=BG)
        f.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(
            f, bg=BG, highlightthickness=0,
            width=self._design_w, height=self._design_h,
        )
        self.canvas.pack(fill="both", expand=True)

        canvas = self.canvas
        canvas.create_line(48, 48, 872, 48, fill=AMBER_D, width=1)
        canvas.create_line(48, 596, 872, 596, fill=DIM2, width=1)

        LOGO_CX, LOGO_CY = 460, 108
        self.app._draw_aurum_logo(canvas, LOGO_CX, LOGO_CY, scale=40,
                                  tag="splash-logo")
        canvas.create_text(LOGO_CX, 180, anchor="center", text="A U R U M",
                           font=(FONT, 22, "bold"), fill=WHITE, tags="wordmark")
        canvas.create_text(LOGO_CX, 210, anchor="center", text="F I N A N C E",
                           font=(FONT, 12), fill=AMBER_D, tags="wordmark")
        canvas.create_line(LOGO_CX - 140, 230, LOGO_CX + 140, 230,
                           fill=AMBER_D, width=1, tags="wordmark")
        canvas.create_text(LOGO_CX, 246, anchor="center", text=self.tagline,
                           font=(FONT, 8, "bold"), fill=DIM, tags="subtitle")
        canvas.create_line(280, 268, 640, 268, fill=BORDER, width=1,
                           tags="subtitle")
        canvas.create_text(460, 500, anchor="center",
                           text="[ ENTER TO ACCESS DESK ]_",
                           font=(FONT, 11, "bold"), fill=AMBER_B,
                           tags="prompt2")

    def on_enter(self, **kwargs: Any) -> None:
        app = self.app
        app.h_path.configure(text="")
        app.h_stat.configure(text="READY", fg=AMBER_B)
        app.f_lbl.configure(text="ENTER proceed  |  CLICK proceed  |  Q quit")

        canvas = self.canvas
        try:
            st = self.conn.status_summary()
            market_val = st.get("market", "-")
        except Exception:
            market_val = "-"
        try:
            keys = app._load_json("keys.json")
            has_tg = bool(keys.get("telegram", {}).get("bot_token"))
            has_keys = bool(
                keys.get("demo", {}).get("api_key")
                or keys.get("testnet", {}).get("api_key")
            )
        except Exception:
            has_tg = False
            has_keys = False

        market_cell = "LIVE" if market_val and market_val != "-" else "OFFLINE"
        market_col = GREEN if market_cell == "LIVE" else DIM
        conn_cell = "BINANCE READY" if has_keys else "OFFLINE"
        conn_col = GREEN if has_keys else DIM
        tg_cell = "ONLINE" if has_tg else "OFFLINE"
        tg_col = GREEN if has_tg else DIM

        # Clear previous "splash" tagged content so re-entry refreshes values
        canvas.delete("splash")

        app._draw_panel(canvas, 140, 296, 780, 414,
                        title="SESSION OVERVIEW", accent=AMBER, tag="splash")
        app._draw_kv_rows(canvas, 168, 330, [
            ("ENGINE", "AURUM CORE", WHITE),
            ("MODE", "OPERATOR CONSOLE", AMBER_B),
            ("ACCOUNT", "PAPER · MULTI", WHITE),
            ("ENVIRONMENT", "LOCAL", WHITE),
        ], value_x=316, tag="splash")
        app._draw_kv_rows(canvas, 472, 330, [
            ("MARKET FEED", market_cell, market_col),
            ("CONNECTION", conn_cell, conn_col),
            ("TELEGRAM", tg_cell, tg_col),
            ("RISK", "KILL-SWITCH ARMED", RED),
        ], value_x=640, tag="splash")

        # Bindings + timer (auto-cleanup in on_exit)
        self._bind(canvas, "<Button-1>", lambda e: app._splash_on_click())
        app._bind_global_nav()
        self._after(500, self._pulse_tick)

        # Resize hook
        self._bind(canvas, "<Configure>", self._render_resize)
        self._render_resize()

    def _render_resize(self, _event=None) -> None:
        if self.canvas is None:
            return
        self.app._apply_canvas_scale(
            self.canvas, self._design_w, self._design_h, 1.0,
        )

    def _pulse_tick(self) -> None:
        canvas = self.canvas
        if canvas is None:
            return
        try:
            cur = canvas.itemcget("prompt2", "text")
        except tk.TclError:
            return
        if cur.endswith("_"):
            canvas.itemconfigure("prompt2", text=cur[:-1] + " ")
        else:
            canvas.itemconfigure("prompt2", text=cur[:-1] + "_")
        self._after(500, self._pulse_tick)
```

- [ ] **Step 4: Run splash tests to verify pass**

```bash
python -m pytest tests/launcher/test_splash_screen.py -v
```

Expected: 4 tests pass (or skip if tk unavailable).

- [ ] **Step 5: Wire SplashScreen into `launcher.py`**

In `launcher.py` find the Terminal `__init__` around L1172. After the line that creates `self.main` (~L1327), add container + ScreenManager:

Before:
```python
        self.main = tk.Frame(self, bg=BG); self.main.pack(fill="both", expand=True)
```

After (replace the single line with 3 lines):
```python
        self.main = tk.Frame(self, bg=BG); self.main.pack(fill="both", expand=True)
        self.screens_container = tk.Frame(self.main, bg=BG)
        # Note: screens_container is pack()-ed lazily on first mgr.show().
        from launcher_support.screens import ScreenManager
        from launcher_support.screens.splash import SplashScreen
        self.screens = ScreenManager(parent=self.screens_container)
        # SYSTEM_TAGLINE and _conn are module-level globals in launcher.py —
        # captured by the lambda closure and injected into SplashScreen.
        self.screens.register(
            "splash",
            lambda parent: SplashScreen(
                parent=parent, app=self, conn=_conn, tagline=SYSTEM_TAGLINE,
            ),
        )
```

- [ ] **Step 6: Convert `_splash` to a thin wrapper**

Find `_splash` at L2250 and replace its body (but keep the signature):

```python
    def _splash(self):
        """Premium institutional landing screen (migrated to ScreenManager)."""
        self._clr()
        self._clear_kb()
        self.history.clear()
        # Ensure screens_container is visible (previous screen may have been
        # a legacy path that packed directly into self.main).
        if not self.screens_container.winfo_manager():
            self.screens_container.pack(fill="both", expand=True)
        self.screens.show("splash")
        try:
            self.focus_set()
        except Exception:
            pass
```

Delete the old body lines from the previous `f = tk.Frame(self.main, bg=BG)` down to `self._splash_pulse_after_id = self.after(500, self._splash_pulse_tick)`.

**Keep** `_render_splash`, `_splash_pulse_tick`, `_splash_on_click` methods — they're referenced by the Splash screen pulse timer internally or still used by legacy bindings elsewhere. If `_splash_pulse_tick` is unused after migration, it can be removed in a follow-up commit after verification.

- [ ] **Step 7: Run full pytest suite**

```bash
python -m pytest tests/ -q 2>&1 | tail -10
```

Expected: all pass, including new splash tests.

- [ ] **Step 8: Run smoke test**

```bash
python smoke_test.py --quiet
```

Expected: 178/178 pass.

- [ ] **Step 9: Manual sanity — launch the app, observe splash**

```bash
python launcher.py
```

Expected: splash appears, ENTER advances to menu. `[ ENTER TO ACCESS DESK ]_` pulses. No visual regression vs pre-migration.

Close the launcher after sanity check.

- [ ] **Step 10: Commit**

```bash
git add launcher_support/screens/splash.py tests/launcher/test_splash_screen.py launcher.py
git commit -m "feat(launcher): migrate _splash to SplashScreen via ScreenManager"
```

---

## Task 12: Documentation — migration guide

**Files:**
- Modify: `docs/architecture/screen_manager.md`

- [ ] **Step 1: Write the guide**

Replace stub with:

```markdown
# Screen Manager — Migration Guide

Infra: `launcher_support/screens/` package.
Spec: `docs/superpowers/specs/2026-04-20-launcher-screen-manager-design.md`.
First migration (piloto): `SplashScreen`.

## Why

`launcher.py` historically switches screens via `for w in X.winfo_children(): w.destroy()` + rebuild. With 40-200 widgets per screen, the destroy + re-layout costs 100-300ms — felt as "FPS-low lag". `ScreenManager` keeps widgets alive across visits; switching becomes `pack_forget()` + `pack()` (sub-millisecond).

## The contract

Every migrated screen subclasses `Screen` (see `base.py`):

```python
class MyScreen(Screen):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app  # launcher Terminal instance — access to drawing helpers, headers

    def build(self):
        # Create widgets ONCE. No data fetch here.
        ...

    def on_enter(self, **kwargs):
        # Refresh dynamic data. Arm timers with self._after(...). Register bindings with self._bind(...).
        ...

    def on_exit(self):
        super().on_exit()  # cancels tracked timers/bindings
        # Additional cleanup if needed.
```

**Do NOT** call `.destroy()` inside `on_exit`. The whole point is reuse.

## Timers & bindings

Use the helpers:
- `self._after(ms, callback)` — arms a `.after()` timer; auto-cancelled in `on_exit`.
- `self._bind(widget, seq, callback)` — binds; auto-unbound in `on_exit`.

Direct `self.container.after()` or `widget.bind()` is allowed but you're responsible for cleanup.

## Registering

In `launcher.py` Terminal `__init__`:

```python
self.screens.register("my_screen", lambda parent: MyScreen(parent=parent, app=self))
```

## Showing

Replace the old `self._clr()` + rebuild call site with:

```python
self._clr()
self._clear_kb()
if not self.screens_container.winfo_manager():
    self.screens_container.pack(fill="both", expand=True)
self.screens.show("my_screen", run_id=run_id)  # kwargs passed to on_enter
```

## Metrics

Each `show()` emits:
- Counter: `runtime_health.record("screen.<name>.first_visit" | "screen.<name>.reentry")`
- Log: `logger("aurum.launcher.screens").info("event=screen_switch name=<> phase=<> ms=<>")`

The legacy (non-migrated) screens can be instrumented with `@timed_legacy_switch("<name>")` decorator from `_metrics.py` — emits `screen.<name>.legacy_rebuild` for comparison.

## When to migrate a screen

After 1-2 days of normal use with instrumentation, inspect:

```bash
python -c "
from core.ops.health import runtime_health
for k, v in sorted(runtime_health.snapshot().items()):
    if k.startswith('screen.'):
        print(f'{k}: {v}')
"
```

Top screens by `legacy_rebuild` count × average ms are the next migration candidates. Follow the pattern in `launcher_support/screens/splash.py`.

## What NOT to migrate

- Screens with live data fetch on every tick (migrate the container, keep the fetch path).
- Screens that are only shown once per session (not worth the effort).
- Screens depending on mutable global state that changes between visits (revisit the state first).

## Rollback

If a migrated screen misbehaves, revert its wrapper in `launcher.py` to the pre-migration body. The ScreenManager itself can stay registered — it's inert if nothing calls `show()` for that name.

```

- [ ] **Step 2: Commit**

```bash
git add docs/architecture/screen_manager.md
git commit -m "docs(architecture): screen manager migration guide"
```

---

## Task 13: Final validation

**Files:** none modified — validation only.

- [ ] **Step 1: Full pytest suite**

```bash
python -m pytest tests/ -q 2>&1 | tail -5
```

Expected: all pass. Compare pass count to pre-plan baseline (was 1462 passed + 2 failed from engine tuning uncommitted; new tests add ~20-30 to pass count).

- [ ] **Step 2: Smoke test**

```bash
python smoke_test.py --quiet
```

Expected: 178/178.

- [ ] **Step 3: Manual launcher drive — collect metrics**

```bash
python launcher.py
```

Manually: open splash → navigate to main menu → back to splash → main menu → results → back → splash. Close launcher.

- [ ] **Step 4: Inspect metrics**

```bash
python -c "
import subprocess
# Re-open python to read fresh runtime_health? Better: parse log lines emitted during the run.
# If launcher logs to stderr, capture during run and grep.
print('See aurum.launcher.screens log entries from the launcher run above.')
print('Expected:')
print('  - screen.splash.first_visit >=1')
print('  - screen.splash.reentry >=1 (if user went splash -> menu -> splash)')
print('  - screen.<X>.legacy_rebuild lines for any decorated non-migrated screen')
"
```

- [ ] **Step 5: Validate success criteria**

Per spec Success Criteria:

1. **Quantitative**: `screen.splash.reentry` ms ≤ 50 AND ≥ 3× faster than `screen.splash.legacy_rebuild` ms (if splash had been decorated pre-migration — compare with similar-complexity screens).
2. **Qualitative**: João navigates splash ↔ menu and does NOT feel lag.
3. **Zero regression**: smoke + suite pass.
4. **Infra ready**: Task 11 was ~1 screen; second screen takes ~30min following the guide.
5. **Doc present**: `docs/architecture/screen_manager.md` complete.

- [ ] **Step 6: Session log + daily log update**

Per CLAUDE.md SESSION LOG rule:

```bash
# Create docs/sessions/2026-04-20_<HHMM>.md with commits + findings + state
# Update docs/days/2026-04-20.md
# Commit both
```

Content of session log should include:
- Number of commits this plan added (12-13)
- `screen.splash.reentry_ms` measured
- `screen.splash.first_visit_ms` measured
- Any `legacy_rebuild_ms` collected for candidate future migrations

- [ ] **Step 7: Final commit**

```bash
git add docs/sessions/2026-04-20_*.md docs/days/2026-04-20.md
git commit -m "docs(sessions): screen manager infra + splash piloto migrated"
```

---

## Self-Review Checklist (for the author)

Before closing this plan:

- [ ] **Spec coverage**: Every section in the spec has at least one task
  - [x] Goal → Tasks 1-13 cover infra + pilot + doc
  - [x] Architecture (Screen + Manager) → Tasks 3-7
  - [x] Components (files) → file list matches spec
  - [x] Data flow (first visit / reentry) → Tasks 5-6
  - [x] Error handling → Task 7
  - [x] Testing (unit, integration, regression) → Tasks 3-7, 10, 11
  - [x] Success criteria → Task 13
  - [x] Risks (timers, bindings, Tk testing, hybrid coexistence) → covered in Tasks 4, 10, 11
- [ ] **Placeholder scan**: grep for `TBD`, `TODO`, `implement later`, "similar to Task N" — NONE found
- [ ] **Type consistency**: `Screen`, `ScreenManager`, `emit_switch_metric`, `timed_legacy_switch`, `ScreenBuildError`, `ScreenContextError` consistent across all tasks
- [ ] **Exact paths**: every `Create:`/`Modify:` line has an exact path
- [ ] **Complete code**: every step that writes code has the full code (no snippets with `...`)
- [ ] **Expected outputs**: every `pytest` command has expected pass/fail count or phrase

If any row is unchecked, fix inline before handing off.
