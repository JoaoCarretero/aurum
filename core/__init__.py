"""AURUM Core — reusable trading engine components.

Top-level re-exports are resolved lazily via PEP 562 __getattr__. This
keeps ``from core.ui.ui_palette import BG`` (and other narrow imports)
cheap — they no longer trigger eager pandas / indicator loading.

Callers that want the convenient ``from core import fetch`` or
``core.fetch`` still work unchanged — the first access triggers the real
import on demand.
"""
from __future__ import annotations

# Map attribute name -> "<submodule>:<attr>" to import on first access.
_LAZY = {
    # core.data
    "fetch": "core.data:fetch",
    "fetch_all": "core.data:fetch_all",
    "validate": "core.data:validate",
    # core.indicators (module + selected attrs)
    "indicators": "core.indicators:indicators",
    "swing_structure": "core.indicators:swing_structure",
    "omega": "core.indicators:omega",
    "cvd": "core.indicators:cvd",
    "cvd_divergence": "core.indicators:cvd_divergence",
    "volume_imbalance": "core.indicators:volume_imbalance",
    "liquidation_proxy": "core.indicators:liquidation_proxy",
    # core.signals
    "decide_direction": "core.signals:decide_direction",
    "score_omega": "core.signals:score_omega",
    "score_chop": "core.signals:score_chop",
    "calc_levels": "core.signals:calc_levels",
    "calc_levels_chop": "core.signals:calc_levels_chop",
    "label_trade": "core.signals:label_trade",
    "label_trade_chop": "core.signals:label_trade_chop",
    # core.portfolio
    "detect_macro": "core.portfolio:detect_macro",
    "build_corr_matrix": "core.portfolio:build_corr_matrix",
    "portfolio_allows": "core.portfolio:portfolio_allows",
    "check_aggregate_notional": "core.portfolio:check_aggregate_notional",
    "_wr": "core.portfolio:_wr",
    "position_size": "core.portfolio:position_size",
    # core.htf
    "prepare_htf": "core.htf:prepare_htf",
    "merge_all_htf_to_ltf": "core.htf:merge_all_htf_to_ltf",
}


def __getattr__(name: str):
    if name not in _LAZY:
        raise AttributeError(f"module 'core' has no attribute {name!r}")
    import importlib
    modname, attr = _LAZY[name].split(":")
    mod = importlib.import_module(modname)
    value = getattr(mod, attr)
    globals()[name] = value  # cache for subsequent accesses
    return value


def __dir__():
    return sorted(list(_LAZY.keys()) + list(globals().keys()))


__all__ = list(_LAZY.keys())
