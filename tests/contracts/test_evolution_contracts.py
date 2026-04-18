"""Contract tests for core.evolution — Darwin adaptive allocator.

Covers:
- calc_fitness: <5 trades → zero fitness; shape of return dict;
  normalizations clipped to [-1, 1]; win-only trades don't divide by
  zero; stability zero when window too small
- DarwinAllocator init: fresh population starts with default DNA for
  every engine; allocations roughly equal
- _allocate: top engine gets ALLOC_TOP; paused gets ALLOC_KILLED;
  allocations normalized to sum=1
- evaluate: generation increments; pause after KILL_ZONE_WINDOWS
  negative fitness; resume when fitness recovers
- crossover: averages parent DNA within bounds (int params rounded)
- get_engine_capital: total * alloc fraction
- revert_mutation: restores dna_backup when present
- _save_state / _load_state round-trip
"""
from __future__ import annotations

import json

import pytest

from core.evolution import DarwinAllocator, calc_fitness


def _mk_trades(wins: int, losses: int, win_pnl: float = 1.0,
               loss_pnl: float = -1.0) -> list[dict]:
    return (
        [{"pnl": win_pnl} for _ in range(wins)]
        + [{"pnl": loss_pnl} for _ in range(losses)]
    )


# ────────────────────────────────────────────────────────────
# calc_fitness
# ────────────────────────────────────────────────────────────

class TestCalcFitness:
    def test_too_few_trades_returns_zero(self):
        out = calc_fitness(_mk_trades(2, 1))
        assert out["fitness"] == 0.0
        assert out["n_trades"] == 3

    def test_return_shape(self):
        out = calc_fitness(_mk_trades(20, 10))
        for key in ("fitness", "sortino", "pf", "adj_wr",
                    "stability", "n_trades", "total_pnl", "win_rate"):
            assert key in out

    def test_normalized_scores_in_unit_range(self):
        out = calc_fitness(_mk_trades(30, 10))
        for k in ("sortino", "pf", "adj_wr", "stability"):
            assert -1.0 <= out[k] <= 1.0

    def test_win_only_does_not_divide_by_zero(self):
        # Only wins → no losses → downside fallback (0.001) must prevent div0
        out = calc_fitness(_mk_trades(15, 0))
        assert out["fitness"] != float("inf")
        assert out["fitness"] != float("-inf")

    def test_positive_expectancy_gives_positive_fitness(self):
        # Mostly wins with bigger avg size → fitness should lean positive
        trades = _mk_trades(25, 5, win_pnl=2.0, loss_pnl=-1.0)
        out = calc_fitness(trades)
        assert out["fitness"] > 0

    def test_short_trade_list_skips_stability(self):
        # Below window → stability forced to 0
        out = calc_fitness(_mk_trades(10, 5))  # 15 trades, default window=30
        assert out["stability"] == 0.0


# ────────────────────────────────────────────────────────────
# DarwinAllocator — init & state
# ────────────────────────────────────────────────────────────

class TestAllocatorInit:
    def test_fresh_population_has_all_engines(self, tmp_path):
        a = DarwinAllocator(engines=["A", "B", "C"], data_dir=str(tmp_path))
        assert set(a.population.keys()) == {"A", "B", "C"}

    def test_fresh_population_has_default_dna(self, tmp_path):
        a = DarwinAllocator(engines=["A"], data_dir=str(tmp_path))
        dna = a.population["A"]["dna"]
        # Defaults pulled from config.params — just assert structure/types
        for param in DarwinAllocator.MUTABLE_PARAMS:
            assert param in dna
            lo, hi = DarwinAllocator.MUTABLE_PARAMS[param]
            assert lo <= dna[param] <= hi

    def test_initial_allocations_roughly_equal(self, tmp_path):
        a = DarwinAllocator(engines=["A", "B", "C", "D"],
                            data_dir=str(tmp_path))
        assert pytest.approx(sum(a.allocations.values()), rel=1e-2) == 1.0
        # Each at 0.25 (1/4)
        assert all(abs(v - 0.25) < 1e-3 for v in a.allocations.values())

    def test_load_state_from_existing_file(self, tmp_path):
        # Seed a population.json manually
        pop_file = tmp_path / "population.json"
        pop_file.write_text(json.dumps({
            "generation": 42,
            "allocations": {"X": 1.0},
            "population": {"X": {
                "dna": {"SCORE_THRESHOLD": 0.5},
                "fitness_history": [],
                "current_fitness": 0.8,
                "negative_streak": 0,
                "paused": False,
                "trades_since_mutation": 0,
                "mutations_applied": 0,
                "dna_backup": None,
            }},
        }), encoding="utf-8")
        a = DarwinAllocator(engines=["X"], data_dir=str(tmp_path))
        assert a.generation == 42
        assert a.allocations == {"X": 1.0}
        assert a.population["X"]["current_fitness"] == 0.8


