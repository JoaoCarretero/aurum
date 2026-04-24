"""Diagnose what's happening when the Arbitrage Hub shows no data.

Runs the full pipeline headlessly and prints each step, so we can see
exactly where the chain breaks (scanner → filter → score → paint).

Usage:
    python tools/diagnose_arb_hub.py
"""
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

# Ensure repo root is on sys.path when invoked as a script.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def main():
    print("=" * 60)
    print("ARBITRAGE HUB DIAGNOSTIC")
    print("=" * 60)

    # 1. AURUM_TEST_MODE check
    tm = os.getenv("AURUM_TEST_MODE", "")
    print(f"\n[1] AURUM_TEST_MODE env: {tm!r}")
    if tm.strip().lower() in {"1", "true", "yes", "on"}:
        print("    !!! TEST MODE ACTIVE — hub will short-circuit to empty data.")
        print("    Fix: unset AURUM_TEST_MODE before running launcher.")
        return

    # 2. Scanner — direct
    print("\n[2] Scanner fetch...")
    try:
        from core.ui.funding_scanner import FundingScanner
        s = FundingScanner()
        opps = s.scan()
        stats = s.stats()
        print(f"    scan: {len(opps)} opps")
        print(f"    venues online: {stats.get('venues_online')}/{stats.get('venues_total')}")
        print(f"    CEX online: {stats.get('cex_online')}, DEX online: {stats.get('dex_online')}")
        if stats.get("errors"):
            print(f"    venue errors: {list(stats['errors'].keys())}")
    except Exception as e:
        print(f"    SCANNER FAILED: {type(e).__name__}: {e}")
        traceback.print_exc()
        return

    # 3. arb_cc pairs
    print("\n[3] arb_cc pairs...")
    try:
        arb_cc = s.arb_pairs(mode="cex-cex", min_spread_apr=1.0)
        arb_dd = s.arb_pairs(mode="dex-dex", min_spread_apr=1.0)
        arb_cd = s.arb_pairs(mode="cex-dex", min_spread_apr=1.0)
        basis = s.basis_pairs(min_basis_bps=5)
        spot = s.spot_arb_pairs(min_spread_bps=3)
        print(f"    arb_cc: {len(arb_cc)}  arb_dd: {len(arb_dd)}  arb_cd: {len(arb_cd)}")
        print(f"    basis: {len(basis)}  spot: {len(spot)}")
    except Exception as e:
        print(f"    PAIRS FAILED: {type(e).__name__}: {e}")
        traceback.print_exc()
        return

    total_pairs = len(arb_cc) + len(arb_dd) + len(arb_cd) + len(basis) + len(spot)
    if total_pairs == 0:
        print("\n    !!! Zero pairs produced. Scanner got data but no arb opps met")
        print("    the min thresholds. Check FundingScanner venue coverage.")
        return

    # 4. Tag _type like paint_opps does
    print("\n[4] Tagging + scoring + filtering (like paint_opps)...")
    tagged = []
    for p in arb_cc:
        pp = dict(p); pp["_type"] = "CC"; tagged.append(pp)
    for p in arb_dd:
        pp = dict(p); pp["_type"] = "DD"; tagged.append(pp)
    for p in arb_cd:
        pp = dict(p); pp["_type"] = "CD"; tagged.append(pp)
    for p in basis:
        pp = dict(p); pp["_type"] = "BS"
        pp.setdefault("net_apr", pp.get("basis_apr"))
        pp.setdefault("short_venue", pp.get("venue_perp"))
        pp.setdefault("long_venue", pp.get("venue_spot"))
        tagged.append(pp)
    for p in spot:
        pp = dict(p); pp["_type"] = "SP"
        pp.setdefault("net_apr", abs(pp.get("spread_bps", 0) or 0) / 100.0)
        pp.setdefault("short_venue", pp.get("venue_a"))
        pp.setdefault("long_venue", pp.get("venue_b"))
        tagged.append(pp)
    print(f"    tagged: {len(tagged)} pairs")

    # 5. matches_type per tab
    from core.arb.tab_matrix import matches_type
    print("\n[5] matches_type per tab (how many pairs go to each tab):")
    for tab_id in ("cex-cex", "dex-dex", "cex-dex", "perp-perp", "spot-spot", "basis"):
        n = sum(1 for p in tagged if matches_type(p, tab_id))
        print(f"    {tab_id}: {n}")

    # 6. filter_and_score — full pipeline with default filters
    print("\n[6] filter_and_score (with default filters)...")
    try:
        import launcher
        from launcher_support.screens.arbitrage_hub import filter_and_score

        class StubApp:
            pass
        app = StubApp()
        app._ARB_FILTER_DEFAULTS = dict(launcher.App._ARB_FILTER_DEFAULTS)
        app._arb_filters = dict(app._ARB_FILTER_DEFAULTS)
        app._ARB_RISKY_VENUES = getattr(launcher.App, "_ARB_RISKY_VENUES", frozenset())
        app._ARB_REALISTIC_APR_MAX = getattr(launcher.App, "_ARB_REALISTIC_APR_MAX", 500.0)
        app._ARB_REALISTIC_VOL_MIN = getattr(launcher.App, "_ARB_REALISTIC_VOL_MIN", 0)
        app._arb_filter_state = lambda: app._arb_filters
        app._pair_min = lambda a, b: min([x for x in (a, b) if x is not None] or [0])

        from core.arb.lifetime import LifetimeTracker
        _tracker = LifetimeTracker()
        app._arb_lifetime_tracker = lambda: _tracker

        print(f"    filter defaults: {app._arb_filters}")
        print(f"    APR_MAX: {app._ARB_REALISTIC_APR_MAX}  VOL_MIN: {app._ARB_REALISTIC_VOL_MIN}")

        result = filter_and_score(app, tagged)
        print(f"    filter_and_score: {len(result)} pairs passed")
        if result:
            for p, sr in result[:5]:
                viab = getattr(sr, "viab", sr.grade)
                print(f"      {p.get('symbol'):>8} [{p.get('_type')}] "
                      f"apr={p.get('net_apr', 0):+.1f}% grade={sr.grade} "
                      f"viab={viab} profit=${getattr(sr, 'profit_usd_per_1k_24h', 0) or 0:+.2f}")
    except Exception as e:
        print(f"    FILTER FAILED: {type(e).__name__}: {e}")
        traceback.print_exc()
        return

    # 7. Final verdict
    print("\n" + "=" * 60)
    if len(result) == 0:
        print("!!! Scanner works, but filter_and_score kills everything.")
        print("    Check _ARB_FILTER_DEFAULTS above. If grade_min=MAYBE +")
        print("    realistic_only=True filters too aggressive, try:")
        print("        In launcher: click [ALL] button to loosen filters.")
        print("    Or edit _ARB_FILTER_DEFAULTS in launcher.py.")
    else:
        print(f"Pipeline health: OK. {len(result)} pairs would render.")
        print("If the hub shows NOTHING, the bug is in the UI wiring:")
        print("  - _arb_opps_repaint not bound?")
        print("  - paint_opps exception suppressed?")
        print("  - hub_scan_async thread dying silently?")
        print("  - _arb_active_type_tab unset?")
        print()
        print("Run launcher from terminal: `python launcher.py` and watch")
        print("stderr for any suppressed exceptions.")


if __name__ == "__main__":
    main()
