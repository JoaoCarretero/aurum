"""
AURUM Finance JWT authentication and password hashing.
"""
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, WebSocket, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from api.models import get_conn

_INSECURE_DEFAULT_SECRET = "aurum-dev-secret-change-in-production"
_ENV_SECRET = (os.environ.get("AURUM_JWT_SECRET") or "").strip()
SECRET_KEY = (
    _ENV_SECRET
    if _ENV_SECRET and _ENV_SECRET != _INSECURE_DEFAULT_SECRET
    else secrets.token_urlsafe(48)
)
SECRET_KEY_SOURCE = (
    "env"
    if _ENV_SECRET and _ENV_SECRET != _INSECURE_DEFAULT_SECRET
    else "ephemeral"
)
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
_bearer = HTTPBearer()


def hash_password(password: str) -> str:
    """Hash a plain-text password with bcrypt."""
    return _pwd_ctx.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plain-text password against a bcrypt hash."""
    return _pwd_ctx.verify(plain, hashed)


def create_token(data: dict, expires_hours: int = TOKEN_EXPIRE_HOURS) -> str:
    """Create a signed JWT token with an expiration claim."""
    payload = data.copy()
    payload["exp"] = datetime.now(timezone.utc) + timedelta(hours=expires_hours)
    payload["iat"] = datetime.now(timezone.utc)
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and verify a JWT token. Raises JWTError on failure."""
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])


def _unauthorized(detail: str = "Invalid or expired token") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _load_user_from_payload(payload: dict) -> dict:
    user_id = payload.get("sub")
    if user_id is None:
        raise _unauthorized("Token missing subject claim")

    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT id, email, role FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        raise _unauthorized("User not found")

    return dict(row)


def get_current_user_from_token(token: str) -> dict:
    """Resolve the current user from a bearer token string."""
    try:
        payload = decode_token(token)
    except JWTError as exc:
        raise _unauthorized() from exc
    return _load_user_from_payload(payload)


def get_current_admin_from_token(token: str) -> dict:
    """Resolve and require admin privileges from a bearer token string."""
    user = get_current_user_from_token(token)
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return user


def authenticate_websocket(
    websocket: WebSocket,
    *,
    require_admin_role: bool = False,
) -> dict:
    """Authenticate a websocket via bearer header or `?token=` query string."""
    auth_header = websocket.headers.get("authorization", "")
    token = ""
    if auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1].strip()
    if not token:
        token = (websocket.query_params.get("token") or "").strip()
    if not token:
        raise _unauthorized("Missing bearer token")
    if require_admin_role:
        return get_current_admin_from_token(token)
    return get_current_user_from_token(token)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    """
    FastAPI dependency: extract the current user from the Authorization header.
    Returns a dict with user fields (id, email, role).
    """
    return get_current_user_from_token(credentials.credentials)


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """FastAPI dependency: require the current user to have admin role."""
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return user
