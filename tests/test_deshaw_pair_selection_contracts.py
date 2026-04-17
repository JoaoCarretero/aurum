from __future__ import annotations

import pandas as pd

from engines import deshaw


def test_find_cointegrated_pairs_rejects_extreme_beta(monkeypatch):
    monkeypatch.setattr(deshaw, "HAS_STATSMODELS", True)
    monkeypatch.setattr(deshaw, "NEWTON_COINT_PVALUE", 0.01)
    monkeypatch.setattr(deshaw, "NEWTON_HALFLIFE_MIN", 5)
    monkeypatch.setattr(deshaw, "NEWTON_HALFLIFE_MAX", 500)
    monkeypatch.setattr(deshaw, "_BETA_MIN", 0.1)
    monkeypatch.setattr(deshaw, "_BETA_MAX", 4.0)
    monkeypatch.setattr(deshaw, "_MAX_REUSE_PER_SYMBOL", 2)

    idx = pd.date_range("2026-01-01", periods=240, freq="1h")
    close = pd.Series(range(240), dtype=float)
    all_dfs = {
        "A": pd.DataFrame({"time": idx, "close": close}),
        "B": pd.DataFrame({"time": idx, "close": close}),
    }

    monkeypatch.setattr(deshaw, "coint", lambda a, b: (-1.0, 0.001, None))

    class _FitCoint:
        params = [0.0, 10.0]

    class _FitHl:
        params = [0.0, -0.01]

    class _SM:
        @staticmethod
        def add_constant(x):
            return x

        class OLS:
            calls = 0

            def __init__(self, a, b):
                pass

            def fit(self):
                type(self).calls += 1
                return _FitCoint() if type(self).calls == 1 else _FitHl()

    monkeypatch.setattr(deshaw, "sm", _SM)

    assert deshaw.find_cointegrated_pairs(all_dfs) == []


def test_symbol_reuse_cap_filters_later_pairs(monkeypatch):
    monkeypatch.setattr(deshaw, "_MAX_REUSE_PER_SYMBOL", 1)
    pairs = [
        {"sym_a": "AAVE", "sym_b": "SOL", "pvalue": 0.001},
        {"sym_a": "AAVE", "sym_b": "DOT", "pvalue": 0.002},
        {"sym_a": "BTC", "sym_b": "ETH", "pvalue": 0.003},
    ]

    selected = []
    usage = {}
    for pair in pairs:
        if usage.get(pair["sym_a"], 0) >= deshaw._MAX_REUSE_PER_SYMBOL:
            continue
        if usage.get(pair["sym_b"], 0) >= deshaw._MAX_REUSE_PER_SYMBOL:
            continue
        selected.append(pair)
        usage[pair["sym_a"]] = usage.get(pair["sym_a"], 0) + 1
        usage[pair["sym_b"]] = usage.get(pair["sym_b"], 0) + 1

    assert selected == [
        {"sym_a": "AAVE", "sym_b": "SOL", "pvalue": 0.001},
        {"sym_a": "BTC", "sym_b": "ETH", "pvalue": 0.003},
    ]


def test_apply_pair_selection_limits_prefers_better_train_payoff(monkeypatch):
    monkeypatch.setattr(deshaw, "_MAX_REUSE_PER_SYMBOL", 1)
    pairs = [
        {"sym_a": "AAVE", "sym_b": "SOL", "pvalue": 0.001, "train_profit_factor": 1.1, "train_pnl": 10.0},
        {"sym_a": "AAVE", "sym_b": "DOT", "pvalue": 0.01, "train_profit_factor": 2.0, "train_pnl": 30.0},
        {"sym_a": "BTC", "sym_b": "ETH", "pvalue": 0.003, "train_profit_factor": 1.2, "train_pnl": 5.0},
    ]

    selected = deshaw._apply_pair_selection_limits(pairs)

    assert selected == [
        {"sym_a": "AAVE", "sym_b": "DOT", "pvalue": 0.01, "train_profit_factor": 2.0, "train_pnl": 30.0},
        {"sym_a": "BTC", "sym_b": "ETH", "pvalue": 0.003, "train_profit_factor": 1.2, "train_pnl": 5.0},
    ]


