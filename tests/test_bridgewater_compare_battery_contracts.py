from tools.bridgewater_compare_battery import _aggregate_bucket, _variant_sentiment


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
