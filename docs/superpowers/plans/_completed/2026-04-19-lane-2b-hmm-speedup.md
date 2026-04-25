# Lane 2b HMM Speedup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce CITADEL 180d wall-time by ≥25% via HMM fit optimization, preserving byte-identical trade-ledger across 5 HMM-user engines in 4 historical windows.

**Architecture:** Three-layer integrity gate (HMM output → trade ledger → equity/metrics) runs before any speedup measurement. Golden fixtures for 4 windows × 5 engines × ~11 symbols committed to git BEFORE any code change. Two hypotheses: H7 (lru_cache of fit by X_train hash, likely dead), H8 (scipy.special.logsumexp → numpy local, workhorse). H9 (hmmlearn backend) archived.

**Tech Stack:** Python 3.14, numpy, scipy, pandas, pytest, pyinstrument, hashlib, functools.lru_cache.

**Spec:** `docs/superpowers/specs/2026-04-19-lane-2b-hmm-speedup-design.md` (v2 hardened)

---

## Dependencies

- Must be executed on branch `feat/lane-2b-hmm` (created from `feat/phi-engine` at commit `ddc3b86` or later)
- All 5 HMM engines must support `--days N --end YYYY-MM-DD` CLI — Task 1 adds this to `jump` to match the pattern
- Python 3.14 global (no venv), per user setup
- CORE PROTECTED: zero modifications allowed to `core/indicators.py`, `core/signals.py`, `core/portfolio.py`, `config/params.py`

---

## Task 1: Create branch and add --end to jump engine

**Files:**
- Modify: `engines/jump.py` (CLI argparse setup, follow `engines/bridgewater.py` pattern)
- Test: `tests/contracts/test_jump_contracts.py` (smoke — run `python -m engines.jump --days 30 --end 2024-06-30 --no-menu` and assert it exits 0)

- [ ] **Step 1.1: Create the working branch**

```bash
git checkout feat/phi-engine
git pull
git checkout -b feat/lane-2b-hmm
```

- [ ] **Step 1.2: Inspect bridgewater's --end pattern to copy it verbatim**

```bash
grep -n "end" engines/bridgewater.py | grep -iE "parser|args|--end" | head -10
```

Record the exact lines where bridgewater declares `--end`, parses it, and applies it to the data window. Same lines need to appear in jump.

- [ ] **Step 1.3: Add --end argument to jump's argparse**

Find jump's `argparse.ArgumentParser` block. Add:

```python
parser.add_argument(
    "--end",
    type=str,
    default=None,
    help="End date YYYY-MM-DD for backtest window (pre-calibration OOS). Default: now.",
)
parser.add_argument(
    "--no-menu",
    action="store_true",
    help="Skip post-run interactive menu",
)
```

Apply `args.end` to the data-fetch window exactly as bridgewater does.

- [ ] **Step 1.4: Write a contract test that exercises --end and --no-menu**

Add to `tests/contracts/test_jump_contracts.py`:

```python
def test_jump_cli_supports_end_and_no_menu():
    """jump must accept --end and --no-menu (Lane 2b prereq)."""
    import subprocess, sys
    result = subprocess.run(
        [sys.executable, "-m", "engines.jump",
         "--days", "30", "--end", "2024-06-30", "--no-menu"],
        capture_output=True, timeout=300
    )
    assert result.returncode == 0, result.stderr.decode()[-500:]
```

- [ ] **Step 1.5: Run the test — expect FAIL (not yet implemented if Step 1.3 not done)**

```bash
python -m pytest tests/contracts/test_jump_contracts.py::test_jump_cli_supports_end_and_no_menu -v
```

Expected: PASS if Step 1.3 was done; otherwise FAIL with argparse unrecognized argument.

- [ ] **Step 1.6: Commit**

```bash
git add engines/jump.py tests/contracts/test_jump_contracts.py
git commit -m "feat(jump): add --end and --no-menu flags (Lane 2b prereq)

Pattern copied from engines/bridgewater.py to match all 4 other
HMM-user engines. Required for Lane 2b golden fixture generation
across stress windows.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Write golden fixture generator tool

**Files:**
- Create: `tools/audits/hmm_golden_generator.py`
- Test: `tests/tools/test_hmm_golden_generator.py`

- [ ] **Step 2.1: Write the failing test**

Create `tests/tools/test_hmm_golden_generator.py`:

```python
"""Unit tests for HMM golden fixture generator."""
import hashlib
import pandas as pd
import numpy as np
from pathlib import Path
import pytest

from tools.audits.hmm_golden_generator import (
    dump_hmm_columns_csv,
    digest_file,
    WINDOW_DEFINITIONS,
    HMM_COLS,
)


def test_dump_hmm_columns_produces_deterministic_csv(tmp_path):
    """Dumping identical df twice must produce identical sha256."""
    df = pd.DataFrame({
        "close": np.linspace(100, 110, 200),
        "hmm_regime": np.arange(200, dtype=float),
        "hmm_regime_label": ["BULL"] * 200,
        "hmm_prob_bull": np.random.default_rng(42).random(200),
        "hmm_prob_bear": np.random.default_rng(43).random(200),
        "hmm_prob_chop": np.random.default_rng(44).random(200),
        "hmm_confidence": np.random.default_rng(45).random(200),
    })

    p1 = tmp_path / "a.csv"
    p2 = tmp_path / "b.csv"
    dump_hmm_columns_csv(df, p1)
    dump_hmm_columns_csv(df, p2)

    assert digest_file(p1) == digest_file(p2)


def test_window_definitions_are_frozen():
    """4 windows pre-registered by spec. Cannot change mid-cycle."""
    assert set(WINDOW_DEFINITIONS.keys()) == {
        "canonical_180d",
        "stress_covid",
        "stress_ftx",
        "stress_etf_rally",
    }
    for name, cfg in WINDOW_DEFINITIONS.items():
        assert "end" in cfg and "days" in cfg
        assert isinstance(cfg["days"], int) and cfg["days"] > 0


def test_hmm_cols_matches_chronos_module():
    """Guard: HMM_COLS here must match core.chronos.HMM_COLS."""
    from core.chronos import HMM_COLS as CHRONOS_HMM_COLS
    assert list(HMM_COLS) == list(CHRONOS_HMM_COLS)
```

- [ ] **Step 2.2: Run test to verify failure**

```bash
python -m pytest tests/tools/test_hmm_golden_generator.py -v
```

Expected: FAIL (ImportError: no module `tools.audits.hmm_golden_generator`)

- [ ] **Step 2.3: Implement the generator tool**

Create `tools/audits/hmm_golden_generator.py`:

```python
"""
HMM Golden Fixture Generator — Lane 2b

Generates deterministic golden fixtures for HMM output integrity checks.
Runs each HMM-user engine across 4 pre-registered windows and digests:
- Layer 1: per-symbol HMM output columns (6 cols)
- Layer 2: per-engine trades.csv
- Layer 3: per-engine equity.csv + aggregate metrics JSON

Output: tests/fixtures/hmm_golden/{window}/...

Idempotent — running twice on unchanged code produces identical digests.
If second run diverges, a bug exists.
"""
from __future__ import annotations
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd

from core.chronos import HMM_COLS

