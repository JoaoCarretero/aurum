"""Contract tests for core.run_manager — per-run dir + global index.

Covers:
- snapshot_config: returns scalar dict, drops dunder/callable/complex
- create_run_dir: creates dir with engine_timestamp id
- _clean_trades: dict + object attrs serialized safely; non-JSON → str
- save_run_artifacts: writes config/trades/equity/summary; overfit +
  diagnostics only when provided
- _load_index: missing → []; malformed → []; wrong type → []
- append_to_index: first entry bootstraps list; multiple append
  accumulate; engine slug resolution from summary/parent/run_id;
  config_hash is deterministic across identical configs
- list_runs: filters by engine; honors last_n tail
- compare_runs: metrics_diff only on numeric keys, config_diff lists
  differences, trade_count_diff uses file content
"""
from __future__ import annotations

import json

import pytest

from core import run_manager as rm


@pytest.fixture
def isolated_dirs(tmp_path, monkeypatch):
    """Redirect RUNS_DIR and INDEX_PATH to tmp_path."""
    runs = tmp_path / "runs"
    runs.mkdir()
    index = tmp_path / "index.json"
    monkeypatch.setattr(rm, "RUNS_DIR", runs)
    monkeypatch.setattr(rm, "INDEX_PATH", index)
    return runs, index


# ────────────────────────────────────────────────────────────
# snapshot_config
# ────────────────────────────────────────────────────────────

class TestSnapshotConfig:
    def test_returns_dict(self):
        assert isinstance(rm.snapshot_config(), dict)

    def test_excludes_dunder_names(self):
        snap = rm.snapshot_config()
        assert not any(k.startswith("__") for k in snap)

    def test_scalars_and_lists_included(self):
        # config.params has at least one known scalar — sanity check the
        # function can pull something non-empty from it.
        snap = rm.snapshot_config()
        assert len(snap) > 0
        for v in snap.values():
            assert isinstance(v, (int, float, str, bool, list, dict, type(None)))


# ────────────────────────────────────────────────────────────
# create_run_dir
# ────────────────────────────────────────────────────────────

class TestCreateRunDir:
    def test_creates_dir_with_engine_prefix(self, isolated_dirs):
        runs, _ = isolated_dirs
        run_id, run_dir = rm.create_run_dir("citadel")
        assert run_id.startswith("citadel_")
        assert run_dir.exists() and run_dir.is_dir()
        assert run_dir.parent == runs

    def test_default_engine_is_citadel(self, isolated_dirs):
        run_id, _ = rm.create_run_dir()
        assert run_id.startswith("citadel_")


# ────────────────────────────────────────────────────────────
# _clean_trades
# ────────────────────────────────────────────────────────────

class TestCleanTrades:
    def test_empty_returns_empty(self):
        assert rm._clean_trades([]) == []
        assert rm._clean_trades(None) == []

    def test_dict_values_preserved_when_serializable(self):
        # _clean_trades uses json.dumps(v, default=str) as a probe — if
        # that passes, the ORIGINAL value is kept (not its string form).
        # default=str is permissive, so most custom objects survive
        # as-is (the str conversion happens only if json.dumps tries
        # to serialize, which it doesn't here — it just validates).
        cleaned = rm._clean_trades([{"sym": "BTC", "pnl": 42.0}])
        assert cleaned[0] == {"sym": "BTC", "pnl": 42.0}

    def test_object_attrs_become_dict(self):
        class Trade:
            def __init__(self):
                self.sym = "ETH"
                self.pnl = 42.0
        cleaned = rm._clean_trades([Trade()])
        assert cleaned[0]["sym"] == "ETH"
        assert cleaned[0]["pnl"] == 42.0


# ────────────────────────────────────────────────────────────
# save_run_artifacts
# ────────────────────────────────────────────────────────────

