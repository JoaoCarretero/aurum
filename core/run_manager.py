"""
run_manager.py — Per-run directory structure and global index for AURUM backtests.

Directory layout:
    data/
      runs/
        citadel_2026-04-09_1940/
          config.json
          trades.json
          equity.json
          summary.json
          overfit.json
          report.html
          log.txt
          trades.log
          charts/
      index.json
"""

import hashlib
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from core.persistence import atomic_write_json

# ---------------------------------------------------------------------------
# Project root — one level up from core/
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RUNS_DIR = DATA_DIR / "runs"
INDEX_PATH = DATA_DIR / "index.json"


# ── TeeLogger ──────────────────────────────────────────────────────────────

class TeeLogger:
    """Captures stdout to both terminal and log file simultaneously."""

    def __init__(self, log_path):
        self.terminal = sys.stdout
        self.log = open(log_path, "w", encoding="utf-8")

    def write(self, msg):
        self.terminal.write(msg)
        self.log.write(msg)

    def flush(self):
        self.terminal.flush()
        self.log.flush()

    def close(self):
        self.log.close()


# ── 1. snapshot_config ─────────────────────────────────────────────────────

def snapshot_config() -> dict:
    """Capture ALL active parameters from config.params for reproducibility."""
    from config import params

    snapshot = {}
    for name in sorted(dir(params)):
        if name.startswith("__"):
            continue
        val = getattr(params, name)
        if callable(val):
            continue
        if isinstance(val, (int, float, str, bool, type(None))):
            snapshot[name] = val
        elif isinstance(val, (list, dict)):
            snapshot[name] = val
        elif isinstance(val, range):
            snapshot[name] = list(val)
        elif isinstance(val, tuple):
            snapshot[name] = list(val)
    return snapshot


# ── 2. create_run_dir ──────────────────────────────────────────────────────

def create_run_dir(engine_name: str = "citadel") -> tuple[str, Path]:
    """Create a timestamped run directory under data/runs/.

    Returns (run_id, run_dir) where run_id is e.g. 'citadel_2026-04-09_1940'.
    """
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    run_id = f"{engine_name}_{stamp}"
    run_dir = RUNS_DIR / run_id

    run_dir.mkdir(parents=True, exist_ok=True)
    # NOTE: charts/ subdir não é mais usado — métricas renderizadas
    # internamente no launcher dashboard via tk.Canvas.

    return run_id, run_dir


# ── 3. setup_logging ──────────────────────────────────────────────────────