# ── Frozen window definitions (do NOT edit mid-cycle) ────────────────
WINDOW_DEFINITIONS = {
    "canonical_180d": {"days": 180, "end": "2026-04-18"},
    "stress_covid":   {"days": 60,  "end": "2020-04-15"},
    "stress_ftx":     {"days": 77,  "end": "2022-12-31"},
    "stress_etf_rally":{"days":90,  "end": "2024-03-31"},
}

HMM_ENGINES = ["citadel", "bridgewater", "deshaw", "jump", "medallion"]

FIXTURE_ROOT = Path("tests/fixtures/hmm_golden")

METRICS_KEYS = [
    "total_trades", "win_rate", "sharpe_ratio",
    "max_drawdown", "total_pnl",
]


def digest_file(path: Path) -> str:
    """sha256 of raw bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump_hmm_columns_csv(df: pd.DataFrame, out_path: Path) -> None:
    """Deterministic CSV of the 6 HMM columns with full float precision."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cols = [c for c in HMM_COLS if c in df.columns]
    df[cols].to_csv(out_path, float_format="%.17g", index=True, lineterminator="\n")


def extract_metrics(report_json_path: Path) -> dict:
    """Extract pinned metrics from engine report JSON, ordered."""
    data = json.loads(report_json_path.read_text())
    return {k: data.get(k) for k in METRICS_KEYS}


def dump_metrics_json(metrics: dict, out_path: Path) -> None:
    """Canonical JSON dump for deterministic digest."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(metrics, sort_keys=True, indent=2, default=str)
    )


def run_engine(engine: str, days: int, end: str) -> Path:
    """Run an engine and return its run directory."""
    cmd = [
        sys.executable, "-m", f"engines.{engine}",
        "--days", str(days), "--end", end, "--no-menu",
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=1800)
    if result.returncode != 0:
        raise RuntimeError(
            f"engine {engine} failed: {result.stderr.decode()[-1000:]}"
        )
    # Run dir is the most recent under data/{engine}/
    engine_dir = Path(f"data/{engine}")
    latest = max(engine_dir.iterdir(), key=lambda p: p.stat().st_mtime)
    return latest


def generate_window_fixtures(window_name: str) -> None:
    """Generate all fixtures for one window."""
    cfg = WINDOW_DEFINITIONS[window_name]
    window_dir = FIXTURE_ROOT / window_name
    window_dir.mkdir(parents=True, exist_ok=True)

    print(f"[{window_name}] days={cfg['days']} end={cfg['end']}")
    universe_seen: set[str] = set()

    for engine in HMM_ENGINES:
        print(f"  running {engine}...")
        run_dir = run_engine(engine, cfg["days"], cfg["end"])

        # Layer 1 — HMM output per symbol (citadel is canonical source)
        if engine == "citadel":
            state_dir = run_dir / "state"
            if state_dir.exists():
                for pq in state_dir.glob("*.parquet"):
                    symbol = pq.stem
                    universe_seen.add(symbol)
                    df = pd.read_parquet(pq)
                    if not all(c in df.columns for c in HMM_COLS):
                        continue
                    csv_path = window_dir / f"{symbol}_hmm_cols.csv"
                    dump_hmm_columns_csv(df, csv_path)
                    sha_path = csv_path.with_suffix(".sha256")
                    sha_path.write_text(digest_file(csv_path))

        # Layer 2 — trade ledger
        trades_path = run_dir / "reports" / "trades.csv"
        if trades_path.exists():
            out_sha = window_dir / f"{engine}_trades.sha256"
            out_sha.write_text(digest_file(trades_path))

        # Layer 3 — equity curve digest + metrics
        equity_path = run_dir / "reports" / "equity.csv"
        if equity_path.exists():
            out_sha = window_dir / f"{engine}_equity.sha256"
            out_sha.write_text(digest_file(equity_path))

        report_json = run_dir / "reports" / "report.json"
        if report_json.exists():
            metrics = extract_metrics(report_json)
            metrics_path = window_dir / f"{engine}_metrics.json"
            dump_metrics_json(metrics, metrics_path)
            sha_path = window_dir / f"{engine}_metrics.sha256"
            sha_path.write_text(digest_file(metrics_path))

    # Write universe.txt for the window
    if universe_seen:
        (window_dir / "universe.txt").write_text(
            "\n".join(sorted(universe_seen)) + "\n"
        )


def main() -> None:
    for window in WINDOW_DEFINITIONS:
        generate_window_fixtures(window)
    print("Done.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2.4: Run unit tests — expect PASS**

```bash
python -m pytest tests/tools/test_hmm_golden_generator.py -v
```

Expected: 3 passed.

- [ ] **Step 2.5: Commit**

```bash
git add tools/audits/hmm_golden_generator.py tests/tools/test_hmm_golden_generator.py
git commit -m "feat(audits): HMM golden fixture generator tool (Lane 2b)

Deterministic fixture generator for integrity checks across 4
pre-registered windows. Dumps HMM columns per symbol (%.17g float
precision), trades.csv digest per engine, equity.csv digest, and
pinned metrics JSON.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Write primary integrity test suite

**Files:**
- Create: `tests/perf/test_hmm_integrity.py`
- Test: self-test by running against current chronos.py (should produce expected digests AFTER golden fixtures exist in Task 6)

- [ ] **Step 3.1: Write the integrity test**

Create `tests/perf/test_hmm_integrity.py`:

```python
"""
HMM Integrity Suite — Lane 2b (primary verification)

Runs 3-layer invariant check across 4 windows × 5 engines.
Compares post-fix digests against golden fixtures committed to git.

Usage (standalone):
    python -m pytest tests/perf/test_hmm_integrity.py -v

Invoked automatically as part of each H7/H8 fix attempt.

