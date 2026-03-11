"""Authentication — password hashing and JWT tokens.

Pure functions only. No DB queries, no Pydantic schemas.
DB operations live in routes. Schemas live in schemas.py.
"""
import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

JWT_ALGORITHM = "HS256"
JWT_EXPIRY_DAYS = 30


def _get_secret() -> str:
    secret = os.environ.get("JWT_SECRET", "")
    if not secret:
        return "dev-secret-do-not-use-in-production"
    return secret


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_token(user_id: int) -> str:
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRY_DAYS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, _get_secret(), algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> int | None:
    """Decode a JWT token. Returns user_id or None if invalid."""
    try:
        payload = jwt.decode(token, _get_secret(), algorithms=[JWT_ALGORITHM])
        sub = payload.get("sub")
        return int(sub) if sub is not None else None
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, ValueError):
        return None