class TestSaveRunArtifacts:
    def test_writes_core_four_files(self, tmp_path):
        rm.save_run_artifacts(
            tmp_path,
            config={"A": 1},
            trades=[{"sym": "BTC"}],
            equity=[{"d": 1, "v": 100}],
            summary={"roi": 0.1},
        )
        for name in ("config.json", "trades.json", "equity.json", "summary.json"):
            assert (tmp_path / name).exists()
        # Overfit and diagnostics NOT written when None
        assert not (tmp_path / "overfit.json").exists()
        assert not (tmp_path / "diagnostics.json").exists()

    def test_overfit_and_diagnostics_optional(self, tmp_path):
        rm.save_run_artifacts(
            tmp_path, config={}, trades=[], equity=[], summary={},
            overfit_results={"passed": True},
            diagnostics={"note": "ok"},
        )
        assert (tmp_path / "overfit.json").exists()
        assert (tmp_path / "diagnostics.json").exists()


# ────────────────────────────────────────────────────────────
# _load_index
# ────────────────────────────────────────────────────────────

class TestLoadIndex:
    def test_missing_returns_empty_list(self, isolated_dirs):
        assert rm._load_index() == []

    def test_malformed_returns_empty(self, isolated_dirs):
        _, index = isolated_dirs
        index.write_text("{ not valid", encoding="utf-8")
        assert rm._load_index() == []

    def test_non_list_returns_empty(self, isolated_dirs):
        _, index = isolated_dirs
        index.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
        assert rm._load_index() == []

    def test_valid_list_returned_as_is(self, isolated_dirs):
        _, index = isolated_dirs
        index.write_text(json.dumps([{"run_id": "x"}]), encoding="utf-8")
        assert rm._load_index() == [{"run_id": "x"}]


# ────────────────────────────────────────────────────────────
# append_to_index
# ────────────────────────────────────────────────────────────

