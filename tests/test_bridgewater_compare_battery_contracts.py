from pathlib import Path

from tools.bridgewater_compare_battery import (
    REPO,
    _aggregate_bucket,
    _resolve_bridgewater_module,
    _resolve_variant_runtime,
    _variant_sentiment,
)


def test_variant_sentiment_disables_only_oi_channel():
    original = {
        "BTCUSDT": {
            "funding_z": "keep",
            "oi_df": {"rows": 10},
            "oi_ready": True,
            "ls_signal": "keep-ls",
            "ls_ready": True,
        }
    }

    variant = _variant_sentiment(original, disable_oi=True)

    assert variant["BTCUSDT"]["funding_z"] == "keep"
    assert variant["BTCUSDT"]["ls_signal"] == "keep-ls"
    assert variant["BTCUSDT"]["ls_ready"] is True
    assert variant["BTCUSDT"]["oi_df"] is None
    assert variant["BTCUSDT"]["oi_ready"] is False
    assert original["BTCUSDT"]["oi_ready"] is True


def test_aggregate_bucket_groups_unknown_and_computes_stats():
    trades = [
        {"macro_bias": "BULL", "result": "WIN", "pnl": 100.0, "r_multiple": 1.2},
        {"macro_bias": "BULL", "result": "LOSS", "pnl": -50.0, "r_multiple": -0.7},
        {"macro_bias": None, "result": "WIN", "pnl": 25.0, "r_multiple": 0.3},
    ]

    out = _aggregate_bucket(trades, "macro_bias")

    assert out["BULL"] == {"n": 2, "win_rate": 50.0, "pnl": 50.0, "avg_r": 0.25}
    assert out["UNKNOWN"] == {"n": 1, "win_rate": 100.0, "pnl": 25.0, "avg_r": 0.3}


def test_resolve_bridgewater_module_imports_from_repo_root():
    bw = _resolve_bridgewater_module()

    assert bw.__name__ == "engines.bridgewater"
    assert Path(bw.__file__).resolve().parent.name == "engines"
    assert REPO.name == "aurum.finance"


def test_resolve_variant_runtime_applies_robust_gates_without_forcing_oi_off():
    bw = _resolve_bridgewater_module()

    full = _resolve_variant_runtime(
        bw,
        preset="robust",
        disable_oi=False,
        strict_direction=False,
        min_components=4,
        min_dir_thresh=None,
        enable_symbol_health=False,
        allowed_regimes="BEAR,CHOP",
        post_trade_cooldown_bars=0,
    )
    amputated = _resolve_variant_runtime(
        bw,
        preset="robust",
        disable_oi=True,
        strict_direction=False,
        min_components=4,
        min_dir_thresh=None,
        enable_symbol_health=False,
        allowed_regimes="BEAR,CHOP",
        post_trade_cooldown_bars=0,
    )

    assert full["disable_oi"] is False
    assert full["strict_direction"] is True
    assert full["min_components"] == 2
    assert full["allowed_macro_regimes"] == {"BEAR", "CHOP"}
    assert amputated["disable_oi"] is True
    assert amputated["min_components"] == 2


def test_resolve_variant_runtime_supports_oi_research_preset():
    bw = _resolve_bridgewater_module()

    research = _resolve_variant_runtime(
        bw,
        preset="oi_research",
        disable_oi=False,
        strict_direction=False,
        min_components=0,
        min_dir_thresh=None,
        enable_symbol_health=False,
        allowed_regimes=None,
        post_trade_cooldown_bars=0,
    )

    assert research["preset"] == "oi_research"
    assert research["disable_oi"] is False
    assert research["allowed_macro_regimes"] == {"BEAR", "CHOP"}
    assert research["min_coverage_fraction"] == 0.85
