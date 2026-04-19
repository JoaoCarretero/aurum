"""
AURUM Finance NEXUS API server.
FastAPI app with CORS, rate limiting, and all route groups.
"""
import os
import time
from collections import defaultdict

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from api.models import init_db
from api.routes import (
    account_router,
    analytics_router,
    auth_router,
    live_ws,
    trading_router,
)


def _env_flag(name: str, default: bool = False) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _allowed_origins() -> list[str]:
    # Browsers reject allow_origins=["*"] with allow_credentials=True,
    # so we never ship that combo. Configure via AURUM_ALLOWED_ORIGINS.
    default_origins = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:3000,http://127.0.0.1:3000"
    )
    return [
        origin.strip()
        for origin in os.environ.get("AURUM_ALLOWED_ORIGINS", default_origins).split(",")
        if origin.strip()
    ]


_rate_store: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT = 100
RATE_WINDOW = 60  # seconds


def create_app(*, expose_docs: bool | None = None) -> FastAPI:
    docs_enabled = _env_flag("AURUM_API_EXPOSE_DOCS", default=False) if expose_docs is None else expose_docs
    app = FastAPI(
        title="AURUM Finance API",
        version="1.0.0",
        description="NEXUS API Bridge and Account Management for AURUM Finance",
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next):
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
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
        return await call_next(request)

    app.include_router(auth_router)
    app.include_router(account_router)
    app.include_router(trading_router)
    app.include_router(analytics_router)
    app.websocket("/api/live/ws")(live_ws)

    @app.on_event("startup")
    async def on_startup():
        init_db()

    @app.get("/", tags=["health"])
    async def root():
        return {
            "service": "AURUM Finance NEXUS API",
            "version": "1.0.0",
            "status": "operational",
        }

    @app.get("/health", tags=["health"])
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
