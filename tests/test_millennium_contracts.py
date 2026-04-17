from datetime import datetime, timedelta

from engines import millennium


def _trade(ts, strategy, pnl, result="WIN"):
    return {
        "timestamp": ts,
        "strategy": strategy,
        "pnl": pnl,
        "entry": 100.0,
        "stop": 99.0,
        "size": 10.0,
        "result": result,
        "macro_bias": "CHOP",
    }


def test_regime_boost_covers_operational_core():
    recent = [
        {"macro_bias": "BULL"},
        {"macro_bias": "BEAR"},
        {"macro_bias": "CHOP"},
    ]
    boost, dominant = millennium._regime_confidence_boost(recent)
    assert dominant in {"BULL", "BEAR", "CHOP"}
    assert set(millennium.OPERATIONAL_ENGINES).issubset(boost.keys())


def test_operational_core_reweight_preserves_strategy_specific_base_weight():
    ts = datetime(2026, 1, 1)
    trades = [
        _trade(ts + timedelta(minutes=15 * i), "CITADEL", 50.0)
        for i in range(3)
    ] + [
        _trade(ts + timedelta(minutes=15 * (i + 3)), "RENAISSANCE", 40.0)
        for i in range(3)
    ] + [
        _trade(ts + timedelta(minutes=15 * (i + 6)), "JUMP", 30.0)
        for i in range(3)
    ]

    out = millennium.operational_core_reweight(trades)
    jump_trade = next(t for t in out if t["strategy"] == "JUMP")
    renaissance_trade = next(t for t in out if t["strategy"] == "RENAISSANCE")

    assert "ensemble_weights" in jump_trade
    assert set(millennium.OPERATIONAL_ENGINES).issubset(jump_trade["ensemble_weights"].keys())
    expected_jump = round(
        jump_trade["pnl_pre_ensemble"]
        * (jump_trade["ensemble_w"] / millennium.BASE_CAPITAL_WEIGHTS["JUMP"]),
        2,
    )
    expected_renaissance = round(
        renaissance_trade["pnl_pre_ensemble"]
        * (renaissance_trade["ensemble_w"] / millennium.BASE_CAPITAL_WEIGHTS["RENAISSANCE"]),
        2,
    )
    assert abs(jump_trade["pnl"] - expected_jump) <= 0.05
    assert abs(renaissance_trade["pnl"] - expected_renaissance) <= 0.05


def test_engine_weight_caps_limit_dominance():
    # Test that no single engine can exceed its cap. JUMP set artificially
    # high to check cap binding (replaces BRIDGEWATER after 2026-04-17 removal).
    capped = millennium._apply_engine_weight_caps(
        {
            "CITADEL": 0.05,
            "RENAISSANCE": 0.10,
            "JUMP": 0.85,
        },
        list(millennium.OPERATIONAL_ENGINES),
    )
    assert capped["JUMP"] <= millennium.ENGINE_WEIGHT_CAPS["JUMP"] + 1e-9
    assert capped["CITADEL"] >= millennium.ENGINE_WEIGHT_FLOORS["CITADEL"] - 1e-9


def test_recent_drawdown_penalty_soft_caps_stressed_engine():
    r_hist = [-1.2, 0.3, -1.0, 0.2, -0.9, 0.1, -0.8, 0.1, -0.7, 0.1]
    penalty, mdd_r = millennium._recent_drawdown_penalty(r_hist)
    assert mdd_r > millennium.ENGINE_DRAWDOWN_WARN_R
    assert millennium.ENGINE_DRAWDOWN_MIN_FACTOR <= penalty < 1.0


def test_capital_weights_reflect_2026_04_17_calibration():
    # 2026-04-17 (pós remoção BRIDGEWATER): 3 engines operacionais.
    # JUMP e RENAISSANCE devem liderar (edge validado); CITADEL leve (decay).
    assert millennium.BASE_CAPITAL_WEIGHTS["JUMP"] > millennium.BASE_CAPITAL_WEIGHTS["CITADEL"]
    assert millennium.BASE_CAPITAL_WEIGHTS["RENAISSANCE"] > millennium.BASE_CAPITAL_WEIGHTS["CITADEL"]
    # CITADEL cap continua contido (edge decay)
    assert millennium.ENGINE_WEIGHT_CAPS["CITADEL"] <= 0.30
    # JUMP e RENAISSANCE ganham caps maiores pós-redistribuição
    assert millennium.ENGINE_WEIGHT_CAPS["JUMP"] >= 0.40
    assert millennium.ENGINE_WEIGHT_CAPS["RENAISSANCE"] >= 0.40
    # BRIDGEWATER removida — NÃO deve aparecer em OPERATIONAL_ENGINES
    assert "BRIDGEWATER" not in millennium.OPERATIONAL_ENGINES
    # Base weights somam 1.0
    assert abs(sum(millennium.BASE_CAPITAL_WEIGHTS.values()) - 1.0) < 1e-9


def test_chop_regime_reduces_renaissance_weight_vs_bull():
    """Gate CHOP deve reduzir RENAISSANCE (colapsa em CHOP OOS 2019)."""
    ts = datetime(2026, 1, 1)
    # Mesmo cenário em dois regimes diferentes — 3 engines ativos
    def _build(regime):
        trades = []
        for i in range(20):
            for eng in ["CITADEL", "RENAISSANCE", "JUMP"]:
                t = _trade(ts + timedelta(minutes=15 * (i * 3 + {"CITADEL":0,"RENAISSANCE":1,"JUMP":2}[eng])),
                           eng, 10.0)
                t["macro_bias"] = regime
                trades.append(t)
        return trades

    chop_out = millennium.operational_core_reweight(_build("CHOP"))
    bull_out = millennium.operational_core_reweight(_build("BULL"))

    chop_renai_last = next(t for t in reversed(chop_out) if t["strategy"] == "RENAISSANCE")
    bull_renai_last = next(t for t in reversed(bull_out) if t["strategy"] == "RENAISSANCE")

    # Em CHOP, RENAISSANCE deve ficar com peso estritamente menor que em BULL
    # (gate CHOP força ENSEMBLE_MIN_W antes de normalizar/cap)
    assert chop_renai_last["ensemble_weights"]["RENAISSANCE"] < bull_renai_last["ensemble_weights"]["RENAISSANCE"]
