"""Typed CockpitClient methods correctly delegate to _get with right paths."""
from unittest.mock import MagicMock

from launcher_support.cockpit_client import CockpitClient


def test_get_run_signals_calls_correct_path():
    client = CockpitClient.__new__(CockpitClient)
    client._get = MagicMock(return_value={"signals": [], "source": "missing"})
    result = client.get_run_signals("rid", limit=50)
    client._get.assert_called_with("/v1/runs/rid/signals?limit=50")
    assert result == {"signals": [], "source": "missing"}


def test_get_run_trades_calls_correct_path():
    client = CockpitClient.__new__(CockpitClient)
    client._get = MagicMock(return_value={"trades": []})
    result = client.get_run_trades("rid")
    client._get.assert_called_with("/v1/runs/rid/trades")
    assert result == {"trades": []}


def test_get_run_log_tail_uses_tail_param():
    """Log endpoint takes ?tail=N (not ?limit=)."""
    client = CockpitClient.__new__(CockpitClient)
    client._get = MagicMock(return_value={"lines": []})
    result = client.get_run_log_tail("rid", limit=300)
    client._get.assert_called_with("/v1/runs/rid/log?tail=300")
    assert result == {"lines": []}


def test_typed_methods_handle_get_returning_none():
    client = CockpitClient.__new__(CockpitClient)
    client._get = MagicMock(return_value=None)
    assert client.get_run_signals("rid") == {}
    assert client.get_run_trades("rid") == {}
    assert client.get_run_log_tail("rid") == {}