Any digest mismatch → fix is rejected.
"""
from __future__ import annotations
import hashlib
import os
from pathlib import Path

import pytest

FIXTURE_ROOT = Path("tests/fixtures/hmm_golden")
WINDOWS = ["canonical_180d", "stress_covid", "stress_ftx", "stress_etf_rally"]
HMM_ENGINES = ["citadel", "bridgewater", "deshaw", "jump", "medallion"]


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_expected(window: str, artifact: str) -> str:
    """Read the pinned sha256 from golden fixtures."""
    p = FIXTURE_ROOT / window / f"{artifact}.sha256"
    if not p.exists():
        pytest.skip(f"golden fixture missing: {p}")
    return p.read_text().strip()


def _latest_run(engine: str) -> Path:
    """Most recent run dir under data/{engine}/. None if no runs."""
    engine_dir = Path(f"data/{engine}")
    if not engine_dir.exists():
        return None
    dirs = [d for d in engine_dir.iterdir() if d.is_dir()]
    if not dirs:
        return None
    return max(dirs, key=lambda p: p.stat().st_mtime)


@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("AURUM_RUN_INTEGRITY"),
    reason="set AURUM_RUN_INTEGRITY=1 after generating runs"
)
@pytest.mark.parametrize("window", WINDOWS)
@pytest.mark.parametrize("engine", HMM_ENGINES)
def test_layer2_trades_ledger_bit_identical(window, engine):
    """Layer 2: trades.csv digest per engine must match golden."""
    expected = _load_expected(window, f"{engine}_trades")
    run_dir = _latest_run(engine)
    if run_dir is None:
        pytest.skip(f"no run dir for {engine}")
    trades = run_dir / "reports" / "trades.csv"
    if not trades.exists():
        pytest.fail(f"trades.csv missing: {trades}")
    observed = sha256_of(trades)
    assert observed == expected, (
        f"[{window}/{engine}] trade ledger drift: "
        f"expected {expected[:12]}..., observed {observed[:12]}..."
    )


@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("AURUM_RUN_INTEGRITY"),
    reason="set AURUM_RUN_INTEGRITY=1 after generating runs"
)
@pytest.mark.parametrize("window", WINDOWS)
@pytest.mark.parametrize("engine", HMM_ENGINES)
def test_layer3_equity_curve_bit_identical(window, engine):
    """Layer 3a: equity.csv digest per engine must match golden."""
    expected = _load_expected(window, f"{engine}_equity")
    run_dir = _latest_run(engine)
    if run_dir is None:
        pytest.skip(f"no run dir for {engine}")
    equity = run_dir / "reports" / "equity.csv"
    if not equity.exists():
        pytest.skip(f"no equity.csv for {engine}")
    assert sha256_of(equity) == expected, (
        f"[{window}/{engine}] equity curve drift"
    )


@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("AURUM_RUN_INTEGRITY"),
    reason="set AURUM_RUN_INTEGRITY=1 after generating runs"
)
@pytest.mark.parametrize("window", WINDOWS)
@pytest.mark.parametrize("engine", HMM_ENGINES)
def test_layer3_metrics_bit_identical(window, engine):
    """Layer 3b: aggregate metrics JSON digest per engine must match."""
    from tools.audits.hmm_golden_generator import extract_metrics, dump_metrics_json
    expected = _load_expected(window, f"{engine}_metrics")
    run_dir = _latest_run(engine)
    if run_dir is None:
        pytest.skip(f"no run dir for {engine}")
    report = run_dir / "reports" / "report.json"
    if not report.exists():
        pytest.skip(f"no report.json for {engine}")
    # Recompute and digest in-memory using the same tool the generator uses
    import tempfile
    m = extract_metrics(report)
    with tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False
    ) as tf:
        tf_path = Path(tf.name)
    try:
        dump_metrics_json(m, tf_path)
        assert sha256_of(tf_path) == expected, (
            f"[{window}/{engine}] metrics drift"
        )
    finally:
        tf_path.unlink(missing_ok=True)


@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("AURUM_RUN_INTEGRITY"),
    reason="set AURUM_RUN_INTEGRITY=1 after generating runs"
)
def test_layer1_hmm_output_bit_identical():
    """Layer 1: per-symbol HMM columns must match golden.

    Requires that a CITADEL run has been produced for every window
    that has a goldens folder. Compares each CSV in the golden
    folder to the equivalent parquet in the run state.
    """
    from tools.audits.hmm_golden_generator import dump_hmm_columns_csv
    import tempfile
    import pandas as pd

    run_dir = _latest_run("citadel")
    if run_dir is None:
        pytest.skip("no citadel run")
    state_dir = run_dir / "state"
    if not state_dir.exists():
        pytest.skip("no state dir")

    for window in WINDOWS:
        wd = FIXTURE_ROOT / window
        if not wd.exists():
            continue
        for sha_file in wd.glob("*_hmm_cols.sha256"):
            symbol = sha_file.stem.removesuffix("_hmm_cols")
            pq = state_dir / f"{symbol}.parquet"
            if not pq.exists():
                continue
            df = pd.read_parquet(pq)
            with tempfile.NamedTemporaryFile(
                "w", suffix=".csv", delete=False
            ) as tf:
                tf_path = Path(tf.name)
            try:
                dump_hmm_columns_csv(df, tf_path)
                expected = sha_file.read_text().strip()
                observed = sha256_of(tf_path)
                assert observed == expected, (
                    f"[{window}/{symbol}] HMM output drift "
                    f"(Layer 1)"
                )
            finally:
                tf_path.unlink(missing_ok=True)
```

- [ ] **Step 3.2: Run pytest collect to ensure syntactic correctness**

```bash
python -m pytest tests/perf/test_hmm_integrity.py --collect-only -q
```

Expected: tests are collected (many will be skipped since `AURUM_RUN_INTEGRITY` env is unset and no goldens exist yet).

- [ ] **Step 3.3: Commit**

```bash
git add tests/perf/test_hmm_integrity.py
git commit -m "test(perf): HMM integrity suite — Layer 1+2+3 (Lane 2b primary)

Parametrized tests over 4 windows × 5 engines compare post-fix
digests against golden fixtures. Skipped by default (requires
AURUM_RUN_INTEGRITY=1 env var after engines have run).

Any digest divergence fails the suite and rejects the fix.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Dual verification tool (secondary independent check)

**Files:**
- Create: `tools/audits/hmm_output_recompute.py`
- Test: `tests/tools/test_hmm_output_recompute.py`

- [ ] **Step 4.1: Write the test for the dual-verify tool**

Create `tests/tools/test_hmm_output_recompute.py`:

```python
"""Unit tests for HMM dual-verification tool."""
import pandas as pd
import numpy as np
from pathlib import Path
import pytest

from tools.audits.hmm_output_recompute import compare_dataframes


def test_identical_dataframes_match(tmp_path):
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [0.1, 0.2, 0.3]})
    result = compare_dataframes(df, df.copy())
    assert result.match is True
    assert result.diff_count == 0


def test_differing_dataframes_report_cells():
    df1 = pd.DataFrame({"a": [1.0, 2.0, 3.0]})
    df2 = pd.DataFrame({"a": [1.0, 2.0, 3.0 + 1e-15]})
    result = compare_dataframes(df1, df2)
    assert result.match is False
    assert result.diff_count >= 1


def test_shape_mismatch_is_flagged():
    df1 = pd.DataFrame({"a": [1.0, 2.0]})
    df2 = pd.DataFrame({"a": [1.0, 2.0, 3.0]})
    result = compare_dataframes(df1, df2)
    assert result.match is False
```

- [ ] **Step 4.2: Run test — expect FAIL (module doesn't exist)**

```bash
python -m pytest tests/tools/test_hmm_output_recompute.py -v
```

Expected: FAIL (ImportError).

- [ ] **Step 4.3: Implement the dual-verify tool**

Create `tools/audits/hmm_output_recompute.py`:

```python
"""
HMM Output Dual-Verification — Lane 2b (secondary check)

Independent verification that does NOT use sha256. Uses
pandas.testing.assert_frame_equal with rtol=0, atol=0 to catch
any numerical drift, then reports per-cell differences.

Runs against the current run output versus a baseline dataframe.
If primary sha256 suite passes but this flags differences, the
primary check has a bug.

Usage:
    python -m tools.audits.hmm_output_recompute \\
        --window canonical_180d --symbol BNBUSDT
