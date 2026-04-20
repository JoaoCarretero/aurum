from __future__ import annotations

from pathlib import Path

from tools.batteries import bridgewater_rolling_compare_battery as battery


def test_default_ends_are_four_recent_aligned_cuts():
    assert battery._default_ends() == [
        "2026-04-05T19:00:00",
        "2026-04-10T19:00:00",
        "2026-04-15T19:00:00",
        "2026-04-20T19:00:00",
    ]


def test_write_report_counts_wins(tmp_path: Path):
    rows = [
        {
            "end": "2026-04-05T19:00:00",
            "status": "OK",
            "winner": "funding+ls",
            "funding_oi_ls": {
                "n_trades": 10,
                "sharpe": 1.0,
                "roi_pct": 2.0,
                "max_dd_pct": 1.0,
                "oi_zero_pct": 25.0,
            },
            "funding_ls": {
                "n_trades": 12,
                "sharpe": 2.0,
                "roi_pct": 3.0,
                "max_dd_pct": 1.0,
                "oi_zero_pct": 100.0,
            },
        },
        {
            "end": "2026-04-10T19:00:00",
            "status": "OK",
            "winner": "funding+oi+ls",
            "funding_oi_ls": {
                "n_trades": 9,
                "sharpe": 2.5,
                "roi_pct": 4.0,
                "max_dd_pct": 1.5,
                "oi_zero_pct": 10.0,
            },
            "funding_ls": {
                "n_trades": 8,
                "sharpe": 1.0,
                "roi_pct": 1.0,
                "max_dd_pct": 1.5,
                "oi_zero_pct": 100.0,
            },
        },
    ]

    args = battery.argparse.Namespace(
        days=30,
        basket="bluechip",
        preset="robust",
        allowed_regimes="BEAR,CHOP",
        ends=["2026-04-05T19:00:00", "2026-04-10T19:00:00"],
    )
    battery._write_report(rows, tmp_path, args)

    text = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "funding+LS=1" in text
    assert "funding+OI+LS=1" in text
    assert "OI zero" in text
    assert "OI gap" in text


def test_extract_variant_metrics_lifts_diagnostics_and_overfit():
    row = {
        "summary": {"n_trades": 7, "roi_pct": 1.5, "sharpe": 2.25, "max_dd_pct": 0.9},
        "sentiment_diagnostics": {"oi_zero_pct": 42.5, "oi_nonzero_trades": 4, "ls_zero_pct": 5.0},
        "overfit": {"passed": 3, "warnings": 1, "failed": 2},
    }

    out = battery._extract_variant_metrics(row)

    assert out == {
        "n_trades": 7,
        "roi_pct": 1.5,
        "sharpe": 2.25,
        "max_dd_pct": 0.9,
        "oi_zero_pct": 42.5,
        "oi_nonzero_trades": 4,
        "ls_zero_pct": 5.0,
        "overfit": {"passed": 3, "warnings": 1, "failed": 2},
    }
