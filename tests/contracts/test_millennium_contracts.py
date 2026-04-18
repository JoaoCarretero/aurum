from datetime import datetime, timedelta

import pandas as pd

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
    millennium.PORTFOLIO_EXECUTION_ENABLED = False
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
    millennium.PORTFOLIO_EXECUTION_ENABLED = False
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
    millennium.PORTFOLIO_EXECUTION_ENABLED = False
    r_hist = [-1.2, 0.3, -1.0, 0.2, -0.9, 0.1, -0.8, 0.1, -0.7, 0.1]
    penalty, mdd_r = millennium._recent_drawdown_penalty(r_hist)
    assert mdd_r > millennium.ENGINE_DRAWDOWN_WARN_R
    assert millennium.ENGINE_DRAWDOWN_MIN_FACTOR <= penalty < 1.0


def test_capital_weights_reflect_2026_04_17_calibration():
    millennium.PORTFOLIO_EXECUTION_ENABLED = False
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
    millennium.PORTFOLIO_EXECUTION_ENABLED = False
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


def test_execution_gate_blocks_subscale_strategy(monkeypatch):
    ts = datetime(2026, 1, 1)
    trades = [
        _trade(ts, "CITADEL", 10.0),
        _trade(ts + timedelta(minutes=15), "RENAISSANCE", 10.0),
        _trade(ts + timedelta(minutes=30), "JUMP", 10.0),
    ]
    monkeypatch.setattr(millennium, "PORTFOLIO_EXECUTION_ENABLED", True)
    monkeypatch.setattr(millennium, "PORTFOLIO_MIN_WEIGHT", {
        "CITADEL": 0.30,
        "RENAISSANCE": 0.0,
        "JUMP": 0.0,
    })
    monkeypatch.setattr(millennium, "PORTFOLIO_CHALLENGER_RATIO", 0.0)
    monkeypatch.setattr(millennium, "PORTFOLIO_CHALLENGER_MAX_GAP", 1.0)
    monkeypatch.setattr(millennium, "PORTFOLIO_GLOBAL_COOLDOWN_BARS", 0)
    monkeypatch.setattr(millennium, "PORTFOLIO_STRATEGY_COOLDOWN_BARS", {
        "CITADEL": 0, "RENAISSANCE": 0, "JUMP": 0,
    })

    out = millennium.operational_core_reweight(trades)
    assert all(t["strategy"] != "CITADEL" for t in out)
    assert any(t["strategy"] == "RENAISSANCE" for t in out)


def test_execution_gate_global_cooldown_reduces_cluster(monkeypatch):
    ts = datetime(2026, 1, 1)
    trades = [
        _trade(ts, "JUMP", 10.0),
        _trade(ts + timedelta(minutes=15), "JUMP", 10.0),
        _trade(ts + timedelta(minutes=30), "JUMP", 10.0),
    ]
    monkeypatch.setattr(millennium, "PORTFOLIO_EXECUTION_ENABLED", True)
    monkeypatch.setattr(millennium, "PORTFOLIO_MIN_WEIGHT", {"JUMP": 0.0})
    monkeypatch.setattr(millennium, "PORTFOLIO_CHALLENGER_RATIO", 0.0)
    monkeypatch.setattr(millennium, "PORTFOLIO_CHALLENGER_MAX_GAP", 1.0)
    monkeypatch.setattr(millennium, "PORTFOLIO_GLOBAL_COOLDOWN_BARS", 2)
    monkeypatch.setattr(millennium, "PORTFOLIO_REGIME_COOLDOWN_MULT", {
        "BULL": 1.0, "BEAR": 1.0, "CHOP": 1.0,
    })
    monkeypatch.setattr(millennium, "PORTFOLIO_STRATEGY_COOLDOWN_BARS", {"JUMP": 0})
    monkeypatch.setattr(millennium, "JUMP_MIN_SCORE_BASE", 0.0)
    monkeypatch.setattr(millennium, "JUMP_MIN_SCORE_WEAK", 0.0)
    monkeypatch.setattr(millennium, "JUMP_MIN_SCORE_STRESSED", 0.0)

    out = millennium.operational_core_reweight(trades)
    assert len(out) == 2
    stats = out[-1]["_portfolio_gate_stats"]
    assert stats["blocked"]["portfolio_cooldown"] == 1