def setup_logging(run_dir: Path) -> tuple:
    """Set up Python logging for a backtest run.

    - run_dir/log.txt   — full log (DEBUG), file only
    - StreamHandler     — WARNING+ on stdout

    Returns (trade_file_handler, validation_file_handler).
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # File handler — DEBUG level, captures everything
    log_path = run_dir / "log.txt"
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s — %(message)s",
                          datefmt="%H:%M:%S")
    )
    root_logger.addHandler(file_handler)

    # Stream handler — WARNING+ to stdout
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(logging.WARNING)
    stream_handler.setFormatter(
        logging.Formatter("%(levelname)s: %(message)s")
    )
    root_logger.addHandler(stream_handler)

    # Trade logger — writes to trades.log
    trade_path = run_dir / "trades.log"
    trade_handler = logging.FileHandler(trade_path, encoding="utf-8")
    trade_handler.setLevel(logging.DEBUG)
    trade_handler.setFormatter(
        logging.Formatter("%(asctime)s %(message)s", datefmt="%H:%M:%S")
    )
    trade_logger = logging.getLogger("trades")
    trade_logger.addHandler(trade_handler)

    # Validation logger — shares the main log file
    validation_handler = logging.FileHandler(log_path, encoding="utf-8")
    validation_handler.setLevel(logging.DEBUG)
    validation_handler.setFormatter(
        logging.Formatter("%(asctime)s [VALIDATION] %(message)s",
                          datefmt="%H:%M:%S")
    )
    validation_logger = logging.getLogger("validation")
    validation_logger.addHandler(validation_handler)

    return trade_handler, validation_handler


# ── 4. save_run_artifacts ──────────────────────────────────────────────────

def save_run_artifacts(run_dir, config, trades, equity, summary,
                       overfit_results=None, diagnostics=None):
    """Save all JSON artifacts to the run directory."""
    run_dir = Path(run_dir)

    # config.json
    atomic_write_json(run_dir / "config.json", config)

    # trades.json — filter non-serializable fields
    clean_trades = _clean_trades(trades)
    atomic_write_json(run_dir / "trades.json", clean_trades)

    # equity.json
    atomic_write_json(run_dir / "equity.json", equity)

    # summary.json
    atomic_write_json(run_dir / "summary.json", summary)

    # overfit.json (optional)
    if overfit_results is not None:
        atomic_write_json(run_dir / "overfit.json", overfit_results)

    # diagnostics (optional, save alongside)
    if diagnostics is not None:
        atomic_write_json(run_dir / "diagnostics.json", diagnostics)


def _clean_trades(trades) -> list:
    """Convert a list of trade dicts/objects into JSON-safe dicts."""
    if not trades:
        return []

    result = []
    for t in trades:
        if isinstance(t, dict):
            row = {}
            for k, v in t.items():
                try:
                    json.dumps(v, default=str)
                    row[k] = v
                except (TypeError, ValueError):
                    row[k] = str(v)
            result.append(row)
        else:
            # Object with attributes
            row = {}
            for k in vars(t):
                v = getattr(t, k)
                try:
                    json.dumps(v, default=str)
                    row[k] = v
                except (TypeError, ValueError):
                    row[k] = str(v)
            result.append(row)
    return result


# ── 5. append_to_index ─────────────────────────────────────────────────────

def append_to_index(run_dir, summary, config, overfit_results=None):
    """Append this run to data/index.json (creates the file if needed).

    Infers engine identity from (in order): summary["engine"] → parent dir
    name → run_id prefix. Writes run_id with engine prefix to avoid the
    launcher listing duplicates (engine-dir-scanned vs index-recorded).
    """
    run_dir = Path(run_dir)
    raw_id = run_dir.name

    # Resolve engine (institutional name → slug)
    s = summary if isinstance(summary, dict) else {}
    _inst = str(s.get("engine") or "").strip()
    _parent = run_dir.parent.name.lower()
    _ENG_TO_SLUG = {
        "CITADEL": "citadel", "BRIDGEWATER": "bridgewater",
        "JUMP": "jump", "DE SHAW": "deshaw", "RENAISSANCE": "renaissance",
        "MILLENNIUM": "millennium", "TWO SIGMA": "twosigma",
        "AQR": "aqr", "JANE STREET": "janestreet",
    }
    _PARENT_TO_SLUG = {
        "bridgewater": "bridgewater", "jump": "jump", "deshaw": "deshaw",
        "renaissance": "renaissance", "millennium": "millennium",
        "twosigma": "twosigma", "aqr": "aqr", "janestreet": "janestreet",
        "runs": "citadel",  # data/runs/ is CITADEL's
    }
    engine_slug = (_ENG_TO_SLUG.get(_inst.upper())
                   or _PARENT_TO_SLUG.get(_parent)
                   or raw_id.rsplit("_", 2)[0] if "_" in raw_id else "unknown")

    # Prefix run_id with engine slug so launcher dedup works
    run_id = raw_id if raw_id.startswith(f"{engine_slug}_") else f"{engine_slug}_{raw_id}"

    # Load existing index
    index = _load_index()

    # Config hash for dedup / fingerprinting
    config_json = json.dumps(config, sort_keys=True, default=str)
    config_hash = hashlib.sha256(config_json.encode("utf-8")).hexdigest()

    # Build entry — pull fields from summary with safe gets
    entry = {
        "run_id":       run_id,
        "engine":       engine_slug,
        "timestamp":    datetime.now().isoformat(),
        "interval":     s.get("interval") or config.get("INTERVAL") or config.get("ENTRY_TF"),
        "period_days":  s.get("period_days") or config.get("SCAN_DAYS"),
        "basket":       s.get("basket") or config.get("BASKET_EFFECTIVE") or "default",
        "n_symbols":    s.get("n_symbols"),
        "n_candles":    s.get("n_candles") or config.get("N_CANDLES"),
        "n_trades":     s.get("n_trades"),
        "win_rate":     s.get("win_rate"),
        "pnl":          s.get("pnl") or s.get("total_pnl"),
        "roi_pct":      s.get("roi_pct") or s.get("roi"),
        "sharpe":       s.get("sharpe"),
        "sortino":      s.get("sortino"),
        "max_dd_pct":   s.get("max_dd_pct") or s.get("max_dd"),
        "overfit_pass": None,
        "overfit_warn": None,
        "config_hash":  config_hash,
    }

    if overfit_results and isinstance(overfit_results, dict):
        entry["overfit_pass"] = overfit_results.get("passed")
        entry["overfit_warn"] = overfit_results.get("warnings")

    index.append(entry)

    # Write back — simple file-lock pattern (atomic-ish on Windows)
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        atomic_write_json(INDEX_PATH, index)
    except OSError:
        # Fallback: write directly
        with open(INDEX_PATH, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2, default=str)


def _load_index() -> list:
    """Load the global index, returning [] on missing/corrupt file."""
    if not INDEX_PATH.exists():
        return []
    try:
        with open(INDEX_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


# ── 6. list_runs ───────────────────────────────────────────────────────────

def list_runs(engine=None, last_n=20) -> list[dict]:
    """Return the last N index entries, optionally filtered by engine."""
    index = _load_index()

    if engine:
        index = [e for e in index if e.get("engine") == engine]

    return index[-last_n:]


# ── 7. compare_runs ───────────────────────────────────────────────────────

def compare_runs(run_id_a: str, run_id_b: str) -> dict:
    """Compare two runs by their config and summary artifacts.

    Returns {metrics_diff, config_diff, trade_count_diff}.
    """
    dir_a = RUNS_DIR / run_id_a
    dir_b = RUNS_DIR / run_id_b

    cfg_a = _load_json(dir_a / "config.json", {})
    cfg_b = _load_json(dir_b / "config.json", {})
    sum_a = _load_json(dir_a / "summary.json", {})
    sum_b = _load_json(dir_b / "summary.json", {})
    trades_a = _load_json(dir_a / "trades.json", [])
    trades_b = _load_json(dir_b / "trades.json", [])

    # Metrics diff
    metric_keys = [
        "n_trades", "trades", "win_rate", "pnl", "total_pnl",
        "roi_pct", "roi", "sharpe", "sortino", "max_dd_pct", "max_dd",
    ]
    metrics_diff = {}
    all_keys = set(sum_a.keys()) | set(sum_b.keys())
    for k in sorted(all_keys):
        va = sum_a.get(k)
        vb = sum_b.get(k)
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            metrics_diff[k] = {"a": va, "b": vb, "delta": vb - va}
        elif va != vb:
            metrics_diff[k] = {"a": va, "b": vb, "delta": None}

    # Config diff
    config_diff = []
    all_cfg_keys = set(cfg_a.keys()) | set(cfg_b.keys())
    for k in sorted(all_cfg_keys):
        va = cfg_a.get(k)
        vb = cfg_b.get(k)
        if va != vb:
            config_diff.append({"key": k, "a": va, "b": vb})

    # Trade count diff
    trade_count_diff = {
        "a": len(trades_a) if isinstance(trades_a, list) else 0,
        "b": len(trades_b) if isinstance(trades_b, list) else 0,
    }

    return {
        "run_a": run_id_a,
        "run_b": run_id_b,
        "metrics_diff": metrics_diff,
        "config_diff": config_diff,
        "trade_count_diff": trade_count_diff,
    }


def _load_json(path: Path, default=None):
    """Load a JSON file, returning *default* on any error."""
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


# ── 8. print_compare ──────────────────────────────────────────────────────

def print_compare(diff: dict):
    """Print a formatted comparison table to stdout."""
    run_a = diff.get("run_a", "RUN A")
    run_b = diff.get("run_b", "RUN B")
    metrics = diff.get("metrics_diff", {})
    config_diff = diff.get("config_diff", [])
    tc = diff.get("trade_count_diff", {})

    line = "-" * 50

    print(f"\n  COMPARE: {run_a} vs {run_b}")
    print(f"  {line}")
    print(f"  {'':20s} {'RUN A':>10s} {'RUN B':>10s} {'DELTA':>10s}")

    # Display order for key metrics
    display = [
        ("Trades",   "n_trades",   "trades"),
        ("Win Rate", "win_rate",   None),
        ("PnL",      "pnl",        "total_pnl"),
        ("ROI %",    "roi_pct",    "roi"),
        ("Sharpe",   "sharpe",     None),
        ("Sortino",  "sortino",    None),
        ("MaxDD",    "max_dd_pct", "max_dd"),
    ]

    for label, key, alt_key in display:
        m = metrics.get(key) or (metrics.get(alt_key) if alt_key else None)
        if m is None:
            continue
        va, vb, delta = m["a"], m["b"], m["delta"]
        if delta is not None:
            print(f"  {label:20s} {_fmt(va):>10s} {_fmt(vb):>10s} {_fmt(delta, sign=True):>10s}")
        else:
            print(f"  {label:20s} {_fmt(va):>10s} {_fmt(vb):>10s} {'':>10s}")

    # Trade count from files
    if tc:
        ta, tb = tc.get("a", 0), tc.get("b", 0)
        if "n_trades" not in metrics and "trades" not in metrics:
            print(f"  {'Trades (file)':20s} {ta:>10d} {tb:>10d} {tb - ta:>+10d}")

    print(f"  {line}")

    if config_diff:
        print("  CONFIG CHANGES:")
        for item in config_diff[:25]:
            k = item["key"]
            va = _compact(item["a"])
            vb = _compact(item["b"])
            print(f"    {k:30s} {va} -> {vb}")
        if len(config_diff) > 25:
            print(f"    ... and {len(config_diff) - 25} more")
    else:
        print("  CONFIG: identical")

    print()


def _fmt(v, sign=False) -> str:
    """Format a numeric value for display."""
    if v is None:
        return "-"
    if isinstance(v, float):
        if sign:
            return f"{v:+.2f}"
        return f"{v:.2f}"
    if isinstance(v, int):
        if sign:
            return f"{v:+d}"
        return str(v)
    return str(v)


def _compact(v) -> str:
    """Compact repr of a config value for the diff table."""
    if isinstance(v, str):
        return v
    if isinstance(v, (list, dict)):
        s = json.dumps(v, default=str)
        return s if len(s) <= 40 else s[:37] + "..."
    return str(v)
