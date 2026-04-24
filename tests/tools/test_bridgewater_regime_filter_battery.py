from __future__ import annotations

from pathlib import Path

from tools.batteries import bridgewater_regime_filter_battery as battery


def test_default_ends_are_four_recent_aligned_cuts():
    assert battery._default_ends() == [
        "2026-04-05T19:00:00",
        "2026-04-10T19:00:00",
        "2026-04-15T19:00:00",
        "2026-04-20T19:00:00",
    ]


def test_extract_metrics_picks_key_fields():
    payload = {
        "n_trades": 120,
        "roi": 6.5,
        "sharpe": 7.25,
        "max_dd_pct": 2.1,
        "allowed_macro_regimes": ["BEAR", "CHOP"],
        "overfit_passed": 4,
        "overfit_warnings": 1,
        "overfit_failed": 1,
    }

    out = battery._extract_metrics(payload)

    assert out == {
        "n_trades": 120,
        "roi": 6.5,
        "sharpe": 7.25,
        "max_dd_pct": 2.1,
        "allowed_macro_regimes": ["BEAR", "CHOP"],
        "overfit": {"passed": 4, "warnings": 1, "failed": 1},
    }


def test_write_report_counts_regime_filter_wins(tmp_path: Path):
    rows = [
        {
            "end": "2026-04-05T19:00:00",
            "status": "OK",
            "allowed_regimes": None,
            "metrics": {"n_trades": 10, "roi": 2.0, "sharpe": 1.0},
        },
        {
            "end": "2026-04-05T19:00:00",
            "status": "OK",
            "allowed_regimes": "BEAR,CHOP",
            "metrics": {"n_trades": 8, "roi": 3.0, "sharpe": 2.0},
        },
        {
            "end": "2026-04-10T19:00:00",
            "status": "OK",
            "allowed_regimes": None,
            "metrics": {"n_trades": 9, "roi": 4.0, "sharpe": 3.0},
        },
        {
            "end": "2026-04-10T19:00:00",
            "status": "OK",
            "allowed_regimes": "BEAR,CHOP",
            "metrics": {"n_trades": 7, "roi": 2.5, "sharpe": 1.5},
        },
    ]

    args = battery.argparse.Namespace(
        days=30,
        basket="bluechip",
        ends=["2026-04-05T19:00:00", "2026-04-10T19:00:00"],
    )
    battery._write_report(rows, tmp_path, args)

    text = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "ALL=1" in text
    assert "BEAR,CHOP=1" in text
    assert "Gap" in text
