"""Contract tests for core.engine_picker — utility helpers.

The module is 1400 lines of Tkinter UI rendering + 5 pure helpers. The
UI paths are skipped (tkinter runtime, not unit-testable cleanly); the
pure helpers are the load-bearing contract:

- _bright: lightens/darkens hex color by factor; invalid → unchanged
- _format_track_subtitle: formats subtitle from best_config brief;
  falls back to tagline; handles missing/partial data
- EngineTrack dataclass: defaults + shape
- build_tracks_from_registry: maps slug→group via DEFAULT_GROUPS (or
  override); sorts by group order then TRACK_SORT_WEIGHT; falls back
  to alpha
- _safe: swallows any exception from the wrapped thunk
"""
from __future__ import annotations

import json
import os

import pytest

import core.engine_picker as ep
from core.engine_picker import (
    DEFAULT_GROUPS,
    GROUP_ORDER,
    MODULE_INFO,
    TRACK_SORT_WEIGHT,
    EngineTrack,
    _bright,
    _format_track_subtitle,
    _safe,
    _stage_badge,
    build_tracks_from_registry,
)
from config.engines import ENGINE_GROUPS, ENGINE_SORT_WEIGHTS


# ────────────────────────────────────────────────────────────
# _bright
# ────────────────────────────────────────────────────────────

class TestBright:
    def test_brightens_with_factor_gt_one(self):
        out = _bright("#808080", factor=1.5)
        # 128 * 1.5 = 192 → #c0c0c0
        assert out == "#c0c0c0"

    def test_darkens_with_factor_lt_one(self):
        out = _bright("#808080", factor=0.5)
        assert out == "#404040"

    def test_clamps_at_255(self):
        out = _bright("#ffffff", factor=2.0)
        assert out == "#ffffff"

    def test_clamps_at_zero(self):
        out = _bright("#000000", factor=-1.0)
        assert out == "#000000"

    def test_invalid_hex_returned_unchanged(self):
        assert _bright("not-a-color") == "not-a-color"

    def test_default_factor_brightens(self):
        # factor=1.2 default → each channel multiplied
        out = _bright("#808080")
        # 128 * 1.2 = 153.6 → 153 → 0x99
        assert out == "#999999"


# ────────────────────────────────────────────────────────────
# _format_track_subtitle
# ────────────────────────────────────────────────────────────

class TestFormatTrackSubtitle:
    def _track(self, tagline: str = "") -> EngineTrack:
        return EngineTrack(slug="x", name="X", tagline=tagline)

    def test_no_brief_falls_back_to_tagline(self):
        t = self._track(tagline="momentum engine")
        assert _format_track_subtitle(None, t) == "momentum engine"

    def test_no_brief_no_tagline_is_empty(self):
        t = self._track(tagline="")
        assert _format_track_subtitle(None, t) == ""

    def test_tagline_truncated_at_44_chars(self):
        long = "a" * 100
        t = self._track(tagline=long)
        assert len(_format_track_subtitle(None, t)) == 44

    def test_brief_tf_and_sharpe_formatted(self):
        bc = {"TF": "15m", "Sharpe val": "4.43"}
        out = _format_track_subtitle(bc, self._track())
        assert "15m" in out
        assert "Sh 4.43" in out

    def test_brief_status_edge_tag(self):
        bc = {"TF": "1h", "Sharpe val": "2.0", "Status": "✓ passed"}
        out = _format_track_subtitle(bc, self._track())
        assert "EDGE" in out

    def test_brief_status_marginal_tag(self):
        bc = {"TF": "1h", "Status": "⚠ marginal"}
        out = _format_track_subtitle(bc, self._track())
        assert "MARG" in out

    def test_brief_status_no_edge_tag(self):
        bc = {"TF": "1h", "Status": "✗ failed"}
        out = _format_track_subtitle(bc, self._track())
        assert "NO-EDGE" in out

    def test_brief_parts_joined_with_middle_dot(self):
        bc = {"TF": "15m", "Sharpe val": "4.0", "Status": "✓"}
        out = _format_track_subtitle(bc, self._track())
        assert " · " in out


# ────────────────────────────────────────────────────────────
# EngineTrack dataclass
# ────────────────────────────────────────────────────────────