def test_execution_gate_diversity_override_reintroduces_underrepresented_engine(monkeypatch):
    ts = datetime(2026, 1, 1)
    trades = []
    for i in range(15):
        trades.append(_trade(ts + timedelta(minutes=15 * i), "JUMP", 10.0))
    late_cit = _trade(ts + timedelta(minutes=15 * 20), "CITADEL", 10.0)
    trades.append(late_cit)

    monkeypatch.setattr(millennium, "PORTFOLIO_EXECUTION_ENABLED", True)
    monkeypatch.setattr(millennium, "PORTFOLIO_MIN_WEIGHT", {
        "JUMP": 0.0, "RENAISSANCE": 0.0, "CITADEL": 0.0,
    })
    monkeypatch.setattr(millennium, "PORTFOLIO_CHALLENGER_RATIO", 0.99)
    monkeypatch.setattr(millennium, "PORTFOLIO_CHALLENGER_MAX_GAP", 0.0)
    monkeypatch.setattr(millennium, "PORTFOLIO_GLOBAL_COOLDOWN_BARS", 0)
    monkeypatch.setattr(millennium, "PORTFOLIO_STRATEGY_COOLDOWN_BARS", {
        "JUMP": 0, "RENAISSANCE": 0, "CITADEL": 0,
    })
    monkeypatch.setattr(millennium, "PORTFOLIO_MIN_ACCEPTED_SHARE", {
        "CITADEL": 0.10, "RENAISSANCE": 0.0, "JUMP": 0.0,
    })
    monkeypatch.setattr(millennium, "JUMP_MIN_SCORE_BASE", 0.0)
    monkeypatch.setattr(millennium, "JUMP_MIN_SCORE_WEAK", 0.0)
    monkeypatch.setattr(millennium, "JUMP_MIN_SCORE_STRESSED", 0.0)

    out = millennium.operational_core_reweight(trades)
    cit = next(t for t in out if t["strategy"] == "CITADEL")
    assert cit["portfolio_gate"] == "diversity_override"


def test_jump_quality_floor_blocks_weak_recent_jump(monkeypatch):
    ts = datetime(2026, 1, 1)
    trades = []
    for i in range(35):
        t = _trade(ts + timedelta(minutes=15 * i), "JUMP", -10.0, result="LOSS")
        t["score"] = 0.81
        trades.append(t)

    monkeypatch.setattr(millennium, "PORTFOLIO_EXECUTION_ENABLED", True)
    monkeypatch.setattr(millennium, "PORTFOLIO_MIN_WEIGHT", {
        "JUMP": 0.0, "RENAISSANCE": 0.0, "CITADEL": 0.0,
    })
    monkeypatch.setattr(millennium, "PORTFOLIO_CHALLENGER_RATIO", 0.0)
    monkeypatch.setattr(millennium, "PORTFOLIO_CHALLENGER_MAX_GAP", 1.0)
    monkeypatch.setattr(millennium, "PORTFOLIO_GLOBAL_COOLDOWN_BARS", 0)
    monkeypatch.setattr(millennium, "PORTFOLIO_STRATEGY_COOLDOWN_BARS", {"JUMP": 0})

    out = millennium.operational_core_reweight(trades)
    assert len(out) < len(trades)
    stats = out[-1]["_portfolio_gate_stats"]
    assert stats["blocked"]["jump_quality_floor"] > 0


def test_collect_operational_trades_uses_engine_native_contexts(monkeypatch):
    seen = {}

    def _fake_scan_azoth(all_dfs, *_args, **_kwargs):
        seen["CITADEL"] = sorted(all_dfs.keys())
        return ([{"timestamp": datetime(2026, 1, 1), "strategy": "CITADEL", "pnl": 1.0, "entry": 1.0, "stop": 0.9, "size": 1.0, "result": "WIN"}], {})

    def _fake_scan_hermes(all_dfs, *_args, **_kwargs):
        seen["RENAISSANCE"] = sorted(all_dfs.keys())
        return ([{"timestamp": datetime(2026, 1, 1, 0, 15), "strategy": "RENAISSANCE", "pnl": 1.0, "entry": 1.0, "stop": 0.9, "size": 1.0, "result": "WIN"}], {})

    def _fake_scan_mercurio(df, sym, *_args, **_kwargs):
        seen.setdefault("JUMP", []).append(sym)
        return ([{"timestamp": datetime(2026, 1, 1, 0, 30), "strategy": "JUMP", "symbol": sym, "pnl": 1.0, "entry": 1.0, "stop": 0.9, "size": 1.0, "result": "WIN"}], {})

    monkeypatch.setattr(millennium, "_scan_azoth", _fake_scan_azoth)
    monkeypatch.setattr(millennium, "_scan_hermes_all", _fake_scan_hermes)
    import engines.jump as jump
    monkeypatch.setattr(jump, "scan_mercurio", _fake_scan_mercurio)

    engine_contexts = {
        "CITADEL": {"all_dfs": {"BTCUSDT": pd.DataFrame({"x": [1]})}, "htf_stack_by_sym": {}, "macro_series": None, "corr": {}},
        "RENAISSANCE": {"all_dfs": {"ETHUSDT": pd.DataFrame({"x": [1]})}, "htf_stack_by_sym": {}, "macro_series": None, "corr": {}},
        "JUMP": {"all_dfs": {"SOLUSDT": pd.DataFrame({"x": [1]})}, "htf_stack_by_sym": {}, "macro_series": None, "corr": {}},
    }

    engine_trades, all_trades = millennium._collect_operational_trades(engine_contexts=engine_contexts)

    assert seen["CITADEL"] == ["BTCUSDT"]
    assert seen["RENAISSANCE"] == ["ETHUSDT"]
    assert seen["JUMP"] == ["SOLUSDT"]
    assert set(engine_trades.keys()) == set(millennium.OPERATIONAL_ENGINES)
    assert len(all_trades) == 3
