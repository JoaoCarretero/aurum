from __future__ import annotations

from types import SimpleNamespace

import tools.anti_overfit_grid as grid
from tools.anti_overfit_grid import (
    ENGINE_SPECS,
    build_windows,
    execute_run,
    render_checklist,
    summarize_results,
)


def test_build_windows_uses_expected_split_lengths():
    spec = ENGINE_SPECS["deshaw"]
    windows = build_windows(spec)

    assert [w.name for w in windows] == ["train", "test", "holdout"]
    assert windows[0].days == 1095
    assert windows[1].days == 366
    assert windows[2].days > 400


def test_bridgewater_uses_recent_coverage_limited_split():
    spec = ENGINE_SPECS["bridgewater"]
    windows = build_windows(spec)

    assert [w.name for w in windows] == ["train", "test", "holdout"]
    assert windows[0].days == 10
    assert windows[1].days == 9
    assert windows[2].days == 10
    assert "BTCUSDT" in (spec.symbols or "")


def test_summarize_results_ranks_by_train_dsr_and_picks_conservative_variant():
    spec = ENGINE_SPECS["kepos"]
    results = {
        "KEP00_baseline": {
            "train": {"sharpe": 1.4, "sortino": 1.8, "max_dd_pct": 8.0, "n_trades": 120, "dsr": 0.97},
            "test": {"sharpe": 1.1, "sortino": 1.3},
            "holdout": {"sharpe": 0.9},
        },
        "KEP01_rsi_looser": {
            "train": {"sharpe": 1.2, "sortino": 1.6, "max_dd_pct": 9.0, "n_trades": 140, "dsr": 0.91},
            "test": {"sharpe": 0.8, "sortino": 1.0},
            "holdout": {"sharpe": 0.6},
        },
        "KEP02_rsi_tighter": {
            "train": {"sharpe": 1.3, "sortino": 1.7, "max_dd_pct": 7.0, "n_trades": 100, "dsr": 0.95},
            "test": {"sharpe": 1.0, "sortino": 1.2},
            "holdout": {"sharpe": 0.85},
        },
    }

    aggregate = summarize_results(spec, results)

    assert aggregate["best_train_variant"] == "KEP00_baseline"
    assert aggregate["conservative_variant"] == "KEP01_rsi_looser"
    assert aggregate["dsr_passed"] is True
    assert aggregate["test_passed"] is False
    assert aggregate["holdout_passed"] is False
    assert aggregate["test_pending"] is False
    assert aggregate["holdout_pending"] is False


def test_render_checklist_includes_auto_filled_sections():
    spec = ENGINE_SPECS["medallion"]
    aggregate = {
        "train_rows": [
            {"variant": "MED00_baseline", "sharpe": 1.234, "sortino": 1.5, "max_dd_pct": 4.2, "n_trades": 130, "dsr": 0.96},
        ],
        "best_train_variant": "MED00_baseline",
        "best_train_sharpe": 1.234,
        "best_train_dsr": 0.96,
        "sharpe_std": 0.1,
        "dsr_passed": True,
        "top3_test_rows": [
            {"rank": 1, "variant": "MED00_baseline", "sharpe_train": 1.234, "sharpe_test": 1.05, "sortino_test": 1.2},
        ],
        "worst_top3_test_sharpe": 1.05,
        "test_passed": True,
        "test_pending": False,
        "conservative_variant": "MED00_baseline",
        "holdout_sharpe": 0.88,
        "holdout_passed": True,
        "holdout_pending": False,
    }

    text = render_checklist(spec, aggregate)

    assert "# Engine Validation Checklist - MEDALLION" in text
    assert "MED00_baseline" in text
    assert "DSR p-value: 0.960" in text
    assert "Passou (> 1.0)? SIM" in text


def test_summarize_results_marks_missing_test_and_holdout_as_pending():
    spec = ENGINE_SPECS["deshaw"]
    results = {
        "DSH00_baseline": {
            "train": {"sharpe": -0.6, "sortino": -0.4, "max_dd_pct": 2.0, "n_trades": 50, "dsr": 0.0},
        },
        "DSH01_chop_only": {
            "train": {"sharpe": -0.2, "sortino": -0.1, "max_dd_pct": 0.3, "n_trades": 2, "dsr": 0.04},
        },
    }

    aggregate = summarize_results(spec, results)

    assert aggregate["worst_top3_test_sharpe"] is None
    assert aggregate["conservative_variant"] is None
    assert aggregate["test_pending"] is True
    assert aggregate["holdout_pending"] is True


def test_summarize_results_marks_none_test_metrics_as_pending():
    spec = ENGINE_SPECS["bridgewater"]
    results = {
        "BW00_baseline": {
            "train": {"sharpe": 2.0, "sortino": 2.5, "max_dd_pct": 2.0, "n_trades": 30, "dsr": 0.99},
            "test": {"sharpe": None, "sortino": None},
        },
        "BW01_thresh_035": {
            "train": {"sharpe": 1.9, "sortino": 2.3, "max_dd_pct": 2.1, "n_trades": 28, "dsr": 0.98},
            "test": {"sharpe": None, "sortino": None},
        },
        "BW02_thresh_040": {
            "train": {"sharpe": 1.8, "sortino": 2.2, "max_dd_pct": 2.2, "n_trades": 27, "dsr": 0.97},
            "test": {"sharpe": None, "sortino": None},
        },
    }

    aggregate = summarize_results(spec, results)

    assert aggregate["worst_top3_test_sharpe"] is None
    assert aggregate["test_pending"] is True
    assert aggregate["conservative_variant"] is None


def test_execute_run_treats_soft_exit_message_in_stderr_as_zero_trade(tmp_path, monkeypatch):
    spec = ENGINE_SPECS["bridgewater"]
    out_root = tmp_path / "artifacts"
    root = tmp_path / "repo"
    engine_dir = root / spec.data_dir
    engine_dir.mkdir(parents=True)

    monkeypatch.setattr(grid, "ROOT", root)
    monkeypatch.setattr(grid, "build_command", lambda *args, **kwargs: ["python", "fake.py"])
    monkeypatch.setattr(grid.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(
        returncode=1,
        stdout="",
        stderr="sem trades fechados\n",
    ))
    monkeypatch.setattr(grid, "_find_new_run_dir", lambda *args, **kwargs: None)

    result = execute_run(
        spec,
        "BW00_baseline",
        spec.variants["BW00_baseline"],
        build_windows(spec)[0],
        "python",
        out_root,
    )

    assert result["n_trades"] == 0
    assert result["sharpe"] is None
    assert result["stage_note"] == "no_closed_trades"
