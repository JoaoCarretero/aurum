"""Unit tests for data/procs.py — local procs snapshot + heartbeat reader.

Sanity note: _list_procs_cached in engines_live_view.py delegates to
core.ops.proc.list_procs (NOT a direct JSON read). data/procs.py replicates
that delegation with its own TTL cache. Tests mock core.ops.proc.list_procs
rather than patching PROCS_PATH, since there is no direct JSON read.
"""
from __future__ import annotations

import json


def test_snapshot_empty_when_list_procs_raises(monkeypatch):
    """When core.ops.proc.list_procs raises, list_procs() returns []."""
    from launcher_support.engines_live.data import procs

    procs.reset_cache_for_tests()

    import core.ops.proc as _proc_mod

    def _raising(**kw):
        raise OSError("no file")
    monkeypatch.setattr(_proc_mod, "list_procs", _raising)

    rows = procs.list_procs()
    assert rows == []


def test_snapshot_reads_from_core_proc(monkeypatch):
    """list_procs() returns rows from core.ops.proc.list_procs."""
    from launcher_support.engines_live.data import procs

    procs.reset_cache_for_tests()

    import core.ops.proc as _proc_mod

    fake_rows = [
        {"engine": "citadel", "pid": 42, "status": "running", "alive": True,
         "started": "2026-04-23T13:35:11"},
    ]
    monkeypatch.setattr(_proc_mod, "list_procs", lambda **kw: list(fake_rows))

    rows = procs.list_procs()
    assert len(rows) == 1
    assert rows[0]["engine"] == "citadel"
    assert rows[0]["pid"] == 42


def test_snapshot_uses_ttl_cache(monkeypatch):
    """list_procs() caches for TTL — second call within TTL returns same rows."""
    from launcher_support.engines_live.data import procs

    procs.reset_cache_for_tests()

    import core.ops.proc as _proc_mod

    calls = []

    def fake_list(**kw):
        calls.append(len(calls))
        return [{"engine": "citadel", "pid": 42, "status": "running"}]

    monkeypatch.setattr(_proc_mod, "list_procs", fake_list)

    r1 = procs.list_procs()
    # Patch to different result — within TTL, we should still get r1
    monkeypatch.setattr(_proc_mod, "list_procs",
                        lambda **kw: [{"engine": "jump", "pid": 99, "status": "running"}])
    r2 = procs.list_procs()

    assert r1 == r2  # cache hit — still citadel
    assert len(calls) == 1  # only one real call was made


def test_snapshot_force_refresh_bypasses_cache(monkeypatch):
    """force=True bypasses TTL and fetches fresh data."""
    from launcher_support.engines_live.data import procs

    procs.reset_cache_for_tests()

    import core.ops.proc as _proc_mod

    monkeypatch.setattr(_proc_mod, "list_procs",
                        lambda **kw: [{"engine": "citadel", "pid": 1, "status": "running"}])
    procs.list_procs()

    # Now swap the underlying source
    monkeypatch.setattr(_proc_mod, "list_procs",
                        lambda **kw: [{"engine": "jump", "pid": 2, "status": "running"}])

    r2 = procs.list_procs(force=True)

    assert len(r2) == 1
    assert r2[0]["engine"] == "jump"


def test_heartbeat_reads_json(tmp_path):
    """read_heartbeat() returns parsed JSON from run_dir/state/heartbeat.json."""
    from launcher_support.engines_live.data import procs

    hb_path = tmp_path / "run_dir" / "state" / "heartbeat.json"
    hb_path.parent.mkdir(parents=True)
    hb_path.write_text(json.dumps({
        "run_id": "abc", "status": "running", "ticks_ok": 17, "novel_total": 0
    }))

    result = procs.read_heartbeat(tmp_path / "run_dir")
    assert result["ticks_ok"] == 17
    assert result["status"] == "running"


def test_heartbeat_returns_none_if_missing(tmp_path):
    """read_heartbeat() returns None when heartbeat.json does not exist."""
    from launcher_support.engines_live.data import procs

    result = procs.read_heartbeat(tmp_path / "nonexistent")
    assert result is None


def test_heartbeat_returns_none_for_non_dict_json(tmp_path):
    """read_heartbeat() returns None when heartbeat.json contains non-dict JSON."""
    from launcher_support.engines_live.data import procs

    hb_path = tmp_path / "run_dir" / "state" / "heartbeat.json"
    hb_path.parent.mkdir(parents=True)
    hb_path.write_text(json.dumps([1, 2, 3]))

    result = procs.read_heartbeat(tmp_path / "run_dir")
    assert result is None


def test_snapshot_ttl_expires_triggers_fresh_fetch(monkeypatch):
    """After TTL elapses, a re-fetch happens (not just cache return)."""
    from launcher_support.engines_live.data import procs
    import core.ops.proc as _proc_mod

    call_count = [0]
    fake_rows = [[{"engine": "citadel"}], [{"engine": "jump"}]]

    def _fake(**kw):
        idx = call_count[0]
        call_count[0] += 1
        return fake_rows[min(idx, len(fake_rows) - 1)]

    monkeypatch.setattr(_proc_mod, "list_procs", _fake)
    procs.reset_cache_for_tests()

    # Freeze time via monkeypatch
    fake_now = [1000.0]
    monkeypatch.setattr(procs.time, "monotonic", lambda: fake_now[0])

    # First call — populates cache with fake_rows[0]
    r1 = procs.list_procs()
    assert r1[0]["engine"] == "citadel"
    assert call_count[0] == 1

    # Advance past TTL
    fake_now[0] = 1000.0 + procs.CACHE_TTL_S + 0.1

    # Second call — should re-fetch (fake_rows[1])
    r2 = procs.list_procs()
    assert r2[0]["engine"] == "jump"
    assert call_count[0] == 2
