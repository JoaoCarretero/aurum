"""Drill-down: row click em mode='list' invoca screens.show('engine_detail', run=r)."""
import pytest
import tkinter as tk
from unittest.mock import MagicMock

from launcher_support.runs_history import RunSummary, render_runs_history


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


def _fake_run():
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
        heartbeat=None,
    )


def test_list_mode_row_click_triggers_drilldown(gui_root):
    parent = tk.Frame(gui_root)
    parent.pack(fill="both", expand=True)
    mock_screens = MagicMock()
    launcher = MagicMock()
    launcher.screens = mock_screens
    launcher.after = MagicMock(return_value="x")
    launcher.after_cancel = MagicMock()

    root = render_runs_history(parent, launcher,
                               client_factory=lambda: None,
                               mode="list")
    state = root._runs_history_state
    state["rows"] = [_fake_run()]
    from launcher_support.runs_history import _paint_rows
    _paint_rows(state)

    # Tk drops Button-1 events em widgets unmapped (root.withdraw'd).
    # deiconify briefly pra map a hierarquia e dispatchar o evento.
    gui_root.deiconify()
    gui_root.update()

    # Find first row widget; simulate click.
    # Section headers tambem sao Frames, mas rows sao distintas por
    # cursor='hand2' (set em _render_run_row). Filtrar por isso garante
    # que pegamos a row clicavel, nao um header.
    table_wrap = state["table_wrap"]
    rows = [w for w in table_wrap.winfo_children()
            if w.winfo_children() and str(w.cget("cursor")) == "hand2"]
    assert rows, "expected at least one row painted"
    first_row = rows[0]
    # when='now' force-dispatcha o handler imediatamente, sem mainloop.
    first_row.event_generate("<Button-1>", when="now")
    gui_root.update()
    gui_root.withdraw()

    mock_screens.show.assert_called_with("engine_detail", run=_fake_run())
    parent.destroy()
