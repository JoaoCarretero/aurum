"""
AURUM Finance — NEXUS API server.
FastAPI app with CORS, rate limiting, and all route groups.
"""
import time
from collections import defaultdict

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from api.models import init_db
from api.routes import (
    auth_router,
    account_router,
    trading_router,
    analytics_router,
    live_ws,
)

# ── App ───────────────────────────────────────────────────────

app = FastAPI(
    title="AURUM Finance API",
    version="1.0.0",
    description="NEXUS — API Bridge & Account Management for AURUM Finance",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS (dev: allow all origins) ─────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Rate Limiting (in-memory, 100 req/min per IP) ────────────

_rate_store: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT = 100
RATE_WINDOW = 60  # seconds


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()

    # Clean old entries
    _rate_store[client_ip] = [
        ts for ts in _rate_store[client_ip] if now - ts < RATE_WINDOW
    ]

    if len(_rate_store[client_ip]) >= RATE_LIMIT:
        return Response(
            content='{"detail":"Rate limit exceeded. Max 100 requests per minute."}',
            status_code=429,
            media_type="application/json",
        )

    _rate_store[client_ip].append(now)
    response = await call_next(request)
    return response


# ── Include routers ───────────────────────────────────────────

app.include_router(auth_router)
app.include_router(account_router)
app.include_router(trading_router)
app.include_router(analytics_router)

# ── WebSocket ─────────────────────────────────────────────────

app.websocket("/api/live/ws")(live_ws)


# ── Startup ───────────────────────────────────────────────────

@app.on_event("startup")
async def on_startup():
    init_db()


# ── Health check ──────────────────────────────────────────────

@app.get("/", tags=["health"])
async def root():
    return {
        "service": "AURUM Finance — NEXUS API",
        "version": "1.0.0",
        "status": "operational",
    }


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok"}
