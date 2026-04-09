"""
AURUM Finance — NEXUS API routes.
All route groups organized with APIRouter.
"""
import json
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, status
from pydantic import BaseModel, EmailStr

from api.models import get_conn
from api.auth import (
    hash_password,
    verify_password,
    create_token,
    decode_token,
    get_current_user,
    require_admin,
)
from core import proc
from core import db as trade_db

# ═════════════════════════════════════════════════════════════════
# Request / Response schemas
# ═════════════════════════════════════════════════════════════════

class RegisterRequest(BaseModel):
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class RefreshRequest(BaseModel):
    token: str

class DepositRequest(BaseModel):
    amount: float
    method: str

class WithdrawRequest(BaseModel):
    amount: float

class EngineAction(BaseModel):
    engine: str


# ═════════════════════════════════════════════════════════════════
# AUTH ROUTES — /api/auth
# ═════════════════════════════════════════════════════════════════

auth_router = APIRouter(prefix="/api/auth", tags=["auth"])


@auth_router.post("/register")
async def register(req: RegisterRequest):
    """Register a new user and create their account."""
    if not req.email or not req.password:
        raise HTTPException(status_code=400, detail="Email and password required")
    if len(req.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    conn = get_conn()
    try:
        existing = conn.execute(
            "SELECT id FROM users WHERE email = ?", (req.email,)
        ).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="Email already registered")

        now = datetime.now(timezone.utc).isoformat()
        pw_hash = hash_password(req.password)

        cursor = conn.execute(
            "INSERT INTO users (email, password_hash, created_at, role) VALUES (?, ?, ?, ?)",
            (req.email, pw_hash, now, "viewer"),
        )
        user_id = cursor.lastrowid

        conn.execute(
            "INSERT INTO accounts (user_id, balance, total_deposited, total_withdrawn) "
            "VALUES (?, 0, 0, 0)",
            (user_id,),
        )
        conn.commit()

        token = create_token({"sub": user_id, "email": req.email, "role": "viewer"})
        return {"message": "User created", "user_id": user_id, "token": token}
    finally:
        conn.close()


@auth_router.post("/login")
async def login(req: LoginRequest):
    """Authenticate and return a JWT token."""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT id, email, password_hash, role FROM users WHERE email = ?",
            (req.email,),
        ).fetchone()
    finally:
        conn.close()

    if not row or not verify_password(req.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_token({"sub": row["id"], "email": row["email"], "role": row["role"]})
    return {"token": token, "user_id": row["id"], "role": row["role"]}


@auth_router.post("/refresh")
async def refresh(req: RefreshRequest):
    """Refresh an existing token (returns a new one with extended expiry)."""
    try:
        payload = decode_token(req.token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    new_token = create_token({
        "sub": payload["sub"],
        "email": payload.get("email"),
        "role": payload.get("role"),
    })
    return {"token": new_token}


# ═════════════════════════════════════════════════════════════════
# ACCOUNT ROUTES — /api/account
# ═════════════════════════════════════════════════════════════════

account_router = APIRouter(prefix="/api/account", tags=["account"])


@account_router.get("/")
async def get_account(user: dict = Depends(get_current_user)):
    """Get account balance, PnL, and allocation info."""
    conn = get_conn()
    try:
        acct = conn.execute(
            "SELECT * FROM accounts WHERE user_id = ?", (user["id"],)
        ).fetchone()
        if not acct:
            raise HTTPException(status_code=404, detail="Account not found")

        acct_dict = dict(acct)
        pnl = acct_dict["balance"] - acct_dict["total_deposited"] + acct_dict["total_withdrawn"]

        # Engine allocations from engine_state
        engines = conn.execute("SELECT engine, status, fitness_score FROM engine_state").fetchall()
        allocations = [dict(e) for e in engines]

        return {
            "balance": acct_dict["balance"],
            "total_deposited": acct_dict["total_deposited"],
            "total_withdrawn": acct_dict["total_withdrawn"],
            "pnl": round(pnl, 2),
            "allocations": allocations,
        }
    finally:
        conn.close()


@account_router.post("/deposit")
async def deposit(req: DepositRequest, user: dict = Depends(get_current_user)):
    """Register a deposit."""
    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")

    conn = get_conn()
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO deposits (user_id, amount, method, status, created_at) "
            "VALUES (?, ?, ?, 'pending', ?)",
            (user["id"], req.amount, req.method, now),
        )

        # Update account balance and totals
        conn.execute(
            "UPDATE accounts SET balance = balance + ?, total_deposited = total_deposited + ? "
            "WHERE user_id = ?",
            (req.amount, req.amount, user["id"]),
        )
        conn.commit()
        return {"message": "Deposit registered", "amount": req.amount, "status": "pending"}
    finally:
        conn.close()


@account_router.post("/withdraw")
async def withdraw(req: WithdrawRequest, user: dict = Depends(get_current_user)):
    """Request a withdrawal."""
    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")

    conn = get_conn()
    try:
        acct = conn.execute(
            "SELECT balance FROM accounts WHERE user_id = ?", (user["id"],)
        ).fetchone()
        if not acct or acct["balance"] < req.amount:
            raise HTTPException(status_code=400, detail="Insufficient balance")

        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO withdrawals (user_id, amount, status, created_at) "
            "VALUES (?, ?, 'pending', ?)",
            (user["id"], req.amount, now),
        )

        conn.execute(
            "UPDATE accounts SET balance = balance - ?, total_withdrawn = total_withdrawn + ? "
            "WHERE user_id = ?",
            (req.amount, req.amount, user["id"]),
        )
        conn.commit()
        return {"message": "Withdrawal requested", "amount": req.amount, "status": "pending"}
    finally:
        conn.close()


