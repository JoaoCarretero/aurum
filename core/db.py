"""
AURUM Finance — SQLite database for run history and trade logs.
DB lives at data/aurum.db (gitignored with the rest of data/).
"""
import json
import sqlite3
from pathlib import Path
from datetime import datetime

DB_PATH = Path("data/aurum.db")

# ── Schema ────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id      TEXT PRIMARY KEY,
    engine      TEXT NOT NULL,
    version     TEXT,
    timestamp   TEXT NOT NULL,
    interval    TEXT,
    scan_days   INTEGER,
    n_symbols   INTEGER,
    account_size REAL,
    leverage    REAL,
    roi         REAL,
    max_dd      REAL,
    sharpe      REAL,
    sortino     REAL,
    calmar      REAL,
    win_rate    REAL,
    n_trades    INTEGER,
    final_equity REAL,
    veredito    TEXT,
    config_json TEXT,
    json_path   TEXT
);

CREATE TABLE IF NOT EXISTS trades (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL,
    symbol      TEXT,
    strategy    TEXT,
    direction   TEXT,
    entry_price REAL,
    exit_price  REAL,
    stop        REAL,
    target      REAL,
    pnl         REAL,
    result      TEXT,
    rr          REAL,
    score       REAL,
    macro_bias  TEXT,
    vol_regime  TEXT,
    duration    INTEGER,
    trade_time  TEXT,
    chop_trade  INTEGER DEFAULT 0,
    details_json TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_trades_run   ON trades(run_id);
CREATE INDEX IF NOT EXISTS idx_trades_sym   ON trades(symbol);
CREATE INDEX IF NOT EXISTS idx_trades_result ON trades(result);
"""


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


# ── Write ─────────────────────────────────────────────────────

def save_run(engine: str, json_path: str) -> str | None:
    """Read a JSON report and persist run + trades to the DB. Returns run_id."""
    # validate path is within data/ directory
    _base = Path("data").resolve()
    if not Path(json_path).resolve().is_relative_to(_base):
        print(f"  DB: path {json_path} is outside data directory")
        return None
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"  DB: erro ao ler {json_path}: {e}")
        return None

    run_id  = data.get("run_id", datetime.now().strftime("%Y-%m-%d_%H%M"))
    summary = data.get("summary", {})
    config  = data.get("config", {})

    conn = _connect()
    try:
        conn.execute("""
            INSERT OR REPLACE INTO runs
            (run_id, engine, version, timestamp, interval, scan_days, n_symbols,
             account_size, leverage, roi, max_dd, sharpe, sortino, calmar,
             win_rate, n_trades, final_equity, config_json, json_path)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            run_id, engine,
            data.get("version"),
            data.get("timestamp", datetime.now().isoformat()),
            config.get("interval"),
            config.get("scan_days") or config.get("n_candles", 0) // (24 * 4) or None,
            len(config.get("symbols", [])),
            config.get("account_size", 10000),
            config.get("leverage", 1.0),
            summary.get("ret"),
            None,  # max_dd — compute from trades if needed
            summary.get("sharpe"),
            summary.get("sortino"),
            summary.get("calmar"),
            summary.get("win_rate"),
            summary.get("closed") or summary.get("total"),
            summary.get("final_equity"),
            json.dumps(config, default=str),
            json_path,
        ))

        # Trades
        trades = data.get("trades", [])
        for t in trades:
            conn.execute("""
                INSERT INTO trades
                (run_id, symbol, strategy, direction, entry_price, exit_price,
                 stop, target, pnl, result, rr, score, macro_bias, vol_regime,
                 duration, trade_time, chop_trade, details_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                run_id,
                t.get("symbol"),
                t.get("strategy", engine),
                t.get("direction"),
                t.get("entry"),
                t.get("exit_p"),
                t.get("stop"),
                t.get("target"),
                t.get("pnl"),
                t.get("result"),
                t.get("rr"),
                t.get("score"),
                t.get("macro_bias"),
                t.get("vol_regime"),
                t.get("duration"),
                t.get("time"),
                1 if t.get("chop_trade") else 0,
                json.dumps({k: v for k, v in t.items()
                            if k not in ("symbol","direction","entry","exit_p",
                                         "stop","target","pnl","result","rr",
                                         "score","macro_bias","vol_regime",
                                         "duration","time","chop_trade","strategy")},
                           default=str),
            ))

        conn.commit()
        return run_id
    finally:
        conn.close()


# ── Read ──────────────────────────────────────────────────────

def list_runs(engine: str | None = None, limit: int = 20) -> list[dict]:
    conn = _connect()
    try:
        if engine:
            rows = conn.execute(
                "SELECT * FROM runs WHERE engine=? ORDER BY timestamp DESC LIMIT ?",
                (engine, limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY timestamp DESC LIMIT ?",
                (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_run(run_id: str) -> dict | None:
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_trades(run_id: str) -> list[dict]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM trades WHERE run_id=? ORDER BY id", (run_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()



def delete_run(run_id: str, delete_files: bool = False) -> bool:
    """Delete a run and its trades from the DB. Optionally delete disk files."""
    conn = _connect()
    try:
        row = conn.execute("SELECT json_path FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if not row:
            return False
        conn.execute("DELETE FROM trades WHERE run_id=?", (run_id,))
        conn.execute("DELETE FROM runs WHERE run_id=?", (run_id,))
        conn.commit()
        if delete_files and row["json_path"]:
            import shutil
            folder = Path(row["json_path"]).parent.parent
            _base = Path("data").resolve()
            if folder.resolve().is_relative_to(_base) and folder.exists():
                shutil.rmtree(folder, ignore_errors=True)
        return True
    finally:
        conn.close()


def stats_summary() -> dict:
    """Quick stats across all runs."""
    conn = _connect()
    try:
        total_runs = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        total_trades = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        by_engine = conn.execute(
            "SELECT engine, COUNT(*) as n, ROUND(AVG(roi),2) as avg_roi, "
            "ROUND(AVG(sharpe),2) as avg_sharpe FROM runs GROUP BY engine"
        ).fetchall()
        best = conn.execute(
            "SELECT run_id, engine, roi, sharpe FROM runs "
            "WHERE roi IS NOT NULL ORDER BY roi DESC LIMIT 1").fetchone()
        return {
            "total_runs": total_runs,
            "total_trades": total_trades,
            "by_engine": [dict(r) for r in by_engine],
            "best_run": dict(best) if best else None,
        }
    finally:
        conn.close()
