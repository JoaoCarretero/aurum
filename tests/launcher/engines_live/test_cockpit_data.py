"""Unit tests for data/cockpit.py — pure cockpit_api client + cache."""
from __future__ import annotations

import time
from unittest.mock import patch


def test_cache_starts_empty():
    from launcher_support.engines_live.data import cockpit

    cockpit.reset_cache_for_tests()
    snapshot = cockpit.get_cached_runs()

    assert snapshot is None


def test_cache_stores_runs_after_fetch():
    from launcher_support.engines_live.data import cockpit

    cockpit.reset_cache_for_tests()
    fake_runs = [{"run_id": "abc", "engine": "citadel", "mode": "paper"}]

    with patch.object(cockpit, "_fetch_runs_from_api", return_value=fake_runs):
        cockpit.force_refresh()

    assert cockpit.get_cached_runs() == fake_runs


def test_cache_respects_ttl():
    from launcher_support.engines_live.data import cockpit

    cockpit.reset_cache_for_tests()
    with patch.object(cockpit, "_fetch_runs_from_api", return_value=[{"r": 1}]):
        cockpit.force_refresh()

    # Second call within TTL should return cached, not re-fetch
    with patch.object(cockpit, "_fetch_runs_from_api", return_value=[{"r": 2}]) as fetch:
        result = cockpit.runs_cached()
        assert fetch.call_count == 0  # cache hit, no API call
    assert result == [{"r": 1}]


def test_cache_expires_after_ttl():
    from launcher_support.engines_live.data import cockpit

    cockpit.reset_cache_for_tests()
    with patch.object(cockpit, "_fetch_runs_from_api", return_value=[{"r": 1}]):
        cockpit.force_refresh()

    # Move past TTL
    cockpit._CACHE_STATE["ts"] = time.time() - (cockpit.CACHE_TTL_S + 10)

    with patch.object(cockpit, "_fetch_runs_from_api", return_value=[{"r": 2}]) as fetch:
        result = cockpit.runs_cached()
        assert fetch.call_count == 1
    assert result == [{"r": 2}]


def test_client_returns_none_if_keys_missing():
    from launcher_support.engines_live.data import cockpit
    from core.risk.key_store import KeyStoreError

    cockpit.reset_client_for_tests()
    with patch("launcher_support.engines_live.data.cockpit.load_runtime_keys") as lrk:
        lrk.side_effect = KeyStoreError("placeholder")
        client = cockpit.get_client()
        assert client is None


def test_loading_flag_toggles():
    from launcher_support.engines_live.data import cockpit

    cockpit.reset_cache_for_tests()
    assert cockpit.is_loading() is False
    cockpit.set_loading(True)
    assert cockpit.is_loading() is True
    cockpit.set_loading(False)
    assert cockpit.is_loading() is False
