import json
import shutil
import uuid
from pathlib import Path

from core.fixture_capture import (
    PHASE_C_CAPTURE_SCHEMA_VERSION,
    PHASE_C_MANIFEST_SCHEMA_VERSION,
    capture_envelope,
    capture_manifest,
    write_capture,
    write_capture_manifest,
)


ROOT = Path(__file__).resolve().parent.parent
TMP_ROOT = ROOT / "tests" / "fixtures" / "phase_c" / "_tmp_capture_tests"


def _fresh_tmp_dir() -> Path:
    path = TMP_ROOT / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=False)
    return path


def test_capture_envelope_contains_versioned_metadata():
    payload = {"x": 1}
    env = capture_envelope(
        surface="live_check_signal",
        fixture_name="case_001",
        payload=payload,
        source={"engine": "live"},
        notes="authentic sample",
    )

    assert env["schema_version"] == PHASE_C_CAPTURE_SCHEMA_VERSION
    assert env["surface"] == "live_check_signal"
    assert env["fixture_name"] == "case_001"
    assert env["source"] == {"engine": "live"}
    assert env["notes"] == "authentic sample"
    assert env["payload"] == payload
    assert "captured_at" in env


def test_write_capture_writes_expected_path_and_payload():
    tmp_dir = _fresh_tmp_dir()
    try:
        out = write_capture(
            surface="live_check_signal",
            fixture_name="case_002",
            payload={"symbol": "BTCUSDT"},
            source={"engine": "live"},
            capture_dir=tmp_dir,
        )

        assert out == tmp_dir / "live_check_signal" / "case_002.json"
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["schema_version"] == PHASE_C_CAPTURE_SCHEMA_VERSION
        assert data["surface"] == "live_check_signal"
        assert data["fixture_name"] == "case_002"
        assert data["payload"] == {"symbol": "BTCUSDT"}
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_capture_manifest_contains_versioned_entries():
    manifest = capture_manifest(
        [{"surface": "live_check_signal", "status": "capturable"}],
        generated_by="pytest",
    )

    assert manifest["schema_version"] == PHASE_C_MANIFEST_SCHEMA_VERSION
    assert manifest["generated_by"] == "pytest"
    assert manifest["entries"] == [{"surface": "live_check_signal", "status": "capturable"}]
    assert "generated_at" in manifest


def test_write_capture_manifest_writes_json():
    tmp_dir = _fresh_tmp_dir()
    try:
        path = tmp_dir / "capture_manifest.json"
        out = write_capture_manifest(
            [{"surface": "backtest_scan_symbol", "status": "capture_required"}],
            generated_by="pytest",
            path=path,
        )

        assert out == path
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["schema_version"] == PHASE_C_MANIFEST_SCHEMA_VERSION
        assert data["generated_by"] == "pytest"
        assert data["entries"][0]["surface"] == "backtest_scan_symbol"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