@account_router.get("/history")
async def account_history(
    user: dict = Depends(get_current_user),
    limit: int = Query(50, ge=1, le=500),
):
    """Get deposit and withdrawal history."""
    conn = get_conn()
    try:
        deposits = conn.execute(
            "SELECT id, amount, method, status, tx_hash, created_at "
            "FROM deposits WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user["id"], limit),
        ).fetchall()

        withdrawals = conn.execute(
            "SELECT id, amount, status, created_at "
            "FROM withdrawals WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user["id"], limit),
        ).fetchall()

        return {
            "deposits": [dict(d) for d in deposits],
            "withdrawals": [dict(w) for w in withdrawals],
        }
    finally:
        conn.close()


# ═════════════════════════════════════════════════════════════════
# TRADING ROUTES — /api/trading
# ═════════════════════════════════════════════════════════════════

trading_router = APIRouter(prefix="/api/trading", tags=["trading"])


@trading_router.get("/status")
async def trading_status(user: dict = Depends(get_current_user)):
    """Get all engine states."""
    conn = get_conn()
    try:
        rows = conn.execute("SELECT * FROM engine_state").fetchall()
        engines_db = {r["engine"]: dict(r) for r in rows}
    finally:
        conn.close()

    # Merge with live process info from proc module
    live_procs = proc.list_procs()
    proc_map = {}
    for p in live_procs:
        proc_map[p.get("engine", "")] = {
            "pid": p.get("pid"),
            "alive": p.get("alive", False),
            "started": p.get("started"),
            "status": p.get("status"),
        }

    result = {}
    all_engines = set(list(engines_db.keys()) + list(proc.ENGINE_NAMES.keys()))
    for eng in all_engines:
        result[eng] = {
            "db_state": engines_db.get(eng, {}),
            "process": proc_map.get(eng, {"alive": False, "status": "stopped"}),
        }

    return {"engines": result}


@trading_router.get("/positions")
async def open_positions(user: dict = Depends(get_current_user)):
    """Get open positions from proc state files."""
    positions = []
    state_dir = Path("data")
    if state_dir.exists():
        for f in state_dir.glob("*_positions.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    positions.extend(data)
                elif isinstance(data, dict):
                    positions.append(data)
            except (json.JSONDecodeError, OSError):
                continue

    # Also check proc state for live positions
    state_file = Path("data/.aurum_procs.json")
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
            for pid_str, info in state.get("procs", {}).items():
                engine = info.get("engine", "")
                pos_file = state_dir / f"{engine}_live_state.json"
                if pos_file.exists():
                    try:
                        live_data = json.loads(pos_file.read_text(encoding="utf-8"))
                        open_pos = live_data.get("open_positions", [])
                        positions.extend(open_pos)
                    except (json.JSONDecodeError, OSError):
                        continue
        except (json.JSONDecodeError, OSError):
            pass

    return {"positions": positions}


@trading_router.get("/trades")
async def trade_history(
    user: dict = Depends(get_current_user),
    engine: Optional[str] = Query(None),
    symbol: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
):
    """Get trade history with filters. Reads from core/db.py trade data."""
    runs = trade_db.list_runs(engine=engine, limit=limit)

    all_trades = []
    for run in runs:
        trades = trade_db.get_trades(run["run_id"])
        for t in trades:
            # Apply symbol filter
            if symbol and t.get("symbol") != symbol:
                continue
            # Apply date filters
            trade_time = t.get("trade_time", "")
            if date_from and trade_time < date_from:
                continue
            if date_to and trade_time > date_to:
                continue
            t["engine"] = run.get("engine")
            t["run_id"] = run["run_id"]
            all_trades.append(t)

    # Sort by trade time descending and apply limit
    all_trades.sort(key=lambda x: x.get("trade_time", ""), reverse=True)
    return {"trades": all_trades[:limit]}


@trading_router.post("/start")
async def start_engine(req: EngineAction, user: dict = Depends(require_admin)):
    """Start an engine by name (admin only)."""
    if req.engine not in proc.ENGINES:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown engine '{req.engine}'. Available: {list(proc.ENGINES.keys())}",
        )

    result = proc.spawn(req.engine)
    if result is None:
        raise HTTPException(status_code=409, detail=f"Engine '{req.engine}' is already running or failed to start")

    # Update engine_state in DB
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO engine_state (engine, status) VALUES (?, 'running') "
            "ON CONFLICT(engine) DO UPDATE SET status = 'running'",
            (req.engine,),
        )
        conn.commit()
    finally:
        conn.close()

    return {"message": f"Engine '{req.engine}' started", "pid": result.get("pid")}


