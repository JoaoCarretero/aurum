import json
import re
from pathlib import Path

from core.analysis_export import _collect_run


ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "phase_c" / "backtest"
RUN_DIR = ROOT / "data" / "runs" / "citadel_2026-04-10_1122"


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _trade_projection(trade: dict) -> dict:
    keys = [
        "symbol",
        "timestamp",
        "direction",
        "entry",
        "stop",
        "target",
        "exit_p",
        "result",
        "pnl",
        "size",
        "score",
    ]
    return {key: trade.get(key) for key in keys}


def _parse_veto_counts(report_html: str, names: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for name in names:
        pattern = (
            rf"{re.escape(name)}\s*</div>\s*<div[^>]*>\s*<div[^>]*></div>\s*</div>\s*"
            rf"<div[^>]*>\s*([0-9]+)\s*\([0-9.]+%\)"
        )
        match = re.search(pattern, report_html, re.S)
        assert match, f"missing veto count for {name}"
        out[name] = int(match.group(1))
    return out


def test_collect_run_matches_recorded_backtest_snapshot():
    expected = _load_json(FIXTURES / "citadel_2026-04-10_1122_snapshot.json")
    entry = _collect_run(RUN_DIR)

    equity_curve = _load_json(RUN_DIR / "equity.json")
    trades = entry["trades"]

    actual = {
        "run_id": entry["run_id"],
        "engine": entry["engine"],
        "summary": entry["summary"],
        "trade_count": len(trades),
        "wins": sum(1 for trade in trades if trade.get("result") == "WIN"),
        "losses": sum(1 for trade in trades if trade.get("result") == "LOSS"),
        "equity_points": len(equity_curve),
        "first_trade": _trade_projection(trades[0]),
        "last_trade": _trade_projection(trades[-1]),
    }

    assert actual == {k: expected[k] for k in actual}


def test_report_html_veto_counts_match_recorded_snapshot():
    expected = _load_json(FIXTURES / "citadel_2026-04-10_1122_snapshot.json")["veto_counts"]
    report_html = (RUN_DIR / "report.html").read_text(encoding="utf-8", errors="replace")

    actual = _parse_veto_counts(report_html, list(expected.keys()))

    assert actual == expected
