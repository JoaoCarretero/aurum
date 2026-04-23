"""
AURUM Finance — NEXUS API database models.
Plain sqlite3, consistent with core/db.py patterns.
DB lives at data/nexus.db (gitignored with the rest of data/).
"""
import sqlite3
from pathlib import Path

DB_PATH = Path("data/nexus.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    role          TEXT DEFAULT 'viewer'
);

CREATE TABLE IF NOT EXISTS accounts (
    user_id          INTEGER UNIQUE NOT NULL,
    balance          REAL DEFAULT 0,
    total_deposited  REAL DEFAULT 0,
    total_withdrawn  REAL DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS deposits (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    amount      REAL NOT NULL,
    method      TEXT,
    status      TEXT DEFAULT 'pending',
    tx_hash     TEXT,
    created_at  TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS withdrawals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    amount      REAL NOT NULL,
    status      TEXT DEFAULT 'pending',
    created_at  TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS engine_state (
    engine        TEXT PRIMARY KEY,
    status        TEXT DEFAULT 'stopped',
    params_json   TEXT,
    last_trade    TEXT,
    fitness_score REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS darwin_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    generation  INTEGER NOT NULL,
    engine      TEXT NOT NULL,
    fitness     REAL,
    allocation  REAL,
    mutation    TEXT,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_deposits_user     ON deposits(user_id);
CREATE INDEX IF NOT EXISTS idx_withdrawals_user  ON withdrawals(user_id);
CREATE INDEX IF NOT EXISTS idx_darwin_engine      ON darwin_log(engine);
"""


def get_conn() -> sqlite3.Connection:
    """Return a connection with row_factory set to sqlite3.Row."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create all tables if they don't exist."""
    conn = get_conn()
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()
