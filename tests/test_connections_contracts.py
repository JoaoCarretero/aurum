"""Contract tests for core.connections — ConnectionManager.

Cobrem: load/save state, active_market, set_connected, ping cache TTL,
status_summary. STATE_FILE redirecionado pra tmp via monkeypatch.
"""
from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

import pytest

import core.connections as cxn
from core.connections import DEFAULT_STATE, MARKETS, ConnectionManager


@pytest.fixture
def iso_state(tmp_path, monkeypatch):
    """Redireciona STATE_FILE pra tmp."""
    state_file = tmp_path / "connections.json"
    monkeypatch.setattr(cxn, "STATE_FILE", state_file)
    return state_file


# ────────────────────────────────────────────────────────────
# __init__ / load
# ────────────────────────────────────────────────────────────

class TestLoad:
    def test_fresh_init_uses_defaults(self, iso_state):
        assert not iso_state.exists()
        mgr = ConnectionManager()
        assert mgr.active_market == "crypto_futures"
        assert mgr.state["connections"]["binance_futures"]["label"] == "Binance Futures"

    def test_defaults_are_deep_copied_not_shared(self, iso_state):
        mgr = ConnectionManager()
        mgr.state["connections"]["binance_futures"]["label"] = "MUTATED"
        # DEFAULT_STATE global não deve ser afetado
        assert DEFAULT_STATE["connections"]["binance_futures"]["label"] == "Binance Futures"

    def test_saved_state_loaded(self, iso_state):
        saved = {
            "active_market": "forex",
            "connections": {
                "binance_futures": {"connected": True, "latency_ms": 123},
            },
        }
        iso_state.parent.mkdir(parents=True, exist_ok=True)
        iso_state.write_text(json.dumps(saved), encoding="utf-8")
        mgr = ConnectionManager()
        assert mgr.active_market == "forex"
        assert mgr.is_connected("binance_futures") is True

    def test_malformed_json_falls_back_to_defaults(self, iso_state):
        iso_state.parent.mkdir(parents=True, exist_ok=True)
        iso_state.write_text("{malformed", encoding="utf-8")
        mgr = ConnectionManager()
        # Should not crash; falls back to DEFAULT_STATE
        assert mgr.active_market == "crypto_futures"

    def test_saved_state_merges_with_defaults(self, iso_state):
        """Campos novos adicionados em DEFAULT_STATE aparecem no merge."""
        # Saved state sem a connection 'telegram' (nova) → merge traz do default
        partial = {
            "active_market": "crypto_futures",
            "connections": {"binance_futures": {"connected": True}},
        }
        iso_state.parent.mkdir(parents=True, exist_ok=True)
        iso_state.write_text(json.dumps(partial), encoding="utf-8")
        mgr = ConnectionManager()
        # telegram existe no default → precisa existir no state carregado
        assert "telegram" in mgr.state["connections"]

    def test_unknown_connection_key_in_save_ignored(self, iso_state):
        """Chaves não existentes no DEFAULT_STATE são silenciosamente ignoradas."""
        saved = {
            "connections": {
                "ghost_exchange_xyz": {"connected": True, "label": "Ghost"},
            },
        }
        iso_state.parent.mkdir(parents=True, exist_ok=True)
        iso_state.write_text(json.dumps(saved), encoding="utf-8")
        mgr = ConnectionManager()
        assert "ghost_exchange_xyz" not in mgr.state["connections"]


# ────────────────────────────────────────────────────────────
# active_market setter
# ────────────────────────────────────────────────────────────

class TestActiveMarket:
    def test_setter_persists(self, iso_state):
        mgr = ConnectionManager()
        mgr.active_market = "forex"
        # Load from disk to verify persistence
        mgr2 = ConnectionManager()
        assert mgr2.active_market == "forex"

    def test_setter_writes_file(self, iso_state):
        mgr = ConnectionManager()
        mgr.active_market = "equities"
        assert iso_state.exists()
        loaded = json.loads(iso_state.read_text(encoding="utf-8"))
        assert loaded["active_market"] == "equities"


# ────────────────────────────────────────────────────────────
# get / is_connected / set_connected
# ────────────────────────────────────────────────────────────

