"""engine_detail_view block render contracts."""
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


def _run_with_hb(hb=None, status="running", **kwargs):
    base = dict(
        run_id="rid", engine="MILLENNIUM", mode="paper", status=status,
        started_at="2026-04-24T17:40:17Z", stopped_at=None,
        last_tick_at="2026-04-24T20:30:00Z",
        ticks_ok=10, ticks_fail=0, novel=2, equity=10005.0,
        initial_balance=10000.0, roi_pct=0.05, trades_closed=1,
        source="vps", run_dir=None, heartbeat=hb or {},
    )
    base.update(kwargs)
    return RunSummary(**base)


def test_triage_block_shows_last_error(gui_root):
    from launcher_support.engine_detail_view import render_triage_block

    parent = tk.Frame(gui_root)
    run = _run_with_hb({"last_error": "boom: traceback (most recent call last)"})
    render_triage_block(parent, run)

    text_pool = " ".join(_collect_text(parent))
    assert "LAST ERROR" in text_pool
    assert "boom" in text_pool
    parent.destroy()


def test_triage_block_no_error_renders_clean_status(gui_root):
    from launcher_support.engine_detail_view import render_triage_block
    parent = tk.Frame(gui_root)
    run = _run_with_hb({"last_error": None})
    render_triage_block(parent, run)
    text_pool = " ".join(_collect_text(parent))
    assert "LAST ERROR" not in text_pool  # banner suprimido
    parent.destroy()


def test_cadence_block_shows_drift(gui_root):
    from launcher_support.engine_detail_view import render_cadence_block
    parent = tk.Frame(gui_root)
    run = _run_with_hb({
        "primed": True, "ks_state": "armed", "tick_sec": 900,
    })
    render_cadence_block(parent, run)
    text_pool = " ".join(_collect_text(parent))
    assert "TICK CADENCE" in text_pool or "CADENCE" in text_pool
    parent.destroy()


def _collect_text(widget):
    """DFS de todos os tk.Label.cget('text') em widget e descendants."""
    out = []
    if isinstance(widget, tk.Label):
        try:
            out.append(str(widget.cget("text")))
        except Exception:
            pass
    for child in widget.winfo_children():
        out.extend(_collect_text(child))
    return out
