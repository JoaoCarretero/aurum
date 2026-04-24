import json, time, os
from pathlib import Path
from core.alchemy_state import AlchemyState, EMPTY_SNAPSHOT

def _make_snap(run_dir: Path, **overrides):
    snap = dict(EMPTY_SNAPSHOT)
    snap.update(overrides)
    (run_dir / "state").mkdir(parents=True, exist_ok=True)
    (run_dir / "state" / "snapshot.json").write_text(json.dumps(snap, default=str))

def test_reads_fresh_snapshot(tmp_path, monkeypatch):
    run = tmp_path / "data" / "janestreet" / "2026-01-01_0000"
    _make_snap(run, account=4321.0, mode="paper")
    monkeypatch.chdir(tmp_path)
    st = AlchemyState()
    snap = st.read()
    assert snap["account"] == 4321.0
    assert snap["mode"] == "paper"
    assert snap["_stale"] is False

def test_returns_empty_when_no_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    st = AlchemyState()
    snap = st.read()
    assert snap["account"] == 0
    assert snap["_stale"] is True
    assert snap["opportunities"] == []

def test_marks_stale_when_old(tmp_path, monkeypatch):
    run = tmp_path / "data" / "janestreet" / "2026-01-01_0000"
    _make_snap(run, account=100.0)
    f = run / "state" / "snapshot.json"
    old = time.time() - 999
    os.utime(f, (old, old))
    monkeypatch.chdir(tmp_path)
    st = AlchemyState(stale_seconds=10)
    snap = st.read()
    assert snap["_stale"] is True
    assert snap["account"] == 100.0

def test_handles_malformed_json(tmp_path, monkeypatch):
    run = tmp_path / "data" / "janestreet" / "2026-01-01_0000"
    (run / "state").mkdir(parents=True)
    (run / "state" / "snapshot.json").write_text("{ not json")
    monkeypatch.chdir(tmp_path)
    st = AlchemyState()
    snap = st.read()
    assert snap["_stale"] is True

def test_discovers_latest_run(tmp_path, monkeypatch):
    a = tmp_path / "data" / "janestreet" / "2026-01-01_0000"
    b = tmp_path / "data" / "janestreet" / "2026-01-02_0000"
    _make_snap(a, account=100.0)
    time.sleep(0.05)
    _make_snap(b, account=200.0)
    monkeypatch.chdir(tmp_path)
    st = AlchemyState()
    snap = st.read()
    assert snap["account"] == 200.0

def test_write_params_creates_file_and_flag(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    st = AlchemyState()
    st.write_params({"MIN_APR": 50.0, "MAX_POS": 4})
    params_file = tmp_path / "config" / "alchemy_params.json"
    flag_file   = tmp_path / "config" / "alchemy_params.json.reload"
    assert params_file.exists()
    assert flag_file.exists()
    data = json.loads(params_file.read_text())
    assert data["MIN_APR"] == 50.0
    assert data["MAX_POS"] == 4

def test_write_params_merges_with_existing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "alchemy_params.json").write_text(
        json.dumps({"MIN_APR": 40.0, "MAX_POS": 5, "LEV": 2}))
    st = AlchemyState()
    st.write_params({"MIN_APR": 60.0})
    data = json.loads((tmp_path / "config" / "alchemy_params.json").read_text())
    assert data["MIN_APR"] == 60.0
    assert data["MAX_POS"] == 5
    assert data["LEV"] == 2
