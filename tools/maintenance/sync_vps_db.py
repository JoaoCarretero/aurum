"""Mirror VPS aurum.db live_trades + live_signals into local DB.

Cockpit /v1/runs/{id}/trades works for paper trades, but /signals
isn't on the VPS deploy yet (added in commit b53fb0e, post-5dfa479).
This script bypasses the cockpit by SSH-pulling the VPS sqlite file
directly and merging via upsert (idempotent — UNIQUE keys dedupe).

Run dirs on VPS = "/srv/aurum.finance/data/aurum.db".
SSH config comes from `core.risk.key_store.load_runtime_keys()['vps_ssh']`.

Usage:
    # Pull VPS DB and merge (default)
    python -m tools.maintenance.sync_vps_db

    # Mirror an already-downloaded file
    python -m tools.maintenance.sync_vps_db --vps-db /tmp/vps_aurum.db

    # Custom local DB
    python -m tools.maintenance.sync_vps_db --local-db /path/to/local.db
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from core.ops.db_live_trades import upsert_signal, upsert_trade

DEFAULT_LOCAL_DB = Path("data/aurum.db")
DEFAULT_VPS_DB_PATH = "/srv/aurum.finance/data/aurum.db"


def _table_rows_as_dicts(conn: sqlite3.Connection,
                          table: str) -> list[dict]:
    """Return all rows from `table` as a list of dicts. Returns [] if the
    table doesn't exist (empty / fresh VPS DB)."""
    try:
        cur = conn.execute(f"SELECT * FROM {table}")
    except sqlite3.OperationalError:
        return []
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _row_to_trade_payload(row: dict) -> dict:
    """A live_trades row read back is already in canonical shape — strip
    the synthetic 'id' (auto-incremented locally) and 'run_id' (passed
    separately to upsert_trade)."""
    payload = {k: v for k, v in row.items() if k not in ("id", "run_id")
               and v is not None}
    return payload


def _row_to_signal_payload(row: dict) -> dict:
    payload = {k: v for k, v in row.items() if k not in ("id", "run_id")
               and v is not None}
    return payload


_LIVE_RUNS_COLS = (
    "engine", "mode", "started_at", "ended_at", "run_dir", "status",
    "tick_count", "novel_count", "open_count", "equity", "last_tick_at",
    "host", "label", "notes",
)


def _mirror_live_runs(vps_conn: sqlite3.Connection,
                      local_conn: sqlite3.Connection) -> int:
    """Mirror live_runs via INSERT OR REPLACE keyed on run_id.

    db_live_runs.upsert is global-DB-bound (uses module-level DB_PATH), so
    bypass it: write rows directly. live_runs.run_id is PRIMARY KEY, so
    INSERT OR REPLACE is idempotent and absorbs mutable-field updates.
    """
    rows = _table_rows_as_dicts(vps_conn, "live_runs")
    n = 0
    for row in rows:
        run_id = row.get("run_id")
        if not run_id:
            continue
        cols = ["run_id"] + [c for c in _LIVE_RUNS_COLS if row.get(c) is not None]
        placeholders = ",".join("?" * len(cols))
        values = [run_id] + [row[c] for c in cols[1:]]
        local_conn.execute(
            f"INSERT OR REPLACE INTO live_runs ({','.join(cols)}) "
            f"VALUES ({placeholders})",
            values,
        )
        n += 1
    return n


def mirror_db_file(vps_db_path: str, local_db_path: str) -> tuple[int, int, int]:
    """Mirror live_trades + live_signals + live_runs from a downloaded VPS
    DB file into the local DB. Returns (trades, signals, runs) inserted."""
    vps_conn = sqlite3.connect(vps_db_path)
    try:
        trade_rows = _table_rows_as_dicts(vps_conn, "live_trades")
        signal_rows = _table_rows_as_dicts(vps_conn, "live_signals")
        local_conn = sqlite3.connect(local_db_path)
        try:
            n_trades = 0
            for row in trade_rows:
                run_id = row.get("run_id")
                if not run_id:
                    continue
                if upsert_trade(local_conn, run_id,
                                  _row_to_trade_payload(row)):
                    n_trades += 1
            n_signals = 0
            for row in signal_rows:
                run_id = row.get("run_id")
                if not run_id:
                    continue
                if upsert_signal(local_conn, run_id,
                                  _row_to_signal_payload(row)):
                    n_signals += 1
            n_runs = _mirror_live_runs(vps_conn, local_conn)
            local_conn.commit()
            return n_trades, n_signals, n_runs
        finally:
            local_conn.close()
    finally:
        vps_conn.close()


