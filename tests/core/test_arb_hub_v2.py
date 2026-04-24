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


def test_filter_and_score_applies_profit_min(tk_root, monkeypatch):
    from launcher_support.screens import arbitrage_hub as ah
    app = _StubApp(tk_root)
    app._arb_filters["profit_min_usd"] = 3.0

    from types import SimpleNamespace
    def fake_score_opp(pair, cfg=None):
        profit_by_sym = {"HIGH": 5.0, "LOW": 1.0}
        return SimpleNamespace(
            score=80, grade="GO", viab="GO", breakeven_h=5.0,
            profit_usd_per_1k_24h=profit_by_sym.get(pair["symbol"], 0.0),
            depth_pct_at_1k=10.0,
            factors={"net_apr": 80, "volume": 60, "oi": 60,
                     "risk": 100, "slippage": 50, "venue": 90},
        )
    monkeypatch.setattr("core.arb.arb_scoring.score_opp", fake_score_opp)
    monkeypatch.setattr(app, "_arb_score_fallback",
                        lambda p: fake_score_opp(p), raising=False)
    monkeypatch.setattr(app, "_pair_min",
                        lambda a, b: min(x for x in (a, b) if x is not None),
                        raising=False)
    app._ARB_REALISTIC_APR_MAX = 500.0
    app._ARB_REALISTIC_VOL_MIN = 0.0
    app._ARB_RISKY_VENUES = frozenset()

    pairs = [
        {"symbol": "HIGH", "short_venue": "binance", "long_venue": "bybit",
         "_type": "CC", "net_apr": 100.0, "volume_24h": 10_000_000,
         "open_interest": 10_000_000, "risk": "LOW"},
        {"symbol": "LOW", "short_venue": "binance", "long_venue": "bybit",
         "_type": "CC", "net_apr": 10.0, "volume_24h": 10_000_000,
         "open_interest": 10_000_000, "risk": "LOW"},
    ]
    out = ah.filter_and_score(app, pairs)
    symbols = [p["symbol"] for p, _ in out]
    assert "HIGH" in symbols
    assert "LOW" not in symbols


def test_filter_and_score_applies_venues_allow(tk_root, monkeypatch):
    from launcher_support.screens import arbitrage_hub as ah
    app = _StubApp(tk_root)
    app._arb_filters["venues_allow"] = ["binance", "bybit"]

    from types import SimpleNamespace
    sr = SimpleNamespace(score=80, grade="GO", viab="GO", breakeven_h=5.0,
                          profit_usd_per_1k_24h=5.0, depth_pct_at_1k=10.0,
                          factors={})
    monkeypatch.setattr("core.arb.arb_scoring.score_opp", lambda p, cfg=None: sr)
    monkeypatch.setattr(app, "_arb_score_fallback",
                        lambda p: sr, raising=False)
    monkeypatch.setattr(app, "_pair_min",
                        lambda a, b: min(x for x in (a, b) if x is not None),
                        raising=False)
    app._ARB_REALISTIC_APR_MAX = 500.0
    app._ARB_REALISTIC_VOL_MIN = 0.0
    app._ARB_RISKY_VENUES = frozenset()

    p_ok = {"symbol": "OK", "short_venue": "binance", "long_venue": "bybit",
            "_type": "CC", "net_apr": 30.0, "volume_24h": 10_000_000,
            "open_interest": 1_000_000, "risk": "LOW"}
    p_no = {"symbol": "NO", "short_venue": "hyperliquid", "long_venue": "dydx",
            "_type": "DD", "net_apr": 30.0, "volume_24h": 10_000_000,
            "open_interest": 1_000_000, "risk": "LOW"}
    out = ah.filter_and_score(app, [p_ok, p_no])
    symbols = [p["symbol"] for p, _ in out]
    assert "OK" in symbols
    assert "NO" not in symbols


def test_filter_and_score_applies_life_min(tk_root, monkeypatch):
    from launcher_support.screens import arbitrage_hub as ah
    app = _StubApp(tk_root)
    app._arb_filters["life_min_seconds"] = 60  # 1 minute

    class StubTracker:
        def __init__(self):
            self.ages = {"OLD": 300.0, "NEW": 5.0}
        def observe_pairs(self, pairs, now):
            pass
        def age(self, key, now):
            for sym, age in self.ages.items():
                if sym in key:
                    return age
            return None
    tracker = StubTracker()
    from core.arb import lifetime as _l
    def patched_key(pair):
        return pair.get("symbol", "UNKNOWN")
    monkeypatch.setattr(_l, "stable_key", patched_key)
    monkeypatch.setattr(app, "_arb_lifetime_tracker",
                        lambda: tracker, raising=False)

    from types import SimpleNamespace
    sr = SimpleNamespace(score=80, grade="GO", viab="GO", breakeven_h=5.0,
                          profit_usd_per_1k_24h=5.0, depth_pct_at_1k=10.0,
                          factors={})
    monkeypatch.setattr("core.arb.arb_scoring.score_opp", lambda p, cfg=None: sr)
    monkeypatch.setattr(app, "_arb_score_fallback",
                        lambda p: sr, raising=False)
    monkeypatch.setattr(app, "_pair_min",
                        lambda a, b: min(x for x in (a, b) if x is not None),
                        raising=False)
    app._ARB_REALISTIC_APR_MAX = 500.0
    app._ARB_REALISTIC_VOL_MIN = 0.0
    app._ARB_RISKY_VENUES = frozenset()

    pairs = [
        {"symbol": "OLD", "short_venue": "binance", "long_venue": "bybit",
         "_type": "CC", "net_apr": 30.0, "volume_24h": 10_000_000,
         "open_interest": 1_000_000, "risk": "LOW"},
        {"symbol": "NEW", "short_venue": "binance", "long_venue": "bybit",
         "_type": "CC", "net_apr": 30.0, "volume_24h": 10_000_000,
         "open_interest": 1_000_000, "risk": "LOW"},
    ]
    out = ah.filter_and_score(app, pairs)
    symbols = [p["symbol"] for p, _ in out]
    assert "OLD" in symbols
    assert "NEW" not in symbols
