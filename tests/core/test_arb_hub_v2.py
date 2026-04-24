"""Integration smoke for Arbitrage Hub v2 density redesign.

Stubs out the Tk layer with a minimal fake app so we can assert on the
label dict the render function produces, without spinning up a Tk root.
"""
from __future__ import annotations

import pytest

tk = pytest.importorskip("tkinter")


class _StubApp:
    """Minimal App-like stub satisfying render()'s expectations."""

    def __init__(self, root):
        self.root = root
        self.main = tk.Frame(root)
        self.history = []
        self.h_path = tk.Label(root, text="")
        self.h_stat = tk.Label(root, text="")
        self.f_lbl = tk.Label(root, text="")
        self._kb_bound = []

        import launcher as _l
        self._ARB_TAB_DEFS = _l.App._ARB_TAB_DEFS
        self._ARB_TAB_CATEGORIES = _l.App._ARB_TAB_CATEGORIES
        self._ARB_LEGACY_TAB_MAP = _l.App._ARB_LEGACY_TAB_MAP
        self._ARB_FILTER_DEFAULTS = dict(_l.App._ARB_FILTER_DEFAULTS)
        self._ARB_OPPS_COLS = _l.App._ARB_OPPS_COLS
        self._arb_filters = dict(self._ARB_FILTER_DEFAULTS)
        self._arb_cache = None
        self._arb_tab = "cex-cex"
        self._arb_tab_labels = {}
        self._arb_active_type_tab = None

    def _clr(self): pass
    def _clear_kb(self): pass
    def _kb(self, k, fn): self._kb_bound.append(k)
    def _bind_global_nav(self): pass
    def _ui_call_soon(self, fn): fn()

    def _arb_update_status_strip(self): pass
    def _arbitrage_hub(self, t): self._arb_tab = t
    def _arb_hub_scan_async(self): pass
    def _arb_schedule_refresh(self): pass
    def _arb_schedule_clock(self): pass
    def _arb_scan_is_fresh(self): return True
    def _arb_hub_telem_update(self, *a, **kw): pass

    def _arb_filter_state(self):
        return self._arb_filters

    def _arb_render_positions(self, parent): pass
    def _arb_render_history(self, parent): pass
    def _arb_render_tab_filtered(self, parent, tab_id):
        self._arb_active_type_tab = tab_id


@pytest.fixture
def tk_root():
    root = tk.Tk()
    root.withdraw()
    yield root
    root.destroy()


def test_render_mounts_eight_tab_labels(tk_root):
    from launcher_support.screens.arbitrage_hub import render
    app = _StubApp(tk_root)
    render(app, tab="cex-cex")
    assert set(app._arb_tab_labels.keys()) == {
        "cex-cex", "dex-dex", "cex-dex",
        "perp-perp", "spot-spot", "basis",
        "positions", "history",
    }


def test_render_active_tab_default_is_cex_cex(tk_root):
    from launcher_support.screens.arbitrage_hub import render
    app = _StubApp(tk_root)
    render(app, tab="cex-cex")
    assert app._arb_tab == "cex-cex"


def test_render_legacy_tab_aliases_to_v2_via_render_hub(tk_root):
    from launcher_support.screens.arbitrage_hub import render_hub
    app = _StubApp(tk_root)
    render_hub(app, tab="opps")
    assert app._arb_tab == "cex-cex"


def test_render_dispatches_type_tabs_to_generic(tk_root):
    from launcher_support.screens.arbitrage_hub import render
    app = _StubApp(tk_root)
    for tab_id in ("cex-cex", "dex-dex", "cex-dex",
                    "perp-perp", "spot-spot", "basis"):
        app._arb_active_type_tab = None
        render(app, tab=tab_id)
        assert app._arb_active_type_tab == tab_id, \
            f"tab {tab_id!r} did not dispatch to generic"
