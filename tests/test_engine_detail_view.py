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


def test_scan_funnel_block_shows_funnel_metrics(gui_root):
    from launcher_support.engine_detail_view import render_scan_funnel_block
    parent = tk.Frame(gui_root)
    run = _run_with_hb({
        "last_scan_scanned": 11, "last_scan_dedup": 8,
        "last_scan_stale": 1, "last_scan_live": 2,
        "last_scan_opened": 1,
    })
    render_scan_funnel_block(parent, run)
    text_pool = " ".join(_collect_text(parent))
    assert "scanned" in text_pool.lower()
    assert "11" in text_pool
    assert "opened" in text_pool.lower()
    parent.destroy()


def test_decisions_block_renders_recent_signals(gui_root, tmp_path):
    from launcher_support.engine_detail_view import render_decisions_block
    parent = tk.Frame(gui_root)
    sig_dir = tmp_path / "millennium_paper" / "rid" / "reports"
    sig_dir.mkdir(parents=True)
    (sig_dir / "signals.jsonl").write_text(
        '{"ts":"t","symbol":"BTCUSDT","decision":"opened","score":0.8,"reason":"r"}\n',
        encoding="utf-8")
    run = _run_with_hb({}, source="local",
                       run_dir=str(sig_dir.parent))
    render_decisions_block(parent, run)
    text_pool = " ".join(_collect_text(parent))
    assert "BTCUSDT" in text_pool
    assert "opened" in text_pool.lower()
    parent.destroy()
