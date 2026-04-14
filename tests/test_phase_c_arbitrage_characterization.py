import asyncio
import json
from pathlib import Path

from engines.janestreet import omega_score, scan_all


ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "phase_c" / "arbitrage"


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class _FakeVenue:
    def __init__(self, name, has_spot, cost, funding, prices, volumes, disabled=False):
        self.name = name
        self.has_spot = has_spot
        self.cost = cost
        self.funding = funding
        self.prices = prices
        self.volumes = volumes
        self._disabled = disabled

    async def safe_fetch(self):
        return None


def _normalize_opp(opp: dict) -> dict:
    return {
        "sym": opp["sym"],
        "type": opp["type"],
        "v_a": opp["v_a"],
        "v_b": opp["v_b"],
        "fr_a": round(float(opp["fr_a"]), 6),
        "fr_b": round(float(opp["fr_b"]), 6),
        "spread": round(float(opp["spread"]), 6),
        "px_spread": round(float(opp["px_spread"]), 5),
        "apr": round(float(opp["apr"]), 4),
        "lev_apr": round(float(opp["lev_apr"]), 4),
        "omega": round(float(opp["omega"]), 4),
        "edge": opp["edge"],
        "vol": int(opp["vol"]),
    }


def test_omega_score_matches_snapshot_cases():
    expected = _load_json(FIXTURES / "omega_score_snapshot.json")
    actual = {
        "negative_spread": omega_score(-0.001, 5_000_000, 5_000_000, 0.0004, 0.0004),
        "illiquid": omega_score(0.002, 2_000_000, 5_000_000, 0.0004, 0.0004),
        "wide_edge": omega_score(0.0022, 7_000_000, 8_000_000, 0.0006, 0.00055, 0.003960396039604017),
        "spot_perp_like": omega_score(0.0012, 10_000_000, 7_000_000, 0.0004, 0.0006, 0),
    }

    assert actual == expected


def test_scan_all_matches_ranked_snapshot():
    venues = [
        _FakeVenue(
            "binance",
            True,
            0.0004,
            {"ETHUSDT": 0.0008},
            {"ETHUSDT": 100.0},
            {"ETHUSDT": 10_000_000},
        ),
        _FakeVenue(
            "bybit",
            False,
            0.00055,
            {"ETHUSDT": -0.0010},
            {"ETHUSDT": 100.6},
            {"ETHUSDT": 8_000_000},
        ),
        _FakeVenue(
            "gate",
            False,
            0.0006,
            {"ETHUSDT": 0.0012},
            {"ETHUSDT": 101.0},
            {"ETHUSDT": 7_000_000},
        ),
    ]

    opps, active = asyncio.run(scan_all(venues))
    expected = _load_json(FIXTURES / "scan_all_snapshot.json")
    actual = {
        "active": [venue.name for venue in active],
        "opportunities": [_normalize_opp(opp) for opp in opps],
    }

    assert actual == expected
