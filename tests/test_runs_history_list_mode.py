"""mode="list" em render_runs_history skipa criação do pane direito."""
import pytest
import tkinter as tk

from launcher_support.runs_history import render_runs_history


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


class _FakeLauncher:
    def after(self, *_a, **_k):
        return "x"

    def after_cancel(self, *_a, **_k):
        pass


def test_list_mode_skips_right_pane(gui_root):
    parent = tk.Frame(gui_root)
    root = render_runs_history(parent, _FakeLauncher(),
                               client_factory=lambda: None,
                               mode="list")
    state = getattr(root, "_runs_history_state", None)
    assert state is not None
    assert state.get("detail_host") is None, \
        "list mode must not create detail pane"
    parent.destroy()


def test_split_mode_keeps_right_pane(gui_root):
    parent = tk.Frame(gui_root)
    root = render_runs_history(parent, _FakeLauncher(),
                               client_factory=lambda: None,
                               mode="split")
    state = getattr(root, "_runs_history_state", None)
    assert state is not None
    assert state.get("detail_host") is not None, \
        "split mode must preserve detail pane (default)"
    parent.destroy()


def test_columns_schema_has_14_cols():
    from launcher_support.runs_history import _COLUMNS

    labels = [label for label, _w in _COLUMNS]
    assert "SHARPE" in labels
    assert "DD%" in labels
    assert "#POS" in labels
    assert len(_COLUMNS) == 14
    # Order check: SHARPE/DD%/#POS aparecem entre ROI e TRADES
    roi_idx = labels.index("ROI")
    trades_idx = labels.index("TRADES")
    sharpe_idx = labels.index("SHARPE")
    dd_idx = labels.index("DD%")
    pos_idx = labels.index("#POS")
    assert roi_idx < dd_idx < sharpe_idx < pos_idx < trades_idx