class TestEngineTrack:
    def test_required_fields_only(self):
        t = EngineTrack(slug="x", name="X")
        assert t.group == "ENGINES"
        assert t.stage == "research"
        assert t.status == "idle"
        assert t.sharpe is None
        assert t.brief is None

    def test_all_optional_fields_accepted(self):
        t = EngineTrack(
            slug="x", name="X", group="BACKTEST",
            sharpe=2.5, win_rate=0.6, regime="BULL",
            brief={"philosophy": "test"},
        )
        assert t.sharpe == 2.5
        assert t.regime == "BULL"
        assert t.brief == {"philosophy": "test"}


# ────────────────────────────────────────────────────────────
# build_tracks_from_registry
# ────────────────────────────────────────────────────────────

class TestBuildTracksFromRegistry:
    def test_empty_registry_returns_empty_list(self):
        assert build_tracks_from_registry({}) == []

    def test_uses_default_groups(self):
        reg = {"citadel": {"display": "CITADEL", "desc": "momentum"}}
        tracks = build_tracks_from_registry(reg)
        assert tracks[0].group == "BACKTEST"
        assert tracks[0].slug == "citadel"
        assert tracks[0].name == "CITADEL"
        assert tracks[0].tagline == "momentum"

    def test_unknown_slug_falls_to_engines_group(self):
        reg = {"madeup": {"display": "Made Up"}}
        tracks = build_tracks_from_registry(reg)
        assert tracks[0].group == "ENGINES"

    def test_custom_groups_override(self):
        reg = {"citadel": {"display": "C"}}
        tracks = build_tracks_from_registry(reg, groups={"citadel": "CUSTOM"})
        assert tracks[0].group == "CUSTOM"

    def test_sort_order_by_group_then_weight(self):
        # citadel (BACKTEST, weight 10) should come before live (LIVE, weight 80)
        # even though "live" is alphabetically earlier in some orderings.
        reg = {
            "live":      {"display": "LIVE"},
            "citadel":   {"display": "CITADEL"},
            "janestreet": {"display": "JS"},
            "aqr":       {"display": "AQR"},
        }
        tracks = build_tracks_from_registry(reg)
        slugs = [t.slug for t in tracks]
        # Group order: BACKTEST → LIVE → TOOLS
        assert slugs.index("citadel") < slugs.index("live")
        assert slugs.index("live")    < slugs.index("aqr")
        # Within LIVE: weight(live=80) < weight(janestreet=90)
        assert slugs.index("live") < slugs.index("janestreet")

    def test_callbacks_invoked_per_slug(self):
        reg = {"citadel": {"display": "C"}, "live": {"display": "L"}}
        calls: list[str] = []

        def on_run_for(slug, meta):
            calls.append(slug)
            return lambda: None

        build_tracks_from_registry(reg, on_run_for=on_run_for)
        assert sorted(calls) == ["citadel", "live"]


# ────────────────────────────────────────────────────────────
# Module metadata sanity
# ────────────────────────────────────────────────────────────

class TestModuleMetadata:
    def test_picker_defaults_follow_canonical_engine_registry(self):
        assert DEFAULT_GROUPS == ENGINE_GROUPS
        assert TRACK_SORT_WEIGHT == ENGINE_SORT_WEIGHTS

    def test_default_groups_only_uses_known_groups(self):
        assert set(DEFAULT_GROUPS.values()) <= set(GROUP_ORDER)

    def test_sort_weight_keys_match_default_groups(self):
        # Every slug with a group should have a sort weight (otherwise
        # ordering falls back to alpha which is a subtle regression).
        missing = set(DEFAULT_GROUPS) - set(TRACK_SORT_WEIGHT)
        assert missing == set()

    def test_module_info_keys_are_subset_of_group_order(self):
        assert set(MODULE_INFO.keys()) <= set(GROUP_ORDER)

    def test_registry_metadata_can_drive_group_and_sort_without_override(self):
        reg = {
            "zeta": {"display": "ZETA", "module": "LIVE", "sort_weight": 5},
            "alpha": {"display": "ALPHA", "module": "BACKTEST", "sort_weight": 50},
        }
        tracks = build_tracks_from_registry(reg)
        assert [t.slug for t in tracks] == ["alpha", "zeta"]

    def test_registry_metadata_carries_stage(self):
        reg = {
            "millennium": {
                "display": "MILLENNIUM",
                "module": "BACKTEST",
                "sort_weight": 60,
                "stage": "bootstrap_staging",
            }
        }
        tracks = build_tracks_from_registry(reg)
        assert tracks[0].stage == "bootstrap_staging"


