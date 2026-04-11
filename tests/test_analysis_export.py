"""TDD tests for core.analysis_export.

RED first: these tests drive the shape and behaviour of the
export_analysis() function before it exists.
"""
import json
from pathlib import Path
import pytest


# ══════════════════════════════════════════════════════════════
#  Fixture: a fake project root with a few runs and sessions
# ══════════════════════════════════════════════════════════════
def _make_fake_run(runs_dir: Path, run_id: str, n_trades: int = 5,
                   wr_wins: int = 3, with_overfit: bool = True,
                   with_log: bool = True, hmm_regimes: list | None = None):
    rd = runs_dir / run_id
    rd.mkdir(parents=True, exist_ok=True)

    trades = []
    hmm_regimes = hmm_regimes or ["BULL", "BEAR", "CHOP"] * (n_trades // 3 + 1)
    for i in range(n_trades):
        trades.append({
            "symbol": "BTCUSDT" if i % 2 == 0 else "ETHUSDT",
            "time": f"2026-04-0{(i%9)+1} 10h",
            "timestamp": f"2026-04-{(i%28)+1:02d}T10:00:00",
            "direction": "BULLISH" if i % 2 == 0 else "BEARISH",
            "result": "WIN" if i < wr_wins else "LOSS",
            "pnl": 10.0 if i < wr_wins else -8.0,
            "r_multiple": 1.5 if i < wr_wins else -1.0,
            "rr": 2.0,
            "duration": 6,
            "entry": 50000.0,
            "stop": 49000.0,
            "target": 52000.0,
            "exit_p": 52000.0 if i < wr_wins else 49000.0,
            "size": 0.1,
            "score": 0.65,
            "chop_trade": False,
            "macro_bias": "BULL",
            "hmm_regime": hmm_regimes[i % len(hmm_regimes)],
            "hmm_confidence": 0.9,
            "hmm_prob_bull": 0.8 if hmm_regimes[i % len(hmm_regimes)] == "BULL" else 0.1,
            "hmm_prob_bear": 0.1,
            "hmm_prob_chop": 0.1,
            "omega_struct": 0.7,
            "omega_flow": 0.6,
            "omega_cascade": 0.5,
            "omega_momentum": 0.8,
            "omega_pullback": 0.4,
        })

    summary = {
        "n_trades": n_trades,
        "win_rate": 100.0 * wr_wins / n_trades,
        "total_pnl": sum(t["pnl"] for t in trades),
        "roi": 5.5,
        "sortino": 2.1,
        "sharpe": 1.4,
        "max_dd_pct": 3.2,
    }

    (rd / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    (rd / "trades.json").write_text(json.dumps({"trades": trades}), encoding="utf-8")
    (rd / "equity.json").write_text(json.dumps([10000, 10050, 10100, 10080]), encoding="utf-8")
    (rd / "config.json").write_text(json.dumps({"leverage": 2, "score_threshold": 0.53}), encoding="utf-8")
    if with_overfit:
        (rd / "overfit.json").write_text(json.dumps({
            "walk_forward": {"windows": [{"wr": 55}], "stable_pct": 70},
            "monte_carlo": {"p5": 9500, "p50": 10200, "p95": 10800, "pct_pos": 75},
        }), encoding="utf-8")
    if with_log:
        lines = [f"2026-04-11 10:00:{i:02d}  info  line {i}\n" for i in range(250)]
        (rd / "log.txt").write_text("".join(lines), encoding="utf-8")
    return rd


@pytest.fixture
def fake_root(tmp_path):
    (tmp_path / "data" / "runs").mkdir(parents=True)
    (tmp_path / "data" / "live").mkdir(parents=True)
    (tmp_path / "data" / "arbitrage").mkdir(parents=True)
    return tmp_path


# ══════════════════════════════════════════════════════════════
#  Top-level structure
# ══════════════════════════════════════════════════════════════
class TestStructure:
    def test_returns_dict_with_required_top_level_keys(self, fake_root):
        from core.analysis_export import export_analysis
        d = export_analysis(root=fake_root)
        for key in ("meta", "config", "runs", "live_sessions",
                    "arbitrage_sessions", "analysis",
                    "system_state", "comparison"):
            assert key in d, f"missing top-level key: {key}"

    def test_meta_has_required_fields(self, fake_root):
        from core.analysis_export import export_analysis
        d = export_analysis(root=fake_root)
        for key in ("exported_at", "aurum_version", "python_version"):
            assert key in d["meta"]
        # exported_at should be an ISO 8601 string
        assert "T" in d["meta"]["exported_at"]

    def test_config_reflects_params(self, fake_root):
        from core.analysis_export import export_analysis
        from config.params import ACCOUNT_SIZE, LEVERAGE, BASE_RISK
        d = export_analysis(root=fake_root)
        assert d["config"]["account_size"] == ACCOUNT_SIZE
        assert d["config"]["leverage"] == LEVERAGE
        assert d["config"]["base_risk"] == BASE_RISK


# ══════════════════════════════════════════════════════════════
#  Runs section
# ══════════════════════════════════════════════════════════════
class TestRuns:
    def test_runs_collected_with_summary_and_trades(self, fake_root):
        from core.analysis_export import export_analysis
        _make_fake_run(fake_root / "data" / "runs", "citadel_2026-04-01_1200", n_trades=5)
        d = export_analysis(root=fake_root)
        assert len(d["runs"]) == 1
        run = d["runs"][0]
        assert run["run_id"] == "citadel_2026-04-01_1200"
        assert run["engine"] == "citadel"
        assert run["summary"]["n_trades"] == 5
        assert len(run["trades"]) == 5

    def test_runs_capped_at_20_newest_first(self, fake_root):
        from core.analysis_export import export_analysis
        runs_dir = fake_root / "data" / "runs"
        for i in range(25):
            _make_fake_run(runs_dir, f"citadel_2026-04-{i+1:02d}_1200", n_trades=1)
        d = export_analysis(root=fake_root)
        assert len(d["runs"]) == 20
        # Newest first: last created should be first in the list
        ids = [r["run_id"] for r in d["runs"]]
        assert ids[0] > ids[-1]

    def test_trades_truncated_to_500_max(self, fake_root):
        from core.analysis_export import export_analysis
        _make_fake_run(fake_root / "data" / "runs", "citadel_2026-04-01_1200", n_trades=800)
        d = export_analysis(root=fake_root)
        run = d["runs"][0]
        assert len(run["trades"]) == 500
        # Summary must still reflect the real count
        assert run["summary"]["n_trades"] == 800

    def test_log_tail_limited_to_100_lines(self, fake_root):
        from core.analysis_export import export_analysis
        _make_fake_run(fake_root / "data" / "runs", "citadel_2026-04-01_1200", n_trades=1)
        d = export_analysis(root=fake_root)
        run = d["runs"][0]
        tail = run["log_tail"]
        assert tail is not None
        assert tail.count("\n") <= 100

    def test_missing_overfit_becomes_null(self, fake_root):
        from core.analysis_export import export_analysis
        _make_fake_run(fake_root / "data" / "runs", "citadel_2026-04-01_1200",
                       n_trades=1, with_overfit=False)
        d = export_analysis(root=fake_root)
        assert d["runs"][0]["overfit"] is None

    def test_corrupt_trades_json_does_not_crash(self, fake_root):
        from core.analysis_export import export_analysis
        rd = fake_root / "data" / "runs" / "citadel_2026-04-01_1200"
        rd.mkdir(parents=True)
        (rd / "summary.json").write_text("{\"n_trades\": 5}", encoding="utf-8")
        (rd / "trades.json").write_text("not-json{", encoding="utf-8")
        d = export_analysis(root=fake_root)
        assert len(d["runs"]) == 1
        assert d["runs"][0]["trades"] == []


# ══════════════════════════════════════════════════════════════
#  Live and arbitrage sessions
# ══════════════════════════════════════════════════════════════
class TestSessions:
    def _make_live_session(self, root: Path, sid: str, crashed: bool = False):
        d = root / "data" / "live" / sid / "logs"
        d.mkdir(parents=True, exist_ok=True)
        lines = [f"info {i}\n" for i in range(150)]
        if crashed:
            lines += ["Traceback (most recent call last):\n",
                      "  File ..., line 1, in <module>\n",
                      "RuntimeError: boom\n"]
        (d / "live.log").write_text("".join(lines), encoding="utf-8")

    def _make_arb_session(self, root: Path, sid: str):
        d = root / "data" / "arbitrage" / sid / "logs"
        d.mkdir(parents=True, exist_ok=True)
        (d / "arb.log").write_text("info line\n" * 80, encoding="utf-8")
        rep = root / "data" / "arbitrage" / sid / "reports"
        rep.mkdir(exist_ok=True)
        (rep / "session.json").write_text(json.dumps({"n_fills": 3}), encoding="utf-8")

    def test_live_sessions_collected_newest_first_max_10(self, fake_root):
        from core.analysis_export import export_analysis
        for i in range(15):
            self._make_live_session(fake_root, f"2026-04-{i+1:02d}_1200")
        d = export_analysis(root=fake_root)
        assert len(d["live_sessions"]) <= 10
        ids = [s["run_id"] for s in d["live_sessions"]]
        assert ids[0] >= ids[-1]

    def test_live_session_crash_detected(self, fake_root):
        from core.analysis_export import export_analysis
        self._make_live_session(fake_root, "2026-04-10_1500", crashed=True)
        self._make_live_session(fake_root, "2026-04-10_1600", crashed=False)
        d = export_analysis(root=fake_root)
        by_id = {s["run_id"]: s for s in d["live_sessions"]}
        assert by_id["2026-04-10_1500"]["crash"] is True
        assert by_id["2026-04-10_1600"]["crash"] is False

    def test_arbitrage_sessions_capped_at_5(self, fake_root):
        from core.analysis_export import export_analysis
        for i in range(8):
            self._make_arb_session(fake_root, f"2026-04-{i+1:02d}_1200")
        d = export_analysis(root=fake_root)
        assert len(d["arbitrage_sessions"]) <= 5


# ══════════════════════════════════════════════════════════════
#  Analysis aggregation
# ══════════════════════════════════════════════════════════════
class TestAnalysis:
    def test_analysis_uses_latest_run(self, fake_root):
        from core.analysis_export import export_analysis
        runs_dir = fake_root / "data" / "runs"
        _make_fake_run(runs_dir, "citadel_2026-04-01_1200", n_trades=10, wr_wins=6)
        _make_fake_run(runs_dir, "citadel_2026-04-02_1200", n_trades=4, wr_wins=3)
        d = export_analysis(root=fake_root)
        assert d["analysis"]["latest_run_id"] == "citadel_2026-04-02_1200"
        assert d["analysis"]["n_trades"] == 4

    def test_analysis_win_rate_matches_trades(self, fake_root):
        from core.analysis_export import export_analysis
        _make_fake_run(fake_root / "data" / "runs", "citadel_2026-04-01_1200",
                       n_trades=10, wr_wins=6)
        d = export_analysis(root=fake_root)
        assert d["analysis"]["win_rate"] == pytest.approx(60.0)

    def test_analysis_groups_by_symbol(self, fake_root):
        from core.analysis_export import export_analysis
        _make_fake_run(fake_root / "data" / "runs", "citadel_2026-04-01_1200",
                       n_trades=6, wr_wins=4)
        d = export_analysis(root=fake_root)
        bs = d["analysis"]["trades_by_symbol"]
        # Half are BTCUSDT, half ETHUSDT
        assert "BTCUSDT" in bs
        assert "ETHUSDT" in bs
        assert bs["BTCUSDT"]["n"] + bs["ETHUSDT"]["n"] == 6

    def test_analysis_groups_by_direction(self, fake_root):
        from core.analysis_export import export_analysis
        _make_fake_run(fake_root / "data" / "runs", "citadel_2026-04-01_1200",
                       n_trades=6, wr_wins=4)
        d = export_analysis(root=fake_root)
        bd = d["analysis"]["trades_by_direction"]
        assert "BULLISH" in bd and "BEARISH" in bd
        assert bd["BULLISH"]["n"] + bd["BEARISH"]["n"] == 6

    def test_analysis_groups_by_hmm_regime(self, fake_root):
        from core.analysis_export import export_analysis
        _make_fake_run(fake_root / "data" / "runs", "citadel_2026-04-01_1200",
                       n_trades=9, wr_wins=6,
                       hmm_regimes=["BULL", "BEAR", "CHOP",
                                    "BULL", "BEAR", "CHOP",
                                    "BULL", "BEAR", "CHOP"])
        d = export_analysis(root=fake_root)
        reg = d["analysis"]["hmm_regime"]
        assert reg["available"] is True
        assert reg["trades_by_hmm_regime"]["BULL"]["n"] == 3
        assert reg["trades_by_hmm_regime"]["BEAR"]["n"] == 3
        assert reg["trades_by_hmm_regime"]["CHOP"]["n"] == 3

    def test_analysis_hmm_unavailable_when_no_column(self, fake_root):
        from core.analysis_export import export_analysis
        rd = fake_root / "data" / "runs" / "citadel_2026-04-01_1200"
        rd.mkdir(parents=True)
        (rd / "summary.json").write_text("{\"n_trades\": 1}", encoding="utf-8")
        (rd / "trades.json").write_text(json.dumps({"trades": [
            {"symbol": "BTC", "direction": "BULLISH", "result": "WIN", "pnl": 10.0}
        ]}), encoding="utf-8")
        d = export_analysis(root=fake_root)
        assert d["analysis"]["hmm_regime"]["available"] is False

    def test_analysis_cost_breakdown_fields(self, fake_root):
        from core.analysis_export import export_analysis
        _make_fake_run(fake_root / "data" / "runs", "citadel_2026-04-01_1200",
                       n_trades=5, wr_wins=3)
        d = export_analysis(root=fake_root)
        cb = d["analysis"]["cost_breakdown"]
        for k in ("total_costs", "gross_pnl", "net_pnl", "cost_pct_of_gross"):
            assert k in cb


# ══════════════════════════════════════════════════════════════
#  Graceful handling
# ══════════════════════════════════════════════════════════════
class TestGraceful:
    def test_missing_data_dir_returns_empty_sections(self, tmp_path):
        from core.analysis_export import export_analysis
        d = export_analysis(root=tmp_path)
        assert d["runs"] == []
        assert d["live_sessions"] == []
        assert d["arbitrage_sessions"] == []
        assert d["analysis"]["n_trades"] == 0

    def test_output_path_writes_valid_json(self, fake_root, tmp_path):
        from core.analysis_export import export_analysis
        _make_fake_run(fake_root / "data" / "runs", "citadel_2026-04-01_1200", n_trades=3)
        out = tmp_path / "export.json"
        d = export_analysis(root=fake_root, output_path=out)
        assert out.exists()
        loaded = json.loads(out.read_text(encoding="utf-8"))
        assert loaded["runs"][0]["run_id"] == "citadel_2026-04-01_1200"
        assert d["runs"][0]["run_id"] == loaded["runs"][0]["run_id"]

    def test_export_file_under_2mb(self, fake_root, tmp_path):
        from core.analysis_export import export_analysis
        # 20 runs with 500 trades each — upper bound of our truncation
        runs_dir = fake_root / "data" / "runs"
        for i in range(20):
            _make_fake_run(runs_dir, f"citadel_2026-04-{i+1:02d}_1200", n_trades=500)
        out = tmp_path / "big.json"
        export_analysis(root=fake_root, output_path=out)
        size_mb = out.stat().st_size / (1024 * 1024)
        assert size_mb < 2.0, f"export {size_mb:.2f} MB exceeds 2 MB limit"
