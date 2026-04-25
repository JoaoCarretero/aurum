"""EngineDetailScreen mount/unmount + on_enter(run=...) skeleton."""
import pytest
import tkinter as tk

from launcher_support.runs_history import RunSummary


@pytest.fixture(scope="module")
def gui_root():
    try:
        root = tk.Tk()
    except Exception:
        pytest.skip("tk unavailable")
    root.withdraw()
    yield root
    try:
        root.destroy()
    except Exception:
        pass


@pytest.fixture
def fake_run():
    return RunSummary(
        run_id="2026-04-24_174017p_test",
        engine="MILLENNIUM",
        mode="paper",
        status="running",
        started_at="2026-04-24T17:40:17Z",
        stopped_at=None,
        last_tick_at="2026-04-24T20:30:00Z",
        ticks_ok=10,
        ticks_fail=0,
        novel=2,
        equity=10005.50,
        initial_balance=10000.0,
        roi_pct=0.055,
        trades_closed=1,
        source="vps",
        run_dir=None,
        heartbeat={
            "last_error": None, "primed": True, "ks_state": "armed",
            "last_scan_scanned": 11, "last_scan_dedup": 8,
            "last_scan_stale": 1, "last_scan_live": 2,
        },
    )


def test_engine_detail_mounts_cleanly(gui_root, fake_run):
    from launcher_support.screens.engine_detail import EngineDetailScreen

    class _FakeApp:
        screens = None
        def _kb(self, *_a, **_k): pass
        h_path = type("L", (), {"configure": lambda *a, **k: None})()
        h_stat = type("L", (), {"configure": lambda *a, **k: None})()
        f_lbl  = type("L", (), {"configure": lambda *a, **k: None})()

    parent = tk.Frame(gui_root)
    screen = EngineDetailScreen(parent=parent, app=_FakeApp(),
                                client_factory=lambda: None)
    screen.mount()
    screen.on_enter(run=fake_run)
    screen.on_exit()
    parent.destroy()


def test_engine_detail_requires_run_kwarg(gui_root):
    from launcher_support.screens.engine_detail import EngineDetailScreen

    class _FakeApp:
        def _kb(self, *_a, **_k): pass

    parent = tk.Frame(gui_root)
    screen = EngineDetailScreen(parent=parent, app=_FakeApp(),
                                client_factory=lambda: None)
    screen.mount()
    with pytest.raises(TypeError):
        screen.on_enter()  # missing run kwarg
    screen.on_exit()
    parent.destroy()


def test_auto_refresh_armed_only_when_running(gui_root, fake_run):
    """Status==running arms 5s timer; status==stopped does not."""
    import dataclasses

    from launcher_support.screens.engine_detail import EngineDetailScreen

    class _FakeApp:
        screens = None
        def _kb(self, *_a, **_k): pass
        h_path = type("L", (), {"configure": lambda *a, **k: None})()
        h_stat = type("L", (), {"configure": lambda *a, **k: None})()
        f_lbl  = type("L", (), {"configure": lambda *a, **k: None})()

    parent = tk.Frame(gui_root)
    screen = EngineDetailScreen(parent=parent, app=_FakeApp(),
                                client_factory=lambda: None)
    screen.mount()

    # status=running → timer armed.
    screen.on_enter(run=fake_run)
    assert screen._refresh_aid is not None
    screen.on_exit()
    assert screen._refresh_aid is None  # cleared on exit

    # status=stopped → no timer.
    fake_run_stopped = dataclasses.replace(fake_run, status="stopped")
    screen.on_enter(run=fake_run_stopped)
    assert screen._refresh_aid is None, \
        "stopped run must not arm auto-refresh"
    screen.on_exit()
    parent.destroy()