def test_discover_cointegrated_pairs_over_time_collects_mid_window_pair(monkeypatch):
    idx = pd.date_range("2026-01-01", periods=6, freq="1h")
    all_dfs = {
        "A": pd.DataFrame({"time": idx, "close": [1, 2, 3, 4, 5, 6]}),
        "B": pd.DataFrame({"time": idx, "close": [6, 5, 4, 3, 2, 1]}),
    }

    def _fake_find(sliced, min_obs=200, log_results=True):
        last_a = float(sliced["A"]["close"].iloc[-1])
        if last_a < 5:
            return []
        return [{"sym_a": "A", "sym_b": "B", "pvalue": 0.004, "beta": 1.0, "alpha": 0.0, "half_life": 20.0}]

    monkeypatch.setattr(deshaw, "find_cointegrated_pairs", _fake_find)
    monkeypatch.setattr(deshaw, "_pair_is_tradeable_window", lambda *args, **kwargs: True)
    monkeypatch.setattr(deshaw, "_MAX_REUSE_PER_SYMBOL", 2)
    monkeypatch.setattr(deshaw, "_ROLLING_MIN_SIGHTINGS", 2)

    pairs = deshaw.discover_cointegrated_pairs_over_time(all_dfs, min_obs=3, window_bars=3, step_bars=1)

    assert pairs == [{"sym_a": "A", "sym_b": "B", "pvalue": 0.004, "beta": 1.0, "alpha": 0.0, "half_life": 20.0}]


def test_discover_cointegrated_pairs_over_time_drops_single_sighting(monkeypatch):
    idx = pd.date_range("2026-01-01", periods=5, freq="1h")
    all_dfs = {
        "A": pd.DataFrame({"time": idx, "close": [1, 2, 3, 4, 5]}),
        "B": pd.DataFrame({"time": idx, "close": [5, 4, 3, 2, 1]}),
    }

    def _fake_find(sliced, min_obs=200, log_results=True):
        last_a = float(sliced["A"]["close"].iloc[-1])
        if last_a == 4:
            return [{"sym_a": "A", "sym_b": "B", "pvalue": 0.004, "beta": 1.0, "alpha": 0.0, "half_life": 20.0}]
        return []

    monkeypatch.setattr(deshaw, "find_cointegrated_pairs", _fake_find)
    monkeypatch.setattr(deshaw, "_pair_is_tradeable_window", lambda *args, **kwargs: True)
    monkeypatch.setattr(deshaw, "_MAX_REUSE_PER_SYMBOL", 2)
    monkeypatch.setattr(deshaw, "_ROLLING_MIN_SIGHTINGS", 2)

    pairs = deshaw.discover_cointegrated_pairs_over_time(all_dfs, min_obs=3, window_bars=3, step_bars=1)

    assert pairs == []


def test_discover_cointegrated_pairs_over_time_requires_tradeable_payoff(monkeypatch):
    idx = pd.date_range("2026-01-01", periods=6, freq="1h")
    all_dfs = {
        "A": pd.DataFrame({"time": idx, "close": [1, 2, 3, 4, 5, 6]}),
        "B": pd.DataFrame({"time": idx, "close": [6, 5, 4, 3, 2, 1]}),
    }

    monkeypatch.setattr(
        deshaw,
        "find_cointegrated_pairs",
        lambda sliced, min_obs=200, log_results=True: [
            {"sym_a": "A", "sym_b": "B", "pvalue": 0.004, "beta": 1.0, "alpha": 0.0, "half_life": 20.0}
        ],
    )
    monkeypatch.setattr(deshaw, "_pair_is_tradeable_window", lambda *args, **kwargs: False)
    monkeypatch.setattr(deshaw, "_MAX_REUSE_PER_SYMBOL", 2)
    monkeypatch.setattr(deshaw, "_ROLLING_MIN_SIGHTINGS", 1)

    pairs = deshaw.discover_cointegrated_pairs_over_time(all_dfs, min_obs=3, window_bars=3, step_bars=1)

    assert pairs == []
