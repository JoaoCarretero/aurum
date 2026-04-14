"""
AURUM Finance - SQLite database for run history and trade logs.
DB lives at data/aurum.db (gitignored with the rest of data/).
"""
import json
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path("data/aurum.db")

_ENGINE_ALIASES = {
    "backtest": "citadel",
    "thoth": "bridgewater",
    "mercurio": "jump",
    "newton": "deshaw",
    "arbitrage": "janestreet",
    "jane_street": "janestreet",
    "jane street": "janestreet",
}

_PARENT_TO_ENGINE = {
    "runs": "citadel",
    "bridgewater": "bridgewater",
    "jump": "jump",
    "deshaw": "deshaw",
    "renaissance": "renaissance",
    "millennium": "millennium",
    "twosigma": "twosigma",
    "aqr": "aqr",
    "janestreet": "janestreet",
}

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


def _normalize_engine(engine: str | None, data: dict | None = None, json_path: str | None = None) -> str:
    text = str(engine or "").strip().lower()
    if text in _ENGINE_ALIASES:
        return _ENGINE_ALIASES[text]
    if text:
        return text

    payload = data or {}
    payload_engine = str(payload.get("engine") or "").strip().lower()
    if payload_engine in _ENGINE_ALIASES:
        return _ENGINE_ALIASES[payload_engine]
    if payload_engine:
        return payload_engine.replace(" ", "")

    if json_path:
        path = Path(json_path)
        for parent in (path.parent, path.parent.parent, path.parent.parent.parent):
            name = parent.name.lower()
            if name in _PARENT_TO_ENGINE:
                return _PARENT_TO_ENGINE[name]

    run_id = str(payload.get("run_id") or "").strip().lower()
    if "_" in run_id:
        prefix = run_id.split("_", 1)[0]
        return _ENGINE_ALIASES.get(prefix, prefix)
    return "unknown"


def _normalize_run_id(run_id: str | None, engine: str, json_path: str | None = None) -> str:
    raw = str(run_id or "").strip()
    if raw.startswith(f"{engine}_"):
        return raw
    if raw and raw[:4].isdigit() and raw.count("_") >= 2:
        return f"{engine}_{raw}"
    if raw:
        return raw
    if json_path:
        folder = Path(json_path).resolve().parent.parent.name
        if folder:
            return folder if folder.startswith(f"{engine}_") else f"{engine}_{folder}"
    return datetime.now().strftime("%Y-%m-%d_%H%M")


def _extract_run_fields(
    data: dict,
    engine: str,
    json_path: str,
) -> tuple[str, str | None, int | None, int | None, float | None, float | None, dict, dict]:
    summary = data.get("summary", {}) if isinstance(data.get("summary"), dict) else {}
    config = data.get("config", {}) if isinstance(data.get("config"), dict) else {}

    interval = (
        data.get("interval")
        or config.get("interval")
        or config.get("INTERVAL")
        or config.get("ENTRY_TF")
    )
    scan_days = config.get("scan_days") or config.get("SCAN_DAYS") or data.get("scan_days")
    n_candles = data.get("n_candles") or config.get("n_candles") or config.get("N_CANDLES")
    if scan_days is None and interval and n_candles:
        per_day = {"1m": 1440, "3m": 480, "5m": 288, "15m": 96, "30m": 48, "1h": 24, "2h": 12, "4h": 6, "1d": 1}.get(str(interval))
        if per_day:
            scan_days = int(round(float(n_candles) / per_day))

    symbols = config.get("symbols") or data.get("symbols") or []
    n_symbols = data.get("n_symbols")
    if n_symbols is None and isinstance(symbols, list):
        n_symbols = len(symbols)

    roi = data.get("roi")
    if roi is None:
        roi = summary.get("ret") or summary.get("roi") or summary.get("roi_pct")

    max_dd = data.get("max_dd_pct")
    if max_dd is None:
        max_dd = summary.get("max_dd_pct") or summary.get("max_dd")

    run_id = _normalize_run_id(data.get("run_id"), engine, json_path)
    return run_id, interval, scan_days, n_symbols, roi, max_dd, summary, config


