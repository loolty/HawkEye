"""
Shared FastAPI dependencies: authenticated user resolution + RBAC guards.
"""

import jwt as pyjwt
from fastapi import Depends, HTTPException, Request, status

from app.core.tokens import decode_token
from app.database.connection import fetch_one

ROLE_ADMIN = "admin"
ROLE_OPTOMETRIST = "optometrist"
ROLE_FRONT_DESK = "front_desk"
ROLE_PATIENT = "patient"

ALL_ROLES = (ROLE_ADMIN, ROLE_OPTOMETRIST, ROLE_FRONT_DESK, ROLE_PATIENT)
STAFF_ROLES = (ROLE_ADMIN, ROLE_OPTOMETRIST, ROLE_FRONT_DESK)

USER_FIELDS = "id, full_name, email, role, is_active"


def _unauthorized(detail: str = "Missing or invalid credentials.") -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail,
                         headers={"WWW-Authenticate": "Bearer"})


def get_current_user(request: Request) -> dict:
    """
    Resolve the authenticated user from the 'Authorization: Bearer <jwt>'
    header. Returns a plain dict of the DB row (sans password hash).
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise _unauthorized()
    try:
        claims = decode_token(auth.removeprefix("Bearer ").strip())
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired, please log in again.",
                            headers={"WWW-Authenticate": "Bearer"})
    except pyjwt.PyJWTError:
        raise _unauthorized()

    user = fetch_one(
        f"SELECT {USER_FIELDS} FROM users WHERE id = :id AND is_active = 1",
        {"id": int(claims["sub"])},
    )
    if user is None:
        raise _unauthorized("Account no longer exists or is deactivated.")
    return user


def require_roles(*allowed: str):
    """RBAC guard factory: `Depends(require_roles(ADMIN, FRONT_DESK))`."""

    async def _guard(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] not in allowed:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Requires one of: {', '.join(allowed)}. You are '{user['role']}'.",
            )
        return user

    return _guard