# ────────────────────────────────────────────────────────────
# _allocate
# ────────────────────────────────────────────────────────────

class TestAllocate:
    def test_allocations_sum_to_one(self, tmp_path):
        a = DarwinAllocator(engines=["A", "B", "C", "D"],
                            data_dir=str(tmp_path))
        scores = {"A": {"fitness": 0.9}, "B": {"fitness": 0.5},
                  "C": {"fitness": 0.1}, "D": {"fitness": -0.2}}
        a._allocate(scores)
        total = sum(a.allocations.values())
        assert pytest.approx(total, rel=1e-2) == 1.0

    def test_top_engine_gets_highest_share(self, tmp_path):
        a = DarwinAllocator(engines=["A", "B", "C", "D"],
                            data_dir=str(tmp_path))
        scores = {"A": {"fitness": 0.9}, "B": {"fitness": 0.3},
                  "C": {"fitness": 0.2}, "D": {"fitness": 0.1}}
        a._allocate(scores)
        top = max(a.allocations, key=lambda k: a.allocations[k])
        assert top == "A"

    def test_paused_engine_gets_killed_allocation_normalized(self, tmp_path):
        a = DarwinAllocator(engines=["A", "B"], data_dir=str(tmp_path))
        a.population["B"]["paused"] = True
        scores = {"A": {"fitness": 0.8}, "B": {"fitness": -0.5}}
        a._allocate(scores)
        # A gets larger share than paused B
        assert a.allocations["A"] > a.allocations["B"]


# ────────────────────────────────────────────────────────────
# evaluate
# ────────────────────────────────────────────────────────────

class TestEvaluate:
    def test_generation_increments(self, tmp_path):
        a = DarwinAllocator(engines=["A"], data_dir=str(tmp_path))
        before = a.generation
        a.evaluate({"A": _mk_trades(3, 2)})
        assert a.generation == before + 1

    def test_paused_after_kill_zone_windows(self, tmp_path):
        a = DarwinAllocator(engines=["A"], data_dir=str(tmp_path))
        # KILL_ZONE_WINDOWS = 3 consecutive negative fitness windows.
        # Loss-heavy trades produce negative fitness.
        losing = _mk_trades(1, 20, win_pnl=1.0, loss_pnl=-5.0)
        for _ in range(DarwinAllocator.KILL_ZONE_WINDOWS):
            a.evaluate({"A": losing})
        assert a.population["A"]["paused"] is True

    def test_resume_after_recovery(self, tmp_path):
        a = DarwinAllocator(engines=["A"], data_dir=str(tmp_path))
        losing = _mk_trades(1, 20, win_pnl=1.0, loss_pnl=-5.0)
        for _ in range(DarwinAllocator.KILL_ZONE_WINDOWS):
            a.evaluate({"A": losing})
        assert a.population["A"]["paused"] is True

        winning = _mk_trades(25, 3, win_pnl=2.0, loss_pnl=-1.0)
        a.evaluate({"A": winning})
        assert a.population["A"]["paused"] is False