class TestConnectionCrud:
    def test_get_missing_returns_empty_dict(self, iso_state):
        mgr = ConnectionManager()
        assert mgr.get("nonexistent") == {}

    def test_get_known_returns_config(self, iso_state):
        mgr = ConnectionManager()
        assert mgr.get("binance_futures")["label"] == "Binance Futures"

    def test_is_connected_defaults_false(self, iso_state):
        mgr = ConnectionManager()
        assert mgr.is_connected("binance_futures") is False

    def test_set_connected_toggles(self, iso_state):
        mgr = ConnectionManager()
        mgr.set_connected("binance_futures", True)
        assert mgr.is_connected("binance_futures") is True

    def test_set_connected_persists(self, iso_state):
        mgr = ConnectionManager()
        mgr.set_connected("bybit", True, latency_ms=42)
        mgr2 = ConnectionManager()
        assert mgr2.is_connected("bybit") is True
        assert mgr2.get("bybit")["latency_ms"] == 42

    def test_set_connected_timestamps_on_connect(self, iso_state):
        mgr = ConnectionManager()
        mgr.set_connected("binance_futures", True)
        assert "last_ping" in mgr.get("binance_futures")

    def test_set_connected_unknown_key_noop(self, iso_state):
        """Chave não existente é silenciosamente ignorada (não cria novo entry)."""
        mgr = ConnectionManager()
        mgr.set_connected("ghost_provider", True)
        assert "ghost_provider" not in mgr.state["connections"]


# ────────────────────────────────────────────────────────────
# ping (com cache TTL)
# ────────────────────────────────────────────────────────────

class TestPing:
    def _mock_ok(self, latency_ms: float = 100.0):
        r = MagicMock()
        r.status_code = 200
        return r

    def test_ping_unsupported_provider_returns_none(self, iso_state):
        mgr = ConnectionManager()
        assert mgr.ping("telegram") is None  # Not implemented for telegram

    def test_ping_binance_success_returns_latency(self, iso_state):
        mgr = ConnectionManager()
        with patch("requests.get", return_value=self._mock_ok()):
            latency = mgr.ping("binance_futures")
        assert latency is not None
        assert latency >= 0

    def test_ping_cached_within_ttl(self, iso_state):
        mgr = ConnectionManager()
        with patch("requests.get", return_value=self._mock_ok()) as mock_get:
            mgr.ping("binance_futures")
            mgr.ping("binance_futures")
            mgr.ping("binance_futures")
        # TTL=8s default → 3 chamadas rápidas = 1 request de verdade
        assert mock_get.call_count == 1

    def test_ping_max_age_zero_forces_fresh(self, iso_state):
        mgr = ConnectionManager()
        with patch("requests.get", return_value=self._mock_ok()) as mock_get:
            mgr.ping("binance_futures", max_age=0)
            mgr.ping("binance_futures", max_age=0)
        assert mock_get.call_count == 2

    def test_ping_network_exception_returns_none(self, iso_state):
        mgr = ConnectionManager()
        with patch("requests.get", side_effect=Exception("timeout")):
            assert mgr.ping("binance_futures", max_age=0) is None

    def test_ping_non_200_returns_none(self, iso_state):
        r = MagicMock()
        r.status_code = 503
        mgr = ConnectionManager()
        with patch("requests.get", return_value=r):
            assert mgr.ping("binance_futures", max_age=0) is None


# ────────────────────────────────────────────────────────────
# status_summary
# ────────────────────────────────────────────────────────────

class TestStatusSummary:
    def test_shape(self, iso_state):
        mgr = ConnectionManager()
        s = mgr.status_summary()
        assert set(s.keys()) == {"market", "market_key", "connected", "n_connected"}

    def test_market_label_matches_active(self, iso_state):
        mgr = ConnectionManager()
        assert mgr.status_summary()["market_key"] == "crypto_futures"
        assert mgr.status_summary()["market"] == MARKETS["crypto_futures"]["label"]

    def test_connected_list_reflects_state(self, iso_state):
        mgr = ConnectionManager()
        mgr.set_connected("binance_futures", True)
        summary = mgr.status_summary()
        assert "binance_futures" in summary["connected"]

    def test_n_connected_counts_default_public_apis(self, iso_state):
        """Default: cftc/fred/yahoo são public APIs marcadas como connected=True."""
        mgr = ConnectionManager()
        s = mgr.status_summary()
        # 3 public APIs always 'connected' in defaults
        assert s["n_connected"] >= 3

    def test_unknown_active_market_returns_unknown_label(self, iso_state):
        mgr = ConnectionManager()
        mgr.state["active_market"] = "nonexistent_market"
        s = mgr.status_summary()
        assert s["market"] == "UNKNOWN"


# ────────────────────────────────────────────────────────────
# constantes de módulo
# ────────────────────────────────────────────────────────────

class TestModuleConstants:
    def test_markets_has_expected_keys(self):
        expected = {"crypto_futures", "crypto_spot", "forex", "equities",
                    "commodities", "indices", "onchain"}
        assert expected.issubset(MARKETS.keys())

    def test_default_state_has_active_market(self):
        assert "active_market" in DEFAULT_STATE
        assert DEFAULT_STATE["active_market"] in MARKETS
