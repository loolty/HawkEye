"""
JWT helpers for stateless session tokens (PyJWT, HS256).

Token lifetimes and secret come from app.core.config.settings.
"""

import datetime as dt

import jwt

from app.core.config import settings

TOKEN_TTL_HOURS = 8  # clinic staff typically shift-length sessions


def create_token(user_id: int, role: str, full_name: str) -> str:
    """Return a signed JWT identifying the logged-in user."""
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "name": full_name,
        "iat": now,
        "exp": now + dt.timedelta(hours=TOKEN_TTL_HOURS),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def decode_token(token: str) -> dict:
    """
    Decode and validate a token.

    Raises jwt.PyJWTError subclasses on malformed/expired tokens.
    Returns the claims dict on success.
    """
    return jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
