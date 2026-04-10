import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

@pytest.fixture
def tmp_run(tmp_path):
    run = tmp_path / "data" / "arbitrage" / "2026-01-01_0000"
    (run / "state").mkdir(parents=True)
    (run / "logs").mkdir()
    (run / "reports").mkdir()
    return run