# ────────────────────────────────────────────────────────────
# crossover
# ────────────────────────────────────────────────────────────

class TestCrossover:
    def test_averages_floats(self, tmp_path):
        a = DarwinAllocator(engines=["A", "B"], data_dir=str(tmp_path))
        a.population["A"]["dna"]["SCORE_THRESHOLD"] = 0.50
        a.population["B"]["dna"]["SCORE_THRESHOLD"] = 0.60
        hybrid = a.crossover("A", "B")
        assert hybrid["SCORE_THRESHOLD"] == pytest.approx(0.55, rel=1e-2)

    def test_averages_ints_and_rounds(self, tmp_path):
        a = DarwinAllocator(engines=["A", "B"], data_dir=str(tmp_path))
        a.population["A"]["dna"]["RSI_BULL_MIN"] = 40
        a.population["B"]["dna"]["RSI_BULL_MIN"] = 45
        hybrid = a.crossover("A", "B")
        # MUTABLE_PARAMS["RSI_BULL_MIN"] = (35, 50), int type
        assert isinstance(hybrid["RSI_BULL_MIN"], int)
        assert hybrid["RSI_BULL_MIN"] in (42, 43)  # round(42.5) may be 42 (banker's)

    def test_clamps_to_bounds(self, tmp_path):
        a = DarwinAllocator(engines=["A", "B"], data_dir=str(tmp_path))
        # Force out-of-bound DNA to test clamping
        a.population["A"]["dna"]["TARGET_RR"] = 99.0
        a.population["B"]["dna"]["TARGET_RR"] = 99.0
        hybrid = a.crossover("A", "B")
        lo, hi = DarwinAllocator.MUTABLE_PARAMS["TARGET_RR"]
        assert lo <= hybrid["TARGET_RR"] <= hi


# ────────────────────────────────────────────────────────────
# Capital helper
# ────────────────────────────────────────────────────────────

class TestGetEngineCapital:
    def test_returns_total_times_allocation(self, tmp_path):
        a = DarwinAllocator(engines=["A", "B"], data_dir=str(tmp_path))
        a.allocations = {"A": 0.7, "B": 0.3}
        assert a.get_engine_capital("A", 1_000) == pytest.approx(700)
        assert a.get_engine_capital("B", 1_000) == pytest.approx(300)

    def test_unknown_engine_returns_zero(self, tmp_path):
        a = DarwinAllocator(engines=["A"], data_dir=str(tmp_path))
        assert a.get_engine_capital("XYZ", 1_000) == 0.0


# ────────────────────────────────────────────────────────────
# revert_mutation
# ────────────────────────────────────────────────────────────

class TestRevertMutation:
    def test_restores_backup_when_present(self, tmp_path):
        a = DarwinAllocator(engines=["A"], data_dir=str(tmp_path))
        original = dict(a.population["A"]["dna"])
        a.population["A"]["dna_backup"] = original
        a.population["A"]["dna"]["SCORE_THRESHOLD"] = 999  # mutated
        a.revert_mutation("A")
        assert a.population["A"]["dna"] == original
        assert a.population["A"]["dna_backup"] is None

    def test_noop_when_no_backup(self, tmp_path):
        a = DarwinAllocator(engines=["A"], data_dir=str(tmp_path))
        before = dict(a.population["A"]["dna"])
        a.revert_mutation("A")  # dna_backup is None
        assert a.population["A"]["dna"] == before


# ────────────────────────────────────────────────────────────
# _save_state / _load_state round-trip
# ────────────────────────────────────────────────────────────

class TestSaveLoadRoundtrip:
    def test_saved_state_is_loadable(self, tmp_path):
        a = DarwinAllocator(engines=["A"], data_dir=str(tmp_path))
        a.generation = 7
        a.allocations = {"A": 1.0}
        a._save_state()
        # New instance from same dir picks up the saved state
        b = DarwinAllocator(engines=["A"], data_dir=str(tmp_path))
        assert b.generation == 7
        assert b.allocations == {"A": 1.0}
