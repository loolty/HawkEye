"""
User account management (admin only).

Power * admin can create any account (staff or patient), reset someone's
> password or change a role, and deactivate (soft-delete) accounts.
* every write is audited, matching the Data Privacy rules.
"""

import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, model_validator

from app.api.deps import ALL_ROLES, ROLE_ADMIN, require_roles
from app.core.security import hash_password
from app.database.connection import execute, fetch_all, fetch_one, scalar
from app.services.audit_service import client_ip, log_action

router = APIRouter(prefix="/api/users", tags=["users"])

TABLE = "users"
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


class UserIn(BaseModel):
    full_name: str = Field(min_length=3, max_length=120)
    email: str
    password: str = Field(min_length=8, max_length=128)
    role: str

    @model_validator(mode="after")
    def _email_format_and_role(self) -> "UserIn":
        if not EMAIL_RE.match(self.email):
            raise ValueError("email must be a valid address like name@clinic.com")
        if self.role not in ALL_ROLES:
            raise ValueError(f"role must be one of {list(ALL_ROLES)}")
        return self

    @property
    def clean_email(self) -> str:
        return self.email.strip().lower()


class UserPatch(BaseModel):
    # all optional; pick any combination of 1+
    role: str | None = None
    is_active: bool | None = None
    new_password: str | None = Field(default=None, min_length=8, max_length=128)

    @model_validator(mode="after")
    def _validate(self) -> "UserPatch":
        if self.role is None and self.is_active is None and self.new_password is None:
            raise ValueError("Nothing to update: set role, is_active and/or new_password.")
        if self.role is not None and self.role not in ALL_ROLES:
            raise ValueError(f"role must be one of {list(ALL_ROLES)}")
        return self


def _no_self_demotion(user: dict, patch: UserPatch) -> None:
    """An admin cannot deactivate or demote themselves and lock the clinic out."""
    if patch.role not in (None, "admin") or patch.is_active is False:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Admins cannot demote or deactivate their own account.")


@router.get("")
def list_users(
    q: str = Query(default="", max_length=100),
    role: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: dict = Depends(require_roles(ROLE_ADMIN)),
) -> dict:
    clauses, params = [], {}
    if q:
        clauses.append("(full_name LIKE :q OR email LIKE :q)")
        params["q"] = f"%{q}%"
    if role:
        if role not in ALL_ROLES:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                f"role must be one of {list(ALL_ROLES)}")
        clauses.append("role = :role")
        params["role"] = role

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    total = scalar(f"SELECT COUNT(*) FROM users {where}", params)
    rows = fetch_all(
        "SELECT u.id, u.full_name, u.email, u.role, u.is_active, u.created_at, "
        "(SELECT COUNT(*) FROM patients p WHERE p.user_id = u.id) AS linked_patient_id "
        f"FROM users u {where} ORDER BY u.role, u.full_name "
        "LIMIT :lim OFFSET :off",
        {**params, "lim": page_size, "off": (page - 1) * page_size},
    )
    # audited bulk READ of user directory
    log_action(user["id"], "READ", TABLE, None, None, {"bulk": True, "count": len(rows)})
    return {"total": total, "page": page, "page_size": page_size, "items": rows}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserIn,
    request: Request,
    admin: dict = Depends(require_roles(ROLE_ADMIN)),
) -> dict:
    if scalar("SELECT COUNT(*) FROM users WHERE email = :e",
              {"e": body.clean_email}):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email is already registered.")

    new_id = execute(
        "INSERT INTO users (full_name, email, password_hash, role) "
        "VALUES (:n, :e, :p, :r)",
        {"n": body.full_name, "e": body.clean_email,
         "p": hash_password(body.password), "r": body.role},
    )
    log_action(admin["id"], "CREATE", TABLE, new_id, client_ip(request),
               {"email": body.clean_email, "role": body.role})
    return {"id": new_id, "message": f"Account created for {body.full_name} ({body.role})."}


@router.patch("/{user_id}")
def patch_user(
    user_id: int,
    body: UserPatch,
    request: Request,
    admin: dict = Depends(require_roles(ROLE_ADMIN)),
) -> dict:
    target = fetch_one("SELECT id, full_name, role, is_active FROM users WHERE id = :id",
                       {"id": user_id})
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    if user_id == admin["id"]:
        _no_self_demotion(admin, body)

    sets, params = [], {"id": user_id}
    if body.role is not None:
        sets.append("role = :role"); params["role"] = body.role
    if body.is_active is not None:
        sets.append("is_active = :active"); params["active"] = 1 if body.is_active else 0
    if body.new_password is not None:
        sets.append("password_hash = :pw"); params["pw"] = hash_password(body.new_password)

    execute(f"UPDATE users SET {', '.join(sets)} WHERE id = :id", params)
    log_action(admin["id"], "UPDATE", TABLE, user_id, client_ip(request), body.model_dump())
    return {"message": f"Account {target['full_name']} updated."}


@router.delete("/{user_id}")
def deactivate_user(
    user_id: int,
    request: Request,
    admin: dict = Depends(require_roles(ROLE_ADMIN)),
) -> dict:
    """Soft-delete: keep the audit chain intact (audited rows reference users)."""
    target = fetch_one("SELECT id, full_name, role FROM users WHERE id = :id", {"id": user_id})
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    if user_id == admin["id"]:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "Admins cannot deactivate their own account.")
    execute("UPDATE users SET is_active = 0 WHERE id = :id", {"id": user_id})
    log_action(admin["id"], "DELETE", TABLE, user_id, client_ip(request),
               {"soft_deactivated": True, "role": target["role"]})
    return {"message": f"Account {target['full_name']} deactivated."}