@trading_router.post("/stop")
async def stop_engine(req: EngineAction, user: dict = Depends(require_admin)):
    """Stop an engine by name (admin only)."""
    live_procs = proc.list_procs()
    target = None
    for p in live_procs:
        if p.get("engine") == req.engine and p.get("alive"):
            target = p
            break

    if not target:
        raise HTTPException(status_code=404, detail=f"Engine '{req.engine}' is not running")

    success = proc.stop_proc(target["pid"])
    if not success:
        raise HTTPException(status_code=500, detail="Failed to stop engine process")

    # Update engine_state in DB
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE engine_state SET status = 'stopped' WHERE engine = ?",
            (req.engine,),
        )
        conn.commit()
    finally:
        conn.close()

    return {"message": f"Engine '{req.engine}' stopped"}


# ═════════════════════════════════════════════════════════════════
# ANALYTICS ROUTES — /api/analytics
# ═════════════════════════════════════════════════════════════════

analytics_router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@analytics_router.get("/equity")
async def equity_curve(
    user: dict = Depends(get_current_user),
    engine: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """Get equity curve data from run history."""
    runs = trade_db.list_runs(engine=engine, limit=limit)

    curve = []
    for run in reversed(runs):  # oldest first
        curve.append({
            "run_id": run["run_id"],
            "engine": run.get("engine"),
            "timestamp": run.get("timestamp"),
            "final_equity": run.get("final_equity"),
            "roi": run.get("roi"),
            "n_trades": run.get("n_trades"),
        })

    return {"equity_curve": curve}


@analytics_router.get("/darwin")
async def darwin_state(user: dict = Depends(get_current_user)):
    """Get Darwin evolutionary state — fitness, allocations, mutations."""
    conn = get_conn()
    try:
        # Latest engine fitness scores
        engines = conn.execute(
            "SELECT engine, fitness_score FROM engine_state"
        ).fetchall()

        # Recent darwin log entries
        log = conn.execute(
            "SELECT * FROM darwin_log ORDER BY created_at DESC LIMIT 100"
        ).fetchall()

        # Latest generation
        latest_gen = conn.execute(
            "SELECT MAX(generation) as gen FROM darwin_log"
        ).fetchone()

        return {
            "engine_fitness": [dict(e) for e in engines],
            "latest_generation": latest_gen["gen"] if latest_gen else 0,
            "log": [dict(l) for l in log],
        }
    finally:
        conn.close()


@analytics_router.get("/performance")
async def per_engine_performance(user: dict = Depends(get_current_user)):
    """Per-engine performance metrics from run history."""
    stats = trade_db.stats_summary()
    return {"performance": stats}


@analytics_router.get("/benchmark")
async def benchmark(user: dict = Depends(get_current_user)):
    """Comparison data across engines."""
    runs = trade_db.list_runs(limit=200)

    by_engine: dict[str, list] = {}
    for run in runs:
        eng = run.get("engine", "unknown")
        if eng not in by_engine:
            by_engine[eng] = []
        by_engine[eng].append({
            "run_id": run["run_id"],
            "roi": run.get("roi"),
            "sharpe": run.get("sharpe"),
            "sortino": run.get("sortino"),
            "calmar": run.get("calmar"),
            "win_rate": run.get("win_rate"),
            "n_trades": run.get("n_trades"),
        })

    # Summary per engine
    summary = {}
    for eng, eng_runs in by_engine.items():
        rois = [r["roi"] for r in eng_runs if r["roi"] is not None]
        sharpes = [r["sharpe"] for r in eng_runs if r["sharpe"] is not None]
        summary[eng] = {
            "n_runs": len(eng_runs),
            "avg_roi": round(sum(rois) / len(rois), 4) if rois else None,
            "best_roi": round(max(rois), 4) if rois else None,
            "avg_sharpe": round(sum(sharpes) / len(sharpes), 2) if sharpes else None,
            "runs": eng_runs[:10],  # latest 10
        }

    return {"benchmark": summary}


# ═════════════════════════════════════════════════════════════════
# WEBSOCKET — /api/live/ws
# ═════════════════════════════════════════════════════════════════

async def live_ws(websocket: WebSocket):
    """WebSocket endpoint streaming engine status every 5 seconds."""
    await websocket.accept()
    try:
        while True:
            # Gather engine states
            conn = get_conn()
            try:
                engine_rows = conn.execute("SELECT * FROM engine_state").fetchall()
                engines_db = [dict(r) for r in engine_rows]
            finally:
                conn.close()

            # Live process info
            live_procs = proc.list_procs()
            proc_status = []
            for p in live_procs:
                proc_status.append({
                    "engine": p.get("engine"),
                    "pid": p.get("pid"),
                    "alive": p.get("alive", False),
                    "status": p.get("status"),
                    "started": p.get("started"),
                })

            payload = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "engines": engines_db,
                "processes": proc_status,
            }

            await websocket.send_json(payload)
            await asyncio.sleep(5)
    except Exception:
        # Client disconnected or error — close gracefully
        try:
            await websocket.close()
        except Exception:
            pass