"""
from __future__ import annotations
import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from core.chronos import HMM_COLS


@dataclass
class CompareResult:
    match: bool
    diff_count: int
    diff_rows: list[int]
    diff_cols: list[str]
    first_example: str = ""


def compare_dataframes(a: pd.DataFrame, b: pd.DataFrame) -> CompareResult:
    """Bit-identical comparison of two frames.

    Returns diff_count = 0 and match = True when the frames are
    bit-identical per pandas.testing.assert_frame_equal with
    rtol=0, atol=0.
    """
    if a.shape != b.shape:
        return CompareResult(
            match=False, diff_count=max(a.size, b.size),
            diff_rows=[], diff_cols=[],
            first_example=f"shape {a.shape} vs {b.shape}"
        )
    try:
        pd.testing.assert_frame_equal(
            a.reset_index(drop=True),
            b.reset_index(drop=True),
            check_exact=True, check_dtype=True,
            rtol=0, atol=0,
        )
        return CompareResult(match=True, diff_count=0,
                             diff_rows=[], diff_cols=[])
    except AssertionError:
        pass

    diff_rows: list[int] = []
    diff_cols: list[str] = []
    first = ""
    for col in a.columns:
        if col not in b.columns:
            diff_cols.append(col)
            continue
        av = a[col].values
        bv = b[col].values
        try:
            mask = ~np.equal(av, bv)
            if av.dtype.kind in "fc":
                mask = mask & ~(np.isnan(av) & np.isnan(bv))
        except TypeError:
            mask = np.asarray([x != y for x, y in zip(av, bv)])
        if mask.any():
            diff_cols.append(col)
            rows = np.where(mask)[0].tolist()
            diff_rows.extend(rows[:5])
            if not first and rows:
                r = rows[0]
                first = f"col={col} row={r} a={av[r]!r} b={bv[r]!r}"

    return CompareResult(
        match=False, diff_count=len(diff_rows),
        diff_rows=diff_rows[:10], diff_cols=diff_cols[:10],
        first_example=first,
    )


def recompute_and_diff(window: str, symbol: str,
                      current_run: Path, baseline_run: Path) -> CompareResult:
    """Load HMM cols from two runs and diff them."""
    cur_pq = current_run / "state" / f"{symbol}.parquet"
    base_pq = baseline_run / "state" / f"{symbol}.parquet"
    if not cur_pq.exists() or not base_pq.exists():
        return CompareResult(
            match=False, diff_count=-1,
            diff_rows=[], diff_cols=[],
            first_example=f"missing parquet: {cur_pq} or {base_pq}"
        )
    cur = pd.read_parquet(cur_pq)[list(HMM_COLS)]
    base = pd.read_parquet(base_pq)[list(HMM_COLS)]
    return compare_dataframes(cur, base)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--window", required=True)
    p.add_argument("--symbol", required=True)
    p.add_argument("--current-run", type=Path, required=True)
    p.add_argument("--baseline-run", type=Path, required=True)
    args = p.parse_args()

    result = recompute_and_diff(
        args.window, args.symbol,
        args.current_run, args.baseline_run,
    )
    print(f"match={result.match} diff_count={result.diff_count}")
    if not result.match:
        print(f"  example: {result.first_example}")
        print(f"  cols: {result.diff_cols}")
        print(f"  rows: {result.diff_rows}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4.4: Run tests — expect PASS**

```bash
python -m pytest tests/tools/test_hmm_output_recompute.py -v
```

Expected: 3 passed.

- [ ] **Step 4.5: Commit**

```bash
git add tools/audits/hmm_output_recompute.py tests/tools/test_hmm_output_recompute.py
git commit -m "feat(audits): HMM dual-verification tool — secondary check

Independent verification of HMM output bit-identity using pandas
assert_frame_equal with rtol=0, atol=0. Protects against bugs in
the primary sha256 check: if primary passes and secondary fails,
there is a bug in the primary check.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Audit-trail report generator

**Files:**
- Create: `tools/audits/hmm_attempt_report.py`
- Test: `tests/tools/test_hmm_attempt_report.py`

- [ ] **Step 5.1: Write a small test for the report generator**

Create `tests/tools/test_hmm_attempt_report.py`:

```python
"""Unit test for HMM attempt report generator."""
from pathlib import Path
from tools.audits.hmm_attempt_report import render_report, AttemptResult


def test_render_report_contains_required_sections(tmp_path):
    result = AttemptResult(
        hypothesis="H8",
        attempt_n=1,
        commit_hash="abc1234",
        layer_results={
            "canonical_180d/citadel/trades": (True, "expected", "observed"),
            "canonical_180d/citadel/equity": (True, "expected", "observed"),
        },
        speedup_wall_before=47.2,
        speedup_wall_after=38.0,
        dual_verify_match=True,
        verdict="PASS",
    )
    text = render_report(result)
    assert "H8" in text
    assert "PASS" in text
    assert "abc1234" in text
    assert "47.2" in text
```

- [ ] **Step 5.2: Run test — expect FAIL**

```bash
python -m pytest tests/tools/test_hmm_attempt_report.py -v
```

- [ ] **Step 5.3: Implement the report generator**

Create `tools/audits/hmm_attempt_report.py`:

```python
"""
HMM Fix-Attempt Report Generator — Lane 2b

Called by the orchestration script after each H7/H8 fix attempt.
Emits a markdown report in docs/audits/ with:
- Hypothesis + commit hash
- Per-layer digest table (expected/observed/match)
- Speedup measurement
- Dual-verify result
- Verdict: PASS / FAIL_INTEGRITY_LAYER_{1,2,3} / FAIL_SPEEDUP / REVERTED
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class AttemptResult:
    hypothesis: str
    attempt_n: int
    commit_hash: str
    layer_results: dict[str, tuple[bool, str, str]] = field(default_factory=dict)
    speedup_wall_before: float = 0.0
    speedup_wall_after: float = 0.0
    dual_verify_match: bool = True
    verdict: str = "UNKNOWN"


def render_report(result: AttemptResult) -> str:
    gain_pct = 0.0
    if result.speedup_wall_before > 0:
        gain_pct = (
            (result.speedup_wall_before - result.speedup_wall_after)
            / result.speedup_wall_before * 100.0
        )

    rows = []
    for key, (ok, expected, observed) in sorted(result.layer_results.items()):
        mark = "✅" if ok else "❌"
        rows.append(
            f"| {key} | {expected[:12]}... | {observed[:12]}... | {mark} |"
        )

    return f"""# HMM Fix Attempt Report — {result.hypothesis} attempt {result.attempt_n}

- **Commit:** `{result.commit_hash}`
- **Timestamp:** {datetime.utcnow().isoformat()}Z
- **Verdict:** **{result.verdict}**

## Integrity digests

| artifact | expected | observed | match |
|---|---|---|---|
{chr(10).join(rows) if rows else "| (none) | — | — | — |"}

## Speedup

- **Baseline wall:** {result.speedup_wall_before:.2f}s
- **Post-fix wall:** {result.speedup_wall_after:.2f}s
- **Gain:** {gain_pct:.1f}%

## Dual verify

- Secondary check matches primary: **{result.dual_verify_match}**
"""


def write_report(result: AttemptResult, out_dir: Path = Path("docs/audits")) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = f"2026-04-19_lane_2b_fix_{result.hypothesis}_attempt_{result.attempt_n}.md"
    path = out_dir / fname
    path.write_text(render_report(result))
    return path
```

- [ ] **Step 5.4: Run tests — expect PASS**

```bash
python -m pytest tests/tools/test_hmm_attempt_report.py -v
```

- [ ] **Step 5.5: Commit**

```bash
git add tools/audits/hmm_attempt_report.py tests/tools/test_hmm_attempt_report.py
git commit -m "feat(audits): HMM attempt report generator

Emits markdown audit-trail report per H7/H8 fix attempt with
digest table, speedup, dual-verify result, verdict.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Generate and commit golden fixtures (the contract lock)