def save_run(engine: str, json_path: str) -> str | None:
    """Read a JSON report and persist run + trades to the DB. Returns run_id."""
    _base = Path("data").resolve()
    resolved = Path(json_path).resolve()
    if not resolved.is_relative_to(_base):
        print(f"  DB: path {json_path} is outside data directory")
        return None
    try:
        with open(resolved, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"  DB: erro ao ler {json_path}: {e}")
        return None

    engine = _normalize_engine(engine, data, str(resolved))
    run_id, interval, scan_days, n_symbols, roi, max_dd, summary, config = _extract_run_fields(
        data, engine, str(resolved)
    )

    conn = _connect()
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO runs
            (run_id, engine, version, timestamp, interval, scan_days, n_symbols,
             account_size, leverage, roi, max_dd, sharpe, sortino, calmar,
             win_rate, n_trades, final_equity, config_json, json_path)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                engine,
                data.get("version"),
                data.get("timestamp", datetime.now().isoformat()),
                interval,
                scan_days,
                n_symbols,
                data.get("account_size", config.get("account_size", 10000)),
                data.get("leverage", config.get("leverage", 1.0)),
                roi,
                max_dd,
                data.get("sharpe", summary.get("sharpe")),
                data.get("sortino", summary.get("sortino")),
                data.get("calmar", summary.get("calmar")),
                data.get("win_rate", summary.get("win_rate")),
                data.get("n_trades", summary.get("closed") or summary.get("total")),
                data.get("final_equity", summary.get("final_equity")),
                json.dumps(config, default=str),
                str(resolved),
            ),
        )

        trades = data.get("trades", [])
        for t in trades:
            conn.execute(
                """
                INSERT INTO trades
                (run_id, symbol, strategy, direction, entry_price, exit_price,
                 stop, target, pnl, result, rr, score, macro_bias, vol_regime,
                 duration, trade_time, chop_trade, details_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
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
                    json.dumps(
                        {
                            k: v
                            for k, v in t.items()
                            if k
                            not in (
                                "symbol",
                                "direction",
                                "entry",
                                "exit_p",
                                "stop",
                                "target",
                                "pnl",
                                "result",
                                "rr",
                                "score",
                                "macro_bias",
                                "vol_regime",
                                "duration",
                                "time",
                                "chop_trade",
                                "strategy",
                            )
                        },
                        default=str,
                    ),
                ),
            )

        conn.commit()
        return run_id
    finally:
        conn.close()


def register_run(
    run_id: str,
    engine: str,
    json_path: str,
    roi: float | None = None,
    sharpe: float | None = None,
    sortino: float | None = None,
    win_rate: float | None = None,
    n_trades: int | None = None,
    final_equity: float | None = None,
    account_size: float | None = None,
    interval: str | None = None,
    n_symbols: int | None = None,
    version: str | None = None,
) -> str:
    """Lightweight run registrar for engines that already persist JSON/index elsewhere."""
    _base = Path("data").resolve()
    resolved = Path(json_path).resolve()
    if not resolved.is_relative_to(_base):
        raise ValueError(f"path {json_path} is outside data directory")

    engine = _normalize_engine(engine, {}, str(resolved))
    run_id = _normalize_run_id(run_id, engine, str(resolved))

    conn = _connect()
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO runs
            (run_id, engine, version, timestamp, interval, scan_days, n_symbols,
             account_size, leverage, roi, max_dd, sharpe, sortino, calmar,
             win_rate, n_trades, final_equity, config_json, json_path)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id,
                engine,
                version,
                datetime.now().isoformat(),
                interval,
                None,
                n_symbols,
                account_size,
                None,
                roi,
                None,
                sharpe,
                sortino,
                None,
                win_rate,
                n_trades,
                final_equity,
                json.dumps({}, default=str),
                str(resolved),
            ),
        )
        conn.commit()
        return run_id
    finally:
        conn.close()


def repair_run(json_path: str, engine: str | None = None) -> str | None:
    """Re-ingest a report, normalizing DB metadata from the artifact itself."""
    return save_run(engine or "", json_path)


def list_runs(engine: str | None = None, limit: int = 20) -> list[dict]:
    conn = _connect()
    try:
        if engine:
            rows = conn.execute(
                "SELECT * FROM runs WHERE engine=? ORDER BY timestamp DESC LIMIT ?",
                (engine, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
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
            "SELECT * FROM trades WHERE run_id=? ORDER BY id", (run_id,)
        ).fetchall()
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
            "WHERE roi IS NOT NULL ORDER BY roi DESC LIMIT 1"
        ).fetchone()
        return {
            "total_runs": total_runs,
            "total_trades": total_trades,
            "by_engine": [dict(r) for r in by_engine],
            "best_run": dict(best) if best else None,
        }
    finally:
        conn.close()