class TestStageBadge:
    def test_known_stage_uses_registry_style(self):
        label, _color = _stage_badge("bootstrap_staging")
        assert label == "BOOTSTRAP"

    def test_unknown_stage_falls_back_to_uppercase(self):
        label, _color = _stage_badge("shadow")
        assert label == "SHADOW"


# ────────────────────────────────────────────────────────────
# _safe
# ────────────────────────────────────────────────────────────

class TestSafe:
    def test_swallows_exception(self):
        def boom():
            raise RuntimeError("should be swallowed")
        # Does not raise
        _safe(boom)

    def test_runs_successful_callable(self):
        flag = []
        _safe(lambda: flag.append(1))
        assert flag == [1]


@pytest.fixture(autouse=True)
def _clear_live_fs_cache():
    ep.clear_live_fs_cache()
    yield
    ep.clear_live_fs_cache()


class TestLiveFsHelpers:
    def test_latest_live_run_dir_uses_ttl_cache(self, tmp_path, monkeypatch):
        repo_file = tmp_path / "core" / "ops" / "engine_picker.py"
        repo_file.parent.mkdir(parents=True)
        repo_file.touch()
        monkeypatch.setattr(ep, "__file__", str(repo_file))
        repo_root = repo_file.resolve().parent.parent.parent
        now = {"value": 100.0}
        monkeypatch.setattr(ep.time, "monotonic", lambda: now["value"])

        eng_dir = repo_root / "data" / "live"
        older = eng_dir / "run_old"
        newer = eng_dir / "run_new"
        older.mkdir(parents=True)
        newer.mkdir(parents=True)
        older_ts = 1_700_000_000
        newer_ts = older_ts + 10
        os.utime(older, (older_ts, older_ts))
        os.utime(newer, (newer_ts, newer_ts))

        assert ep._latest_live_run_dir("live") == newer

        newest = eng_dir / "run_latest"
        newest.mkdir()
        latest_ts = newer_ts + 10
        os.utime(newest, (latest_ts, latest_ts))
        assert ep._latest_live_run_dir("live") == newer

        now["value"] += ep._LIVE_FS_CACHE_TTL_S + 0.1
        assert ep._latest_live_run_dir("live") == newest

    def test_load_live_log_tails_last_lines_and_uses_cache(self, tmp_path, monkeypatch):
        repo_file = tmp_path / "core" / "ops" / "engine_picker.py"
        repo_file.parent.mkdir(parents=True)
        repo_file.touch()
        monkeypatch.setattr(ep, "__file__", str(repo_file))
        repo_root = repo_file.resolve().parent.parent.parent
        now = {"value": 200.0}
        monkeypatch.setattr(ep.time, "monotonic", lambda: now["value"])

        log_path = repo_root / "data" / "live" / "run_001" / "logs" / "live.log"
        log_path.parent.mkdir(parents=True)
        log_path.write_text("".join(f"line {i}\n" for i in range(1, 8)), encoding="utf-8")

        found, tail = ep._load_live_log("live", n_lines=3)
        assert found == log_path
        assert tail == "line 5\nline 6\nline 7\n"

        log_path.write_text("mutated\n", encoding="utf-8")
        _, cached_tail = ep._load_live_log("live", n_lines=3)
        assert cached_tail == "line 5\nline 6\nline 7\n"

        now["value"] += ep._LIVE_FS_CACHE_TTL_S + 0.1
        _, fresh_tail = ep._load_live_log("live", n_lines=3)
        assert fresh_tail == "mutated\n"

    def test_load_live_positions_normalizes_dict_payload(self, tmp_path, monkeypatch):
        repo_file = tmp_path / "core" / "ops" / "engine_picker.py"
        repo_file.parent.mkdir(parents=True)
        repo_file.touch()
        monkeypatch.setattr(ep, "__file__", str(repo_file))
        repo_root = repo_file.resolve().parent.parent.parent

        positions_path = repo_root / "data" / "live" / "run_001" / "state" / "positions.json"
        positions_path.parent.mkdir(parents=True)
        positions_path.write_text(
            json.dumps(
                {
                    "BTCUSDT": {"side": "LONG", "qty": 1},
                    "ETHUSDT": 2,
                }
            ),
            encoding="utf-8",
        )

        positions = ep._load_live_positions("bridgewater")
        assert positions == [
            {"symbol": "BTCUSDT", "side": "LONG", "qty": 1},
            {"symbol": "ETHUSDT", "value": 2},
        ]