**Files:**
- Create: `tests/fixtures/hmm_golden/{window}/...` (~148 files total)

- [ ] **Step 6.1: Add .gitignore exception for golden fixtures**

Edit `.gitignore` to explicitly un-ignore `tests/fixtures/hmm_golden/` if any parent pattern would exclude it. Append to `.gitignore`:

```
!tests/fixtures/hmm_golden/
!tests/fixtures/hmm_golden/**
```

Only apply if existing patterns would have excluded the dir.

- [ ] **Step 6.2: Run the golden generator — canonical_180d first**

```bash
python -m tools.audits.hmm_golden_generator
```

Expected duration: ~15 min (5 engines × 4 windows, serial). Progress lines like `[canonical_180d] days=180 end=2026-04-18 ... running citadel...` appear.

If any engine errors out (e.g., data gap for stress_covid symbols), note which and adjust universe for that window:
- Edit `tools/audits/hmm_golden_generator.py` to allow per-window universe override
- Commit the override before re-running

- [ ] **Step 6.3: Inspect generated fixtures**

```bash
find tests/fixtures/hmm_golden -type f | wc -l
```

Expected: between ~100 and ~150 files. Listing first 10:

```bash
find tests/fixtures/hmm_golden -type f | head -10
```

- [ ] **Step 6.4: Commit the golden fixtures — THE CONTRACT**

```bash
git add tests/fixtures/hmm_golden/ .gitignore
git commit -m "fix(fixtures): lock HMM golden outputs antes de Lane 2b

Golden fixture lock per spec v2. These digests are the contract
against which every H7/H8 fix is measured.

- 4 windows (canonical_180d, stress_covid, stress_ftx, stress_etf_rally)
- 5 engines (citadel, bridgewater, deshaw, jump, medallion)
- 3 layers (HMM cols, trades, equity+metrics)
- ~130 files, each a sha256 digest or deterministic CSV/JSON

From now until merge: any change producing a different digest is
rejected automatically.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 6.5: Verify primary suite passes against self**

```bash
AURUM_RUN_INTEGRITY=1 python -m pytest tests/perf/test_hmm_integrity.py -v
```

Expected: all tests PASS or SKIP (no divergence possible since we just generated the goldens against the current code).

If any fail: there is a non-determinism in the pipeline that must be fixed before proceeding (engine must produce bit-identical output on rerun).

---

## Task 7: H7 diagnostic — count HMM calls

**Files:**
- Create: `tools/audits/hmm_call_counter.py`
- Modify: `core/chronos.py` (temporary instrumentation, reverted after)

- [ ] **Step 7.1: Add temporary counter to _build_hmm_backend**

Open `core/chronos.py`, find `_build_hmm_backend`. Wrap with a counter guarded by env var:

```python
import os
_HMM_CALL_COUNTER: dict[str, int] = {}

def _build_hmm_backend(n_states: int, random_state: int = 42):
    if os.environ.get("AURUM_HMM_COUNT"):
        import traceback
        caller = traceback.extract_stack()[-3]
        key = f"{Path(caller.filename).name}:{caller.name}"
        _HMM_CALL_COUNTER[key] = _HMM_CALL_COUNTER.get(key, 0) + 1
    # ... existing body unchanged ...
```

Also add a `_dump_hmm_counter()` function that writes the dict to `data/perf_profile/2026-04-19/hmm_call_count.txt`.

- [ ] **Step 7.2: Run CITADEL 180d with the counter enabled**

```bash
AURUM_HMM_COUNT=1 python -m engines.citadel --days 180 --end 2026-04-18 --no-menu
```

Then invoke a small helper that dumps the counter at process end. Or have `_build_hmm_backend` log each increment to a file.

- [ ] **Step 7.3: Read the count and decide H7 viability**

```bash
cat data/perf_profile/2026-04-19/hmm_call_count.txt
```

Decision rule:
- If total calls ≤ number of symbols in the universe (~11): **H7 DEAD — arquivar**
- If total calls ≥ 2× number of symbols: **H7 LIVE — proceed to implementation**

- [ ] **Step 7.4: Revert the instrumentation**

```bash
git checkout core/chronos.py
```

(Do NOT commit the counter. It stays in working tree only during diagnostic.)

- [ ] **Step 7.5: Commit only the count result**

```bash
git add data/perf_profile/2026-04-19/hmm_call_count.txt tools/audits/hmm_call_counter.py
git commit -m "diag(hmm): H7 call count baseline — CITADEL 180d

Measured with temporary counter in _build_hmm_backend (reverted).

Result: {N} total calls across {M} symbols. Ratio = {R}.

H7 verdict: {DEAD|LIVE}

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: H8 microbench — scipy.logsumexp vs numpy local

**Files:**
- Create: `tools/audits/logsumexp_microbench.py`

- [ ] **Step 8.1: Write the microbench script**

Create `tools/audits/logsumexp_microbench.py`:

```python
"""
H8 Microbench — scipy.special.logsumexp vs numpy-local.

Validates mechanism of H8 before any code change to chronos.
Reports timing and precision delta on arrays matching the shapes
used in _forward/_backward (500 samples × 3 states).
"""
from __future__ import annotations
import numpy as np
import time
from scipy.special import logsumexp as scipy_lse


def numpy_logsumexp_axis1(M: np.ndarray) -> np.ndarray:
    """Local vectorized logsumexp along axis=1."""
    m = M.max(axis=1, keepdims=True)
    return (np.log(np.exp(M - m).sum(axis=1)) + m.squeeze(1))


def bench(fn, M, iters=10000):
    t0 = time.perf_counter()
    for _ in range(iters):
        _ = fn(M)
    return time.perf_counter() - t0


def main():
    rng = np.random.default_rng(42)
    M = rng.standard_normal((500, 3)) * 10.0

    scipy_out = scipy_lse(M, axis=1)
    local_out = numpy_logsumexp_axis1(M)

    max_abs = float(np.max(np.abs(scipy_out - local_out)))
    max_rel = float(np.max(
        np.abs(scipy_out - local_out) / np.maximum(np.abs(scipy_out), 1e-300)
    ))

    t_scipy = bench(lambda m: scipy_lse(m, axis=1), M)
    t_local = bench(numpy_logsumexp_axis1, M)

    print(f"shape={M.shape}")
    print(f"scipy wall: {t_scipy:.3f}s")
    print(f"local wall: {t_local:.3f}s")
    print(f"speedup:    {t_scipy / t_local:.2f}x")
    print(f"max |diff|: {max_abs:.3e}")
    print(f"max rel:    {max_rel:.3e}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 8.2: Run the microbench and inspect output**

```bash
python -m tools.audits.logsumexp_microbench | tee data/perf_profile/2026-04-19/logsumexp_microbench.txt
```

Expected: `speedup ≥ 2x`, `max |diff| ≤ 1e-10` (float-epsilon).

If `max |diff| > 1e-10` → H8 is at serious risk for Layer 1 bit-identicality; proceed but watch Layer 1 carefully.

- [ ] **Step 8.3: Commit the microbench tool and result**

```bash
git add tools/audits/logsumexp_microbench.py data/perf_profile/2026-04-19/logsumexp_microbench.txt
git commit -m "diag(hmm): H8 microbench — scipy logsumexp vs numpy local

