"""Contract tests for core.portfolio_monitor — account snapshots + paper state.

PAPER_STATE_FILE is redirected to tmp_path via monkeypatch on the class
attribute for isolation.

Covers:
- has_keys: paper always True; missing keys.json → False; placeholder
  "COLE_AQUI" treated as missing; valid keys → True
- status: paper → "paper"; no_keys → "no_keys"; valid → "live"
- _normalise_positions: amt=0 skipped; side LONG/SHORT; malformed
  values fall back to 0.0
- paper_state_load: missing file bootstraps default state; subsequent
  load returns same state
- paper_set_balance: deposit (amount > current) bumps total_deposits;
  withdraw (amount < current) bumps total_withdraws; adjust logs event
- paper_reset: returns to default state, overwriting existing
- _load_paper: builds snapshot with expected keys + today_pnl from
  today's history entries
- refresh(no_keys): returns error snapshot, cached
- get_cached / all_cached / clear: basic cache ops
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from core.portfolio_monitor import PortfolioMonitor


@pytest.fixture
def isolated_paper(tmp_path, monkeypatch):
    """Redirect PAPER_STATE_FILE to a tmp_path file."""
    p = tmp_path / "paper_state.json"
    monkeypatch.setattr(PortfolioMonitor, "PAPER_STATE_FILE", p)
    return p


@pytest.fixture
def keys_file(tmp_path):
    def _write(payload: dict) -> Path:
        p = tmp_path / "keys.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        return p
    return _write


# ────────────────────────────────────────────────────────────
# has_keys / status
# ────────────────────────────────────────────────────────────

class TestHasKeys:
    def test_paper_always_has_keys(self, tmp_path):
        pm = PortfolioMonitor(keys_path=tmp_path / "nonexistent.json")
        assert pm.has_keys("paper") is True

    def test_missing_file_no_keys(self, tmp_path):
        pm = PortfolioMonitor(keys_path=tmp_path / "nonexistent.json")
        assert pm.has_keys("testnet") is False

    def test_placeholder_treated_as_missing(self, keys_file):
        path = keys_file({"testnet": {
            "api_key": "COLE_AQUI_SUA_KEY", "api_secret": "secret",
        }})
        pm = PortfolioMonitor(keys_path=path)
        assert pm.has_keys("testnet") is False

    def test_valid_keys_detected(self, keys_file):
        path = keys_file({"testnet": {
            "api_key": "real_key_abc", "api_secret": "real_secret_xyz",
        }})
        pm = PortfolioMonitor(keys_path=path)
        assert pm.has_keys("testnet") is True

    def test_empty_secret_no_keys(self, keys_file):
        path = keys_file({"testnet": {"api_key": "k", "api_secret": ""}})
        pm = PortfolioMonitor(keys_path=path)
        assert pm.has_keys("testnet") is False


class TestStatus:
    def test_paper_status(self, tmp_path):
        pm = PortfolioMonitor(keys_path=tmp_path / "nope.json")
        assert pm.status("paper") == "paper"

    def test_no_keys_status(self, tmp_path):
        pm = PortfolioMonitor(keys_path=tmp_path / "nope.json")
        assert pm.status("testnet") == "no_keys"

    def test_live_status(self, keys_file):
        path = keys_file({"live": {
            "api_key": "k" * 20, "api_secret": "s" * 20,
        }})
        pm = PortfolioMonitor(keys_path=path)
        assert pm.status("live") == "live"


# ────────────────────────────────────────────────────────────
# _normalise_positions
# ────────────────────────────────────────────────────────────

class TestNormalisePositions:
    def test_skips_zero_amount(self):
        raw = [
            {"symbol": "A", "positionAmt": "0"},
            {"symbol": "B", "positionAmt": "1.0", "entryPrice": "100",
             "markPrice": "110", "unRealizedProfit": "10", "leverage": "3"},
        ]
        out = PortfolioMonitor._normalise_positions(raw)
        assert len(out) == 1
        assert out[0]["symbol"] == "B"

    def test_sides_mapped_correctly(self):
        raw = [
            {"symbol": "LONG_SYM",  "positionAmt": "5",
             "entryPrice": "1", "markPrice": "1", "unRealizedProfit": "0", "leverage": "1"},
            {"symbol": "SHORT_SYM", "positionAmt": "-5",
             "entryPrice": "1", "markPrice": "1", "unRealizedProfit": "0", "leverage": "1"},
        ]
        out = PortfolioMonitor._normalise_positions(raw)
        sides = {p["symbol"]: p["side"] for p in out}
        assert sides == {"LONG_SYM": "LONG", "SHORT_SYM": "SHORT"}

    def test_malformed_numeric_falls_back_to_zero(self):
        raw = [{"symbol": "X", "positionAmt": "1.0",
                "entryPrice": "NaN", "markPrice": None,
                "unRealizedProfit": "bad", "leverage": "xyz"}]
        out = PortfolioMonitor._normalise_positions(raw)
        # All numeric fields fallback to 0.0 on parse failure
        assert out[0]["entry"] == 0.0
        assert out[0]["mark"] == 0.0
        assert out[0]["pnl"] == 0.0
        assert out[0]["leverage"] == 0.0


# ────────────────────────────────────────────────────────────
# Paper state lifecycle
# ────────────────────────────────────────────────────────────

class TestPaperState:
    def test_load_missing_bootstraps_default(self, isolated_paper):
        assert not isolated_paper.exists()
        state = PortfolioMonitor.paper_state_load()
        assert isolated_paper.exists()
        # Default fields
        assert state["current_balance"] == PortfolioMonitor.PAPER_DEFAULT_BALANCE
        assert state["trades"] == []
        assert state["equity_curve"] == [PortfolioMonitor.PAPER_DEFAULT_BALANCE]

    def test_save_and_reload(self, isolated_paper):
        state = PortfolioMonitor.paper_state_load()
        state["current_balance"] = 5_000.0
        PortfolioMonitor.paper_state_save(state)
        reloaded = PortfolioMonitor.paper_state_load()
        assert reloaded["current_balance"] == 5_000.0

    def test_set_balance_deposit(self, isolated_paper):
        PortfolioMonitor.paper_state_load()
        state = PortfolioMonitor.paper_set_balance(15_000.0, note="test deposit")
        assert state["current_balance"] == 15_000.0
        # Δ = +5000 → total_deposits increased
        assert state["total_deposits"] > PortfolioMonitor.PAPER_DEFAULT_BALANCE
        last_event = state["history"][-1]
        assert last_event["type"] == "deposit"

    def test_set_balance_withdraw(self, isolated_paper):
        PortfolioMonitor.paper_state_load()
        state = PortfolioMonitor.paper_set_balance(5_000.0)
        assert state["current_balance"] == 5_000.0
        assert state["total_withdraws"] > 0
        last_event = state["history"][-1]
        assert last_event["type"] == "withdraw"

    def test_set_balance_same_amount_is_adjust(self, isolated_paper):
        PortfolioMonitor.paper_state_load()
        state = PortfolioMonitor.paper_set_balance(
            PortfolioMonitor.PAPER_DEFAULT_BALANCE)
        last_event = state["history"][-1]
        assert last_event["type"] == "adjust"

    def test_reset_clears_state(self, isolated_paper):
        PortfolioMonitor.paper_state_load()
        PortfolioMonitor.paper_set_balance(99_000.0)
        state = PortfolioMonitor.paper_reset()
        assert state["current_balance"] == PortfolioMonitor.PAPER_DEFAULT_BALANCE
        assert len(state["history"]) == 1  # just the init entry


# ────────────────────────────────────────────────────────────
# _load_paper
# ────────────────────────────────────────────────────────────

class TestLoadPaper:
    def test_paper_snapshot_has_expected_keys(self, isolated_paper):
        pm = PortfolioMonitor(keys_path="nowhere.json")
        snap = pm._load_paper()
        for key in ("mode", "status", "balance", "equity", "positions",
                    "recent_trades", "history", "summary"):
            assert key in snap
        assert snap["mode"] == "paper"
        assert snap["status"] == "paper"

    def test_today_pnl_sums_today_history(self, isolated_paper):
        # Seed state with a today-trade and an old-trade
        today = datetime.now().date().isoformat()
        yesterday = (datetime.now() - timedelta(days=1)).isoformat()
        PortfolioMonitor.paper_state_save({
            "current_balance": 10_000, "equity": 10_000,
            "positions": [], "trades": [],
            "equity_curve": [10_000],
            "history": [
                {"ts": f"{today}T10:00:00", "type": "trade", "amount": 50},
                {"ts": f"{today}T11:00:00", "type": "realized_pnl", "amount": -20},
                {"ts": yesterday, "type": "trade", "amount": 999},
            ],
            "total_deposits": 10_000, "total_withdraws": 0,
            "realized_pnl": 0, "unrealized_pnl": 0,
            "initial_balance": 10_000,
        })
        pm = PortfolioMonitor(keys_path="nowhere.json")
        snap = pm._load_paper()
        # today_pnl = 50 + (-20) = 30
        assert snap["today_pnl"] == pytest.approx(30.0)


# ────────────────────────────────────────────────────────────
# refresh + cache
# ────────────────────────────────────────────────────────────

class TestRefreshCache:
    def test_refresh_no_keys_caches_error_snapshot(self, tmp_path):
        pm = PortfolioMonitor(keys_path=tmp_path / "missing.json")
        snap = pm.refresh("testnet")
        assert snap["status"] == "no_keys"
        assert pm.get_cached("testnet") == snap

    def test_get_cached_returns_none_when_empty(self, tmp_path):
        pm = PortfolioMonitor(keys_path=tmp_path / "missing.json")
        assert pm.get_cached("live") is None

    def test_all_cached_returns_copy(self, tmp_path):
        pm = PortfolioMonitor(keys_path=tmp_path / "missing.json")
        pm.refresh("testnet")
        snapshot_of_cache = pm.all_cached()
        # Mutating the returned dict should not affect live cache
        snapshot_of_cache["testnet"] = None
        assert pm.get_cached("testnet") is not None

    def test_clear_empties_cache(self, tmp_path):
        pm = PortfolioMonitor(keys_path=tmp_path / "missing.json")
        pm.refresh("testnet")
        pm.clear()
        assert pm.all_cached() == {}
