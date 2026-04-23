import json
from engines.janestreet import Engine

def test_snapshot_contains_required_keys(tmp_run, monkeypatch):
    # Arrange: minimal engine with mocked state
    eng = Engine.__new__(Engine)  # bypass __init__
    eng.account = 5000.0
    eng.peak = 5100.0
    eng.positions = []
    eng.closed = []
    eng.killed = False
    eng.consecutive_losses = 0
    eng._snapshot_file = tmp_run / "state" / "snapshot.json"
    eng._latest_opportunities = []
    eng._latest_funding = {}
    eng._latest_basis_history = {}
    eng._latest_venue_health = {}
    eng.venues = {}

    eng._write_snapshot()

    data = json.loads(eng._snapshot_file.read_text())
    required = {
        "ts","run_id","mode","engine_pid","account","peak",
        "exposure_usd","drawdown_pct","realized_pnl","unrealized_pnl",
        "losses_streak","killed","sortino","trades_count",
        "opportunities","funding","next_funding","positions",
        "venue_health","basis_history",
    }
    assert required.issubset(data.keys()), f"missing: {required - data.keys()}"
    assert data["account"] == 5000.0
    assert data["killed"] is False