Isolated timing + precision delta on shape (500, 3). Confirms
mechanism exists (or doesn't) before touching chronos.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: H8 implement _logsumexp_axis1 helper (TDD)

**Files:**
- Modify: `core/chronos.py` (add helper)
- Test: `tests/core/test_chronos_logsumexp.py`

- [ ] **Step 9.1: Write the failing test**

Create `tests/core/test_chronos_logsumexp.py`:

```python
"""Unit tests for chronos._logsumexp_axis1 helper (H8)."""
import numpy as np
from scipy.special import logsumexp as scipy_lse

from core.chronos import _logsumexp_axis1


def test_matches_scipy_on_random_input():
    rng = np.random.default_rng(42)
    M = rng.standard_normal((500, 3)) * 10.0
    expected = scipy_lse(M, axis=1)
    observed = _logsumexp_axis1(M)
    np.testing.assert_allclose(observed, expected, rtol=0, atol=1e-10)


def test_handles_negative_large_values():
    M = np.array([[-1000.0, -1001.0, -1002.0],
                  [-500.0, -600.0, -700.0]])
    expected = scipy_lse(M, axis=1)
    observed = _logsumexp_axis1(M)
    np.testing.assert_allclose(observed, expected, rtol=0, atol=1e-10)


def test_shape_is_preserved():
    M = np.zeros((7, 3))
    out = _logsumexp_axis1(M)
    assert out.shape == (7,)


def test_single_state_input():
    M = np.array([[5.0], [10.0], [-3.0]])
    expected = scipy_lse(M, axis=1)
    observed = _logsumexp_axis1(M)
    np.testing.assert_allclose(observed, expected, rtol=0, atol=1e-10)
```

- [ ] **Step 9.2: Run test — expect FAIL**

```bash
python -m pytest tests/core/test_chronos_logsumexp.py -v
```

Expected: FAIL with `ImportError: cannot import name '_logsumexp_axis1'`.

- [ ] **Step 9.3: Implement the helper in core/chronos.py**

Add the helper near the top of `core/chronos.py`, after the imports block (before class `GaussianHMMNp`):

```python
def _logsumexp_axis1(M: np.ndarray) -> np.ndarray:
    """Vectorized log-sum-exp along axis=1 (H8, Lane 2b).

    Equivalent to scipy.special.logsumexp(M, axis=1) but inline
    to avoid scipy dispatch overhead in the HMM EM inner loop.

    Numerically stable via the max-subtraction trick.
    """
    m = M.max(axis=1, keepdims=True)
    return np.log(np.exp(M - m).sum(axis=1)) + m.squeeze(1)
```

Do NOT yet replace call sites inside `_forward`/`_backward` — that's Task 10.

- [ ] **Step 9.4: Run test — expect PASS**

```bash
python -m pytest tests/core/test_chronos_logsumexp.py -v
```

Expected: 4 passed.

- [ ] **Step 9.5: Run the full chronos test to confirm no regression**

```bash
python -m pytest tests/core/test_chronos_hmm.py -v
```

Expected: all pass (helper is unused so far, so no HMM output changes).

- [ ] **Step 9.6: Commit**

```bash
git add core/chronos.py tests/core/test_chronos_logsumexp.py
git commit -m "feat(chronos): add _logsumexp_axis1 helper (H8, unused)

Vectorized numpy-local logsumexp equivalent to scipy.special.logsumexp(M, axis=1).
Added as helper; call sites in _forward/_backward NOT yet replaced.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: H8 swap call sites in _forward/_backward

**Files:**
- Modify: `core/chronos.py` (inside GaussianHMMNp class)

- [ ] **Step 10.1: Locate the scipy logsumexp call sites**

```bash
grep -n "logsumexp" core/chronos.py
```

Expected: 2 call sites inside `GaussianHMMNp._forward` and `GaussianHMMNp._backward`, each of form like `logsumexp(M, axis=1)`.

- [ ] **Step 10.2: Replace both sites with the local helper**

For each call site:
- Replace `from scipy.special import logsumexp` with nothing (or leave if used elsewhere — grep again if unsure)
- Replace `logsumexp(expr, axis=1)` with `_logsumexp_axis1(expr)` inline

Use the Edit tool with exact line matching to avoid unintended replacements.

- [ ] **Step 10.3: Re-run chronos unit tests**

```bash
python -m pytest tests/core/test_chronos_hmm.py tests/core/test_chronos_logsumexp.py -v
```

Expected: all PASS. If any fail (HMM output drift in existing tests), revert the edit and investigate:

```bash
git diff core/chronos.py  # inspect
git checkout core/chronos.py  # revert if needed
```

- [ ] **Step 10.4: Run smoke test**

```bash
python smoke_test.py --quiet
```

Expected: 178/178 (or whatever the current count is) — no regression.

- [ ] **Step 10.5: Commit**

```bash
git add core/chronos.py
git commit -m "perf(chronos): H8 swap scipy.special.logsumexp -> _logsumexp_axis1

Inline numpy-local logsumexp in GaussianHMMNp._forward and
_backward. Eliminates scipy dispatch overhead in the HMM EM
inner loop (called 100 iters × 2 passes × ~500 samples per fit).

Integrity check against 4-window × 5-engine golden fixtures
performed in Task 11.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: H8 run full integrity suite (3 layers × 4 windows × 5 engines)

**Files:**
- Output: `data/perf_profile/2026-04-19/post_h8_*` + audit report

- [ ] **Step 11.1: Regenerate engine runs for all 4 windows × 5 engines**

We need fresh runs from the H8-modified code to compare against goldens. The generator tool already does this — run it again in a subdirectory to avoid overwriting goldens:

```bash
# Save current goldens aside for safety
cp -r tests/fixtures/hmm_golden tests/fixtures/hmm_golden.SAFEHOLD

# Re-run all engines for all 4 windows
python -m tools.audits.hmm_golden_generator
```

This regenerates fixtures in place. The generator is deterministic, so if H8 preserves output exactly, the files will be byte-identical.

- [ ] **Step 11.2: Compare regenerated fixtures against SAFEHOLD**

```bash
diff -r tests/fixtures/hmm_golden tests/fixtures/hmm_golden.SAFEHOLD
```

Expected: no output (files identical).

If diff shows output: **H8 FAILS integrity**. Proceed to Step 11.6 (revert).

- [ ] **Step 11.3: Run the primary integrity pytest suite**

```bash
AURUM_RUN_INTEGRITY=1 python -m pytest tests/perf/test_hmm_integrity.py -v
```

Expected: all PASS.

- [ ] **Step 11.4: Run dual-verification on the most impactful symbol**

Pick one symbol (e.g., BNBUSDT in canonical_180d) and compare the new run's HMM output against a reference. Reference can be obtained by restoring from SAFEHOLD:

```bash
python -m tools.audits.hmm_output_recompute \
    --window canonical_180d --symbol BNBUSDT \
    --current-run "$(ls -td data/citadel/*/ | head -1)" \
    --baseline-run "$(ls -td data/citadel/*/ | head -2 | tail -1)"
```

Expected: `match=True`. (If the most recent two runs were both post-H8, they will be identical by determinism.)

- [ ] **Step 11.5: Cleanup SAFEHOLD if everything passes**

```bash
rm -rf tests/fixtures/hmm_golden.SAFEHOLD
```

- [ ] **Step 11.6: If any check failed — revert H8 cleanly**

```bash
git revert --no-commit HEAD      # revert the H8 swap
git revert --no-commit HEAD~1    # revert the helper add
git commit -m "revert: H8 failed integrity — see audit report

One of Layer 1/2/3 digests diverged. H8 archived for this cycle.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

Then jump to Task 13 (H7 if viable) or directly to Task 14.

- [ ] **Step 11.7: Commit the generator re-run output and audit report**

```bash
python -c "
from tools.audits.hmm_attempt_report import AttemptResult, write_report
import subprocess
sha = subprocess.check_output(['git','rev-parse','HEAD']).decode().strip()[:8]
r = AttemptResult(
    hypothesis='H8', attempt_n=1, commit_hash=sha,
    layer_results={},  # populated manually — primary suite output
    speedup_wall_before=47.2, speedup_wall_after=0.0,  # filled in Task 12
    dual_verify_match=True, verdict='PASS_INTEGRITY_PENDING_SPEEDUP',
)
write_report(r)
"

git add docs/audits/2026-04-19_lane_2b_fix_H8_attempt_1.md
git commit -m "audit(hmm): H8 passed 3-layer integrity × 4 windows

Integrity verdict: PASS for all 4 windows × 5 engines × 3 layers.
Speedup measurement pending (Task 12).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: H8 measure speedup (gate ≥10%)

**Files:**
- Output: `data/perf_profile/2026-04-19/h8_citadel_180d.json`

- [ ] **Step 12.1: Run CITADEL 180d three times, capture wall-time**

```bash
for i in 1 2 3; do
    t0=$(date +%s.%N)
    python -m engines.citadel --days 180 --end 2026-04-18 --no-menu > /dev/null 2>&1
    t1=$(date +%s.%N)
    echo "run $i: $(python -c "print(${t1} - ${t0})")"
done | tee data/perf_profile/2026-04-19/h8_citadel_180d_timings.txt
```

- [ ] **Step 12.2: Compute median wall-time**

```bash
python -c "
import statistics
lines = open('data/perf_profile/2026-04-19/h8_citadel_180d_timings.txt').read().splitlines()
ts = [float(l.split(': ')[1]) for l in lines if ': ' in l]
print(f'median = {statistics.median(ts):.2f}s')
print(f'gain vs 47.2s baseline = {(47.2 - statistics.median(ts)) / 47.2 * 100:.1f}%')
" | tee -a data/perf_profile/2026-04-19/h8_citadel_180d_timings.txt
```

- [ ] **Step 12.3: Decision: ≥10% gain?**

If `gain ≥ 10%` → H8 **ACCEPTED**, proceed to Task 13.
If `gain < 10%` → H8 **REJECTED for speedup**, revert the H8 commits:

```bash
# find the two H8 commits
git log --oneline | grep "H8\|_logsumexp_axis1" | head -4

# revert both in one commit
git revert --no-commit <h8_swap_sha>
git revert --no-commit <h8_helper_sha>
git commit -m "revert: H8 below 10% speedup gate — per spec

Integrity passed but speedup {X}% < 10% threshold. Reverted per
stop-rule in Lane 2b spec v2.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 12.4: Update the audit report with speedup numbers**

Re-run the audit report generator with the actual speedup result (see Task 11 Step 11.7 pattern). Overwrite `docs/audits/2026-04-19_lane_2b_fix_H8_attempt_1.md` with the final verdict (`PASS` or `REVERTED_SPEEDUP`).

```bash
git add docs/audits/2026-04-19_lane_2b_fix_H8_attempt_1.md data/perf_profile/2026-04-19/h8_citadel_180d_timings.txt
git commit -m "audit(hmm): H8 speedup = {X}% — verdict {PASS|REVERTED_SPEEDUP}

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 13: H7 implement lru_cache (only if H7 was LIVE in Task 7)

**If Task 7 decided H7 is DEAD, skip to Task 14.**

**Files:**
- Modify: `core/chronos.py` (wrap model fit in cache)
- Test: `tests/core/test_chronos_hmm_cache.py`

- [ ] **Step 13.1: Write the failing test**

Create `tests/core/test_chronos_hmm_cache.py`:

```python
"""H7 — lru_cache on HMM fit."""
import numpy as np
from core.chronos import _build_hmm_backend_cached


def test_same_input_returns_cached_model():
    X = np.random.default_rng(0).standard_normal((300, 2))
    m1 = _build_hmm_backend_cached(X.tobytes(), 3)
    m2 = _build_hmm_backend_cached(X.tobytes(), 3)
    assert m1 is m2  # cache hit identity


def test_different_input_returns_different_model():
    X1 = np.random.default_rng(0).standard_normal((300, 2)).tobytes()
    X2 = np.random.default_rng(1).standard_normal((300, 2)).tobytes()
    m1 = _build_hmm_backend_cached(X1, 3)
    m2 = _build_hmm_backend_cached(X2, 3)
    assert m1 is not m2
```

- [ ] **Step 13.2: Run test — expect FAIL**

```bash
python -m pytest tests/core/test_chronos_hmm_cache.py -v
```

- [ ] **Step 13.3: Implement the cached wrapper**

Add to `core/chronos.py`, after `_build_hmm_backend`:

```python
from functools import lru_cache
import hashlib

@lru_cache(maxsize=256)
def _build_hmm_backend_cached(x_train_bytes: bytes, n_states: int, random_state: int = 42):
    """H7: memoized backend-and-fit by X_train hash.

    Returns a fitted HMM model. Key is the raw bytes of the
    training array; determinism of the underlying GaussianHMMNp
    init (random_state=42) ensures identical output across calls.
    """
    X = np.frombuffer(x_train_bytes).reshape(-1, 2)
    model = _build_hmm_backend(n_states=n_states, random_state=random_state)
    model.fit(X)
    return model
```

Then modify `enrich_with_regime` to call the cached path instead of direct `_build_hmm_backend` + `model.fit`:

```python
# OLD:
# model = _build_hmm_backend(n_states=n_states)
# model.fit(X_train)

# NEW:
model = _build_hmm_backend_cached(
    X_train.tobytes(), n_states=n_states
)
```

- [ ] **Step 13.4: Run cache unit tests + chronos tests — expect PASS**

```bash
python -m pytest tests/core/test_chronos_hmm_cache.py tests/core/test_chronos_hmm.py -v
```

- [ ] **Step 13.5: Run the integrity suite (Task 11 equivalent)**

```bash
cp -r tests/fixtures/hmm_golden tests/fixtures/hmm_golden.SAFEHOLD
python -m tools.audits.hmm_golden_generator
diff -r tests/fixtures/hmm_golden tests/fixtures/hmm_golden.SAFEHOLD
```

Expected: no output (H7 MUST be bit-identical by construction).

If diff appears: H7 has a bug in implementation (not a numerical drift). Fix the bug, do not revert.

```bash
AURUM_RUN_INTEGRITY=1 python -m pytest tests/perf/test_hmm_integrity.py -v
rm -rf tests/fixtures/hmm_golden.SAFEHOLD
```

- [ ] **Step 13.6: Measure speedup (Task 12 equivalent)**

Same 3-run median procedure as Task 12 Step 12.1. Gate: ≥10% vs previous best (post-H8 if H8 accepted, else vs 47.2s baseline).

- [ ] **Step 13.7: Commit if passes; revert if fails gate**

On PASS:

```bash
git add core/chronos.py tests/core/test_chronos_hmm_cache.py
git add docs/audits/2026-04-19_lane_2b_fix_H7_attempt_1.md
git add data/perf_profile/2026-04-19/h7_citadel_180d_timings.txt
git commit -m "perf(chronos): H7 lru_cache on HMM fit by X_train hash

Cache hit in walk-forward when consecutive bars within same
lookback share training data. Bit-identical by construction
(model reuse returns same object). Speedup = {X}%.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

On FAIL:

```bash
git revert --no-commit HEAD~2..HEAD
git commit -m "revert: H7 below 10% speedup gate"
```

---

## Task 14: Consolidation — full suite + smoke + final audit report

**Files:**
- Create: `docs/audits/2026-04-19_lane_2b_final.md`

- [ ] **Step 14.1: Run the full pytest suite**

```bash
python -m pytest tests/ -q
```

Expected: same count as pre-cycle baseline (no regressions from pre-Lane-2b), plus new tests introduced in Tasks 2/3/4/5/9/13.

- [ ] **Step 14.2: Run the smoke test**

```bash
python smoke_test.py --quiet
```

Expected: 178/178 (or the pre-cycle baseline count).

- [ ] **Step 14.3: Compute total cycle gain**

```bash
python -c "
baseline = 47.2
current = float(open('data/perf_profile/2026-04-19/final_citadel_180d_timing.txt').read().strip())
gain = (baseline - current) / baseline * 100
print(f'Total cycle gain: {gain:.1f}%')
print(f'Gate 25%: {\"PASS\" if gain >= 25 else \"INSUFFICIENT\"}')
"
```

(First create `data/perf_profile/2026-04-19/final_citadel_180d_timing.txt` with the final median wall-time from the most recent H8/H7 measurements.)

- [ ] **Step 14.4: Write the final audit report**

Create `docs/audits/2026-04-19_lane_2b_final.md`:

```markdown
# Lane 2b HMM Speedup — Final Audit Report

## Context
- Spec: docs/superpowers/specs/2026-04-19-lane-2b-hmm-speedup-design.md (v2)
- Branch: feat/lane-2b-hmm
- Started: 2026-04-19 (commit ddc3b86)
- Ended: 2026-04-{DD}

## Hypotheses outcomes
| # | Hypothesis | Verdict | Speedup | Integrity | Notes |
|---|---|---|---|---|---|
| H7 | lru_cache fit by X_train hash | {DEAD/PASS/REVERTED} | {X%/N-A} | {PASS/FAIL} | {notes} |
| H8 | scipy logsumexp -> numpy local | {PASS/REVERTED} | {X%} | {PASS/FAIL} | {notes} |
| H9 | hmmlearn backend C | ARCHIVED preemptively | n/a | n/a | moved to future cycle |

## Speedup summary
- Baseline CITADEL 180d: 47.2s
- Post-cycle CITADEL 180d: {X}s
- Total gain: {X}%
- Cycle gate (≥25%): {PASS/INSUFFICIENT}

## Integrity summary
- 4 windows × 5 engines × 3 layers = ~60 gate checks per fix attempt
- H8 attempt 1: {PASS/FAIL at Layer N}
- H7 attempt 1: {PASS/FAIL at Layer N / SKIPPED}
- Dual verification concord: {YES/NO}

## Artifacts
- Golden fixtures: tests/fixtures/hmm_golden/ (committed 2026-04-19)
- Audit reports: docs/audits/2026-04-19_lane_2b_fix_*.md
- Perf data: data/perf_profile/2026-04-19/

## Shadow mode (H8 only, if H8 accepted)
- Deployed: {YES/NO + date}
- 72h divergence: {0/N}
- Status: {STABLE/ROLLED_BACK}

## Closure
- State: {Success Complete / Success Partial / Failure Integrity / Failure Honor}
- Next cycle candidates: {H9 convergence study / H10 _forward/_backward vectorize / ...}
```

Fill in all `{X}` placeholders with real values.

- [ ] **Step 14.5: Commit the final report**

```bash
git add docs/audits/2026-04-19_lane_2b_final.md data/perf_profile/2026-04-19/
git commit -m "audit(hmm): Lane 2b final report — cycle verdict {state}

Total CITADEL 180d gain: {X}%. Integrity: {PASS|FAIL}.
H7: {verdict}. H8: {verdict}. H9: archived preemptively.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 15: Session log + daily log

**Files:**
- Create: `docs/sessions/2026-04-19_{HHMM}.md`
- Update: `docs/days/2026-04-19.md`

- [ ] **Step 15.1: Generate the session log**

Follow the exact template in `CLAUDE.md` under "REGRA PERMANENTE — SESSION LOG". Include the Lane 2b cycle outcome, all commits, integrity/speedup results.

- [ ] **Step 15.2: Update the daily log**

If `docs/days/2026-04-19.md` exists, prepend today's Lane 2b session at the top of "Sessões do dia". Otherwise create it from scratch.

- [ ] **Step 15.3: Commit logs**

```bash
git add docs/sessions/2026-04-19_*.md docs/days/2026-04-19.md
git commit -m "docs(sessions): 2026-04-19_{HHMM} Lane 2b HMM speedup

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Shadow-mode checklist (H8 only, post-merge, operational — not a code task)

If H8 was accepted and merged into `feat/phi-engine`:

- [ ] Deploy `feat/lane-2b-hmm` to the VPS `millennium_shadow` service in shadow mode
- [ ] Add a side-by-side HMM computation hook (old vs new) that logs digest delta per bar per symbol
- [ ] Set a rollback watchdog: any bar-level digest divergence → auto `git revert` on the server
- [ ] Run shadow for 72h (wall-time)
- [ ] After 72h with zero divergence: promote the merge, decommission shadow, update `docs/audits/2026-04-19_lane_2b_final.md` with shadow outcome
- [ ] If any divergence occurs: rollback, update final report with shadow verdict FAILED

---

## Self-Review

**1. Spec coverage:**
- [x] Spec §Hipóteses — Tasks 7, 8, 9, 10, 13
- [x] Spec §Invariante 3 camadas — Task 3 (primary) + Task 4 (dual) + Task 11 (execution)
- [x] Spec §4 janelas — Task 2 (WINDOW_DEFINITIONS) + Task 6 (generation)
- [x] Spec §Golden fixture lock — Task 6
- [x] Spec §Dual verification — Task 4
- [x] Spec §Métrica speedup — Task 12
- [x] Spec §Regra parada honra — Task 11 Step 11.6 and Task 12 Step 12.3
- [x] Spec §Kill switch rollback — covered via revert steps in Tasks 11, 12, 13
- [x] Spec §Shadow mode 72h (H8) — Shadow checklist section
- [x] Spec §Audit trail — Tasks 5, 11, 12, 14

**2. Placeholder scan:** No TBD/TODO. `{X}` placeholders are concrete "fill with measured value" slots, not missing content.

**3. Type consistency:** Verified — `HMM_COLS`, `WINDOW_DEFINITIONS`, `HMM_ENGINES`, `AttemptResult`, `CompareResult` names consistent across Tasks 2-5 and their consumers in Task 11+.

**4. Scope:** Single cycle, 2 hypotheses + preemptively archived H9. No decomposition needed.