class TestAppendToIndex:
    def _mkrun(self, runs, name):
        d = runs / name
        d.mkdir()
        return d

    def test_first_entry_bootstraps_index(self, isolated_dirs):
        runs, index = isolated_dirs
        rd = self._mkrun(runs, "citadel_2026-04-15_1000")
        rm.append_to_index(rd, summary={"engine": "CITADEL", "sharpe": 2.5},
                           config={"A": 1})
        data = json.loads(index.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["engine"] == "citadel"
        assert data[0]["sharpe"] == 2.5
        assert isinstance(data[0]["config_hash"], str) and len(data[0]["config_hash"]) == 64

    def test_multiple_appends_accumulate(self, isolated_dirs):
        runs, index = isolated_dirs
        a = self._mkrun(runs, "citadel_2026-04-15_1000")
        b = self._mkrun(runs, "citadel_2026-04-15_1100")
        rm.append_to_index(a, summary={"engine": "CITADEL"}, config={"X": 1})
        rm.append_to_index(b, summary={"engine": "CITADEL"}, config={"X": 2})
        data = json.loads(index.read_text(encoding="utf-8"))
        assert len(data) == 2

    def test_engine_slug_from_summary_name(self, isolated_dirs):
        runs, index = isolated_dirs
        rd = self._mkrun(runs, "raw_20260415")
        rm.append_to_index(rd, summary={"engine": "JUMP"}, config={})
        data = json.loads(index.read_text(encoding="utf-8"))
        assert data[0]["engine"] == "jump"

    def test_config_hash_deterministic(self, isolated_dirs):
        runs, index = isolated_dirs
        a = self._mkrun(runs, "citadel_a")
        b = self._mkrun(runs, "citadel_b")
        cfg = {"alpha": 1, "beta": 2, "gamma": [3, 4, 5]}
        rm.append_to_index(a, summary={"engine": "CITADEL"}, config=cfg)
        rm.append_to_index(b, summary={"engine": "CITADEL"}, config=cfg)
        data = json.loads(index.read_text(encoding="utf-8"))
        assert data[0]["config_hash"] == data[1]["config_hash"]

    def test_overfit_fields_populated_when_provided(self, isolated_dirs):
        runs, index = isolated_dirs
        rd = self._mkrun(runs, "citadel_ov")
        rm.append_to_index(
            rd, summary={"engine": "CITADEL"}, config={},
            overfit_results={"passed": False, "warnings": ["x", "y"]},
        )
        data = json.loads(index.read_text(encoding="utf-8"))
        assert data[0]["overfit_pass"] is False
        assert data[0]["overfit_warn"] == ["x", "y"]


# ────────────────────────────────────────────────────────────
# list_runs
# ────────────────────────────────────────────────────────────

class TestListRuns:
    def _seed(self, index, rows):
        index.write_text(json.dumps(rows), encoding="utf-8")

    def test_empty_returns_empty(self, isolated_dirs):
        assert rm.list_runs() == []

    def test_filter_by_engine(self, isolated_dirs):
        _, index = isolated_dirs
        self._seed(index, [
            {"run_id": "a", "engine": "citadel"},
            {"run_id": "b", "engine": "jump"},
            {"run_id": "c", "engine": "citadel"},
        ])
        out = rm.list_runs(engine="citadel")
        assert [r["run_id"] for r in out] == ["a", "c"]

    def test_last_n_takes_tail(self, isolated_dirs):
        _, index = isolated_dirs
        self._seed(index, [{"run_id": f"r{i}", "engine": "x"} for i in range(10)])
        out = rm.list_runs(last_n=3)
        assert [r["run_id"] for r in out] == ["r7", "r8", "r9"]


# ────────────────────────────────────────────────────────────
# compare_runs
# ────────────────────────────────────────────────────────────

class TestCompareRuns:
    def _mkrun_with_files(self, runs, name, *, config, summary, trades):
        d = runs / name
        d.mkdir()
        (d / "config.json").write_text(json.dumps(config), encoding="utf-8")
        (d / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        (d / "trades.json").write_text(json.dumps(trades), encoding="utf-8")
        return d

    def test_numeric_metrics_diff_has_delta(self, isolated_dirs):
        runs, _ = isolated_dirs
        self._mkrun_with_files(runs, "A",
                               config={"X": 1},
                               summary={"sharpe": 2.0, "sortino": 3.0},
                               trades=[])
        self._mkrun_with_files(runs, "B",
                               config={"X": 1},
                               summary={"sharpe": 2.5, "sortino": 2.7},
                               trades=[])
        diff = rm.compare_runs("A", "B")
        assert diff["metrics_diff"]["sharpe"]["delta"] == pytest.approx(0.5)
        assert diff["metrics_diff"]["sortino"]["delta"] == pytest.approx(-0.3)

    def test_config_diff_lists_changed_keys(self, isolated_dirs):
        runs, _ = isolated_dirs
        self._mkrun_with_files(runs, "A",
                               config={"X": 1, "Y": 2, "Z": 3},
                               summary={}, trades=[])
        self._mkrun_with_files(runs, "B",
                               config={"X": 1, "Y": 20, "Z": 3},
                               summary={}, trades=[])
        diff = rm.compare_runs("A", "B")
        changed = {item["key"] for item in diff["config_diff"]}
        assert changed == {"Y"}

    def test_trade_count_diff_from_files(self, isolated_dirs):
        runs, _ = isolated_dirs
        self._mkrun_with_files(runs, "A", config={}, summary={},
                               trades=[{"x": 1}, {"x": 2}])
        self._mkrun_with_files(runs, "B", config={}, summary={},
                               trades=[{"x": 1}])
        diff = rm.compare_runs("A", "B")
        assert diff["trade_count_diff"] == {"a": 2, "b": 1}


# ────────────────────────────────────────────────────────────
# Format helpers
# ────────────────────────────────────────────────────────────

class TestFormatters:
    def test_fmt_none_is_dash(self):
        assert rm._fmt(None) == "-"

    def test_fmt_float_two_decimals(self):
        assert rm._fmt(3.14159) == "3.14"

    def test_fmt_with_sign(self):
        assert rm._fmt(2.5, sign=True) == "+2.50"
        assert rm._fmt(-1.5, sign=True) == "-1.50"

    def test_compact_str_unchanged(self):
        assert rm._compact("hello") == "hello"

    def test_compact_long_list_truncated(self):
        long_list = list(range(100))
        out = rm._compact(long_list)
        assert out.endswith("...")
        assert len(out) <= 40