def _ssh_args(ssh_cfg: dict) -> tuple[list[str], str, str, int]:
    """Common SSH/SCP arg builder. Returns (key_args, host, user, port)."""
    host = ssh_cfg.get("host")
    user = ssh_cfg.get("user", "root")
    port = int(ssh_cfg.get("ssh_port", 22))
    key_path = ssh_cfg.get("key_path")
    common = ["-o", "StrictHostKeyChecking=accept-new",
              "-o", "ConnectTimeout=8"]
    if key_path:
        common += ["-i", str(key_path)]
    return common, host, user, port


def _scp_pull_vps_db(dest: Path) -> bool:
    """Snapshot the VPS DB atomically (sqlite3 .backup, WAL-safe) then
    scp it. Without the .backup step, scp of aurum.db alone misses
    recent writes still in aurum.db-wal — VPS uses WAL journal_mode and
    the in-flight 4MB+ WAL holds today's live_trades / live_signals."""
    try:
        from core.risk.key_store import load_runtime_keys
        ssh = load_runtime_keys().get("vps_ssh") or {}
    except Exception as exc:  # noqa: BLE001
        print(f"sync_vps_db: failed to load vps_ssh config: {exc}",
              file=sys.stderr)
        return False
    common, host, user, port = _ssh_args(ssh)
    if not host:
        print("sync_vps_db: vps_ssh.host missing in keys.json",
              file=sys.stderr)
        return False
    import uuid
    remote_snapshot = f"/tmp/aurum_db_snapshot_{uuid.uuid4().hex}.db"
    # 1. atomic .backup on VPS
    ssh_cmd = ["ssh", "-p", str(port)] + common + [
        f"{user}@{host}",
        f"sqlite3 {DEFAULT_VPS_DB_PATH} \".backup '{remote_snapshot}'\" "
        f"&& echo OK || (echo FAIL; exit 1)",
    ]
    try:
        backup = subprocess.run(ssh_cmd, capture_output=True, text=True,
                                  timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"sync_vps_db: ssh .backup failed: {exc}", file=sys.stderr)
        return False
    if backup.returncode != 0 or "OK" not in backup.stdout:
        print(f"sync_vps_db: ssh .backup exit={backup.returncode}\n"
              f"stdout={backup.stdout}\nstderr={backup.stderr}",
              file=sys.stderr)
        return False
    # 2. scp the snapshot
    scp_cmd = ["scp", "-P", str(port)] + common + [
        f"{user}@{host}:{remote_snapshot}", str(dest),
    ]
    try:
        result = subprocess.run(scp_cmd, capture_output=True, text=True,
                                  timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"sync_vps_db: scp failed: {exc}", file=sys.stderr)
        return False
    if result.returncode != 0:
        print(f"sync_vps_db: scp exit={result.returncode}\n{result.stderr}",
              file=sys.stderr)
        return False
    # 3. cleanup remote snapshot (best-effort)
    cleanup_cmd = ["ssh", "-p", str(port)] + common + [
        f"{user}@{host}", f"rm -f {remote_snapshot}",
    ]
    subprocess.run(cleanup_cmd, capture_output=True, timeout=10)
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--vps-db", type=str,
                    help="path to a pre-downloaded VPS DB file (skip scp)")
    ap.add_argument("--local-db", type=str, default=str(DEFAULT_LOCAL_DB),
                    help="local DB to merge into (default: data/aurum.db)")
    args = ap.parse_args()

    if args.vps_db:
        vps_path = Path(args.vps_db)
        if not vps_path.exists():
            print(f"sync_vps_db: {vps_path} not found", file=sys.stderr)
            return 1
        cleanup = False
    else:
        tmpdir = Path(tempfile.mkdtemp(prefix="aurum_vps_db_"))
        vps_path = tmpdir / "vps_aurum.db"
        print(f"scp pull -> {vps_path}")
        if not _scp_pull_vps_db(vps_path):
            shutil.rmtree(tmpdir, ignore_errors=True)
            return 1
        cleanup = True

    try:
        n_t, n_s, n_r = mirror_db_file(str(vps_path), args.local_db)
        print(f"merged {n_t} trades + {n_s} signals + {n_r} runs "
              f"into {args.local_db}")
        return 0
    finally:
        if cleanup:
            shutil.rmtree(vps_path.parent, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
