"""SQLite persistence pra historico de stats por agente.

Tabela unica `research_desk_stats` com linha diaria por agente.
Snapshot de observables (tickets done/active, artifacts, cost).
Ratios ship/iterate/kill sao derivados das linhas via delta entre
dias consecutivos — funcao pura, testavel sem DB.

Design:
  - `connect(db_path)` abre conn com PRAGMA WAL + cria schema IF NOT EXISTS
  - `record_snapshot(conn, ...)` upsert por (agent_key, date)
  - `list_days(conn, agent_key, days)` retorna rows DESC
  - `compute_ratios(rows)` pure — ship/iterate/kill a partir de deltas
  - `ship_iterate_kill_over(rows, window)` — agregado window dias

Convencoes:
  - date e string YYYY-MM-DD (UTC). PK composto (agent_key, date).
  - Numeros monetarios em cents (int) pra evitar float drift.

Nao migra dados antigos — schema IF NOT EXISTS criado onde primeiro
`connect` toca o arquivo.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


_SCHEMA = """
CREATE TABLE IF NOT EXISTS research_desk_stats (
    agent_key          TEXT NOT NULL,
    date               TEXT NOT NULL,
    tickets_done       INTEGER NOT NULL DEFAULT 0,
    tickets_active     INTEGER NOT NULL DEFAULT 0,
    artifacts_total    INTEGER NOT NULL DEFAULT 0,
    spent_cents        INTEGER NOT NULL DEFAULT 0,
    runs_total         INTEGER NOT NULL DEFAULT 0,
    runs_success       INTEGER NOT NULL DEFAULT 0,
    runs_error         INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (agent_key, date)
)
"""

_UPSERT = """
INSERT INTO research_desk_stats (
    agent_key, date, tickets_done, tickets_active,
    artifacts_total, spent_cents, runs_total,
    runs_success, runs_error
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(agent_key, date) DO UPDATE SET
    tickets_done    = excluded.tickets_done,
    tickets_active  = excluded.tickets_active,
    artifacts_total = excluded.artifacts_total,
    spent_cents     = excluded.spent_cents,
    runs_total      = excluded.runs_total,
    runs_success    = excluded.runs_success,
    runs_error      = excluded.runs_error
"""

_LIST = """
SELECT agent_key, date, tickets_done, tickets_active,
       artifacts_total, spent_cents, runs_total,
       runs_success, runs_error
FROM research_desk_stats
WHERE agent_key = ?
ORDER BY date DESC
LIMIT ?
"""


@dataclass(frozen=True)
class StatRow:
    agent_key: str
    date: str           # YYYY-MM-DD
    tickets_done: int
    tickets_active: int
    artifacts_total: int
    spent_cents: int
    runs_total: int
    runs_success: int
    runs_error: int


@dataclass(frozen=True)
class RatiosView:
    """Ship/iterate/kill ratio + totais absolutos.

    - ship   = tickets fechados com sucesso na janela
    - iterate = artifacts novos na janela (work-in-progress)
    - kill   = runs com erro / cancelados

    Os 3 sao contagens absolutas; pct e ratio normalizado.
    """
    ship: int
    iterate: int
    kill: int
    total: int          # ship + iterate + kill
    ship_pct: float     # 0..1
    iterate_pct: float
    kill_pct: float


def today_utc() -> str:
    """Data de hoje em UTC YYYY-MM-DD — use sempre na mesma timezone."""
    return dt.datetime.now(dt.timezone.utc).date().isoformat()


def connect(db_path: Path | str) -> sqlite3.Connection:
    """Abre conexao, ativa WAL, garante schema. Idempotente.

    `check_same_thread=False`: a single conn instance can be passed
    across threads. SQLite is db-level safe under WAL (one writer +
    many readers), so this is correct as long as callers don't issue
    overlapping writes from multiple threads. Today the cockpit only
    writes from the main thread (snapshot day-rollover) and reads
    from the same; the relaxed flag is forward-compat for moving
    cost_dashboard fetches off the main thread later.
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.DatabaseError:
        pass  # :memory: ou fs que nao suporta; segue
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def record_snapshot(
    conn: sqlite3.Connection,
    *,
    agent_key: str,
    date: str,
    tickets_done: int = 0,
    tickets_active: int = 0,
    artifacts_total: int = 0,
    spent_cents: int = 0,
    runs_total: int = 0,
    runs_success: int = 0,
    runs_error: int = 0,
) -> None:
    """Upsert diario. Chama uma vez por agent por dia (mais so atualiza)."""
    conn.execute(_UPSERT, (
        agent_key, date, tickets_done, tickets_active,
        artifacts_total, spent_cents, runs_total,
        runs_success, runs_error,
    ))
    conn.commit()


def list_days(
    conn: sqlite3.Connection, agent_key: str, days: int = 30,
) -> list[StatRow]:
    """Retorna ate `days` snapshots mais recentes (DESC por data)."""
    cur = conn.execute(_LIST, (agent_key, days))
    return [_row_to_stat(r) for r in cur.fetchall()]


def _row_to_stat(r: sqlite3.Row) -> StatRow:
    return StatRow(
        agent_key=r["agent_key"],
        date=r["date"],
        tickets_done=int(r["tickets_done"] or 0),
        tickets_active=int(r["tickets_active"] or 0),
        artifacts_total=int(r["artifacts_total"] or 0),
        spent_cents=int(r["spent_cents"] or 0),
        runs_total=int(r["runs_total"] or 0),
        runs_success=int(r["runs_success"] or 0),
        runs_error=int(r["runs_error"] or 0),
    )


# ── Pure aggregations (testaveis sem DB) ──────────────────────────


def compute_ratios(rows: Iterable[StatRow]) -> RatiosView:
    """Calcula ship/iterate/kill a partir de snapshots.

    ship   = delta(tickets_done) entre dia mais velho e mais novo
    iterate = delta(artifacts_total) - ship  (artifacts que nao fecharam)
    kill   = soma de runs_error na janela

    Se 0 ou 1 row nao ha delta; retorna zerado exceto kill (sempre somavel).
    """
    row_list = list(rows)
    if not row_list:
        return _empty_ratios()

    # Rows chegam DESC — converter pra ASC pra delta mais-antigo->mais-novo
    row_list_asc = sorted(row_list, key=lambda r: r.date)

    kill = sum(r.runs_error for r in row_list_asc)

    if len(row_list_asc) < 2:
        return _pack(ship=0, iterate=0, kill=kill)

    oldest = row_list_asc[0]
    newest = row_list_asc[-1]

    ship = max(0, newest.tickets_done - oldest.tickets_done)
    artifact_delta = max(0, newest.artifacts_total - oldest.artifacts_total)
    iterate = max(0, artifact_delta - ship)

    return _pack(ship=ship, iterate=iterate, kill=kill)


def _pack(*, ship: int, iterate: int, kill: int) -> RatiosView:
    total = ship + iterate + kill
    if total == 0:
        return _empty_ratios()
    return RatiosView(
        ship=ship,
        iterate=iterate,
        kill=kill,
        total=total,
        ship_pct=ship / total,
        iterate_pct=iterate / total,
        kill_pct=kill / total,
    )


def _empty_ratios() -> RatiosView:
    return RatiosView(
        ship=0, iterate=0, kill=0, total=0,
        ship_pct=0.0, iterate_pct=0.0, kill_pct=0.0,
    )


def total_spent_last_n_days(rows: Iterable[StatRow], days: int) -> int:
    """Soma spent_cents nas ultimas `days` linhas (DESC por data)."""
    row_list = list(rows)[:days]
    return sum(r.spent_cents for r in row_list)
