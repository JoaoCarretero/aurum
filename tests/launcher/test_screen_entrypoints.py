from __future__ import annotations

import importlib
import sys
import tkinter as tk
from types import SimpleNamespace

import pytest


@pytest.fixture(scope="module")
def tk_root():
    root = tk.Tk()
    root.withdraw()
    yield root
    try:
        root.destroy()
    except Exception:
        pass


class _ProbeLabel:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def configure(self, **kwargs) -> None:
        self.calls.append(dict(kwargs))


class _ProbeApp:
    def __init__(self) -> None:
        self.h_path = _ProbeLabel()
        self.h_stat = _ProbeLabel()
        self.f_lbl = _ProbeLabel()
        self.paint_metrics: list[str] = []
        self.nav_bound = 0
        self.menu_calls: list[str] = []
        self._engines_live_handle = None
        self._macro_render_after = None
        self._macro_cycle_after = None
        self._macro_page_token = None

    def _bind_global_nav(self) -> None:
        self.nav_bound += 1

    def _schedule_first_paint_metric(self, name: str) -> None:
        self.paint_metrics.append(name)

    def _menu(self, name: str) -> None:
        self.menu_calls.append(name)

    def focus_set(self) -> None:
        return None


def test_screens_package_import_stays_lazy(monkeypatch):
    import launcher_support.screens as screens_pkg

    concrete_modules = [
        "launcher_support.screens.connections",
        "launcher_support.screens.data_center",
        "launcher_support.screens.engines_live",
        "launcher_support.screens.macro_brain",
    ]
    for name in concrete_modules:
        monkeypatch.delitem(sys.modules, name, raising=False)

    importlib.reload(screens_pkg)

    for name in concrete_modules:
        assert name not in sys.modules
    assert hasattr(screens_pkg, "Screen")
    assert hasattr(screens_pkg, "ScreenManager")
    assert hasattr(screens_pkg, "register_default_screens")


def test_engines_live_screen_schedules_first_paint_on_initial_mount(tk_root, monkeypatch):
    from launcher_support.screens.engines_live import EnginesLiveScreen
    from launcher_support import engines_live_view

    render_calls: list[tuple[object, object]] = []

    def fake_render(app, host, *, on_escape):
        render_calls.append((app, host))
        return {"root": host, "cleanup": lambda: None}

    monkeypatch.setattr(engines_live_view, "render", fake_render)

    app = _ProbeApp()
    conn = SimpleNamespace(active_market="crypto")
    screen = EnginesLiveScreen(parent=tk_root, app=app, conn=conn)
    screen.mount()

    screen.on_enter()

    assert app.paint_metrics == ["engines_live"]
    assert app.nav_bound == 1
    assert len(render_calls) == 1
    assert app._engines_live_handle["root"] is screen.host


def test_macro_brain_screen_defers_first_cycle_and_marks_first_paint(tk_root, monkeypatch):
    from launcher_support.screens.macro_brain import MacroBrainScreen
    from macro_brain import dashboard_view

    render_calls: list[object] = []
    scheduled: list[int] = []

    def fake_render(host, app=None):
        render_calls.append(host)

    monkeypatch.setattr(dashboard_view, "render", fake_render)

    app = _ProbeApp()
    screen = MacroBrainScreen(parent=tk_root, app=app)
    screen.mount()
    monkeypatch.setattr(screen, "_after", lambda ms, cb: scheduled.append(ms) or f"after-{ms}")

    screen.on_enter()

    assert app.paint_metrics == ["macro_brain"]
    assert app.nav_bound == 1
    assert len(render_calls) == 1
    assert scheduled == [3_000, 30_000]
