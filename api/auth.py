"""
AURUM Finance — JWT authentication & password hashing.
"""
import os
from datetime import datetime, timedelta, timezone

from passlib.context import CryptContext
from jose import jwt, JWTError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from api.models import get_conn

# ── Config ────────────────────────────────────────────────────

SECRET_KEY = os.environ.get("AURUM_JWT_SECRET", "aurum-dev-secret-change-in-production")
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
_bearer = HTTPBearer()


# ── Password ──────────────────────────────────────────────────

def hash_password(password: str) -> str:
    """Hash a plain-text password with bcrypt."""
    return _pwd_ctx.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plain-text password against a bcrypt hash."""
    return _pwd_ctx.verify(plain, hashed)


# ── JWT ───────────────────────────────────────────────────────

def create_token(data: dict, expires_hours: int = TOKEN_EXPIRE_HOURS) -> str:
    """Create a signed JWT token with an expiration claim."""
    payload = data.copy()
    payload["exp"] = datetime.now(timezone.utc) + timedelta(hours=expires_hours)
    payload["iat"] = datetime.now(timezone.utc)
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and verify a JWT token. Raises JWTError on failure."""
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])


# ── FastAPI dependency ────────────────────────────────────────

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    """
    FastAPI dependency: extract the current user from the Authorization header.
    Returns a dict with user fields (id, email, role).
    """
    token = credentials.credentials
    try:
        payload = decode_token(token)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject claim",
        )

    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT id, email, role FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    return dict(row)


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """FastAPI dependency: require the current user to have admin role."""
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return user
