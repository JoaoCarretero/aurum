from __future__ import annotations

from tools.maintenance.millennium_live_tuner import _diversity_bonus, _score


def test_score_penalizes_drawdown_and_trade_frequency():
    low_quality = {
        "sharpe": 0.5,
        "roi_pct": 2.0,
        "max_dd_pct": 10.0,
        "n_trades": 40,
    }
    high_quality = {
        "sharpe": 1.5,
        "roi_pct": 8.0,
        "max_dd_pct": 3.0,
        "n_trades": 10,
    }

    assert _score(high_quality, days=30) > _score(low_quality, days=30)


def test_diversity_bonus_rewards_multi_strategy_mix():
    narrow = [{"result": "WIN", "strategy": "CITADEL"} for _ in range(20)]
    mixed = (
        [{"result": "WIN", "strategy": "CITADEL"} for _ in range(5)]
        + [{"result": "LOSS", "strategy": "JUMP"} for _ in range(5)]
        + [{"result": "WIN", "strategy": "RENAISSANCE"} for _ in range(5)]
    )

    assert _diversity_bonus(mixed) > _diversity_bonus(narrow)


def test_diversity_bonus_penalizes_no_closed_trades():
    assert _diversity_bonus([]) == -4.0
