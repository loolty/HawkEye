"""
Authentication endpoints.

* POST /api/auth/login     — email + password → JWT (any role)
* POST /api/auth/register  — online patient signup; links the account to a
                             physical clinic record by (hk_patient_id, DOB).
                             System Rule 3: Identity Resolution.
* GET  /api/auth/me        — current session identity
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.core.security import hash_password, verify_password
from app.core.tokens import create_token
from app.database.connection import execute, fetch_one, scalar
from app.services.audit_service import client_ip, log_action

router = APIRouter(prefix="/api/auth", tags=["auth"])

LOGIN_FAIL_AUDIT = ("LOGIN", "users")


# Plain pattern instead of EmailStr: seeded demo emails use the reserved
# '.local' domain (hawkeyes.local), which RFC email validators reject.
EMAIL_PATTERN = r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"


class LoginIn(BaseModel):
    email: str = Field(pattern=EMAIL_PATTERN)
    password: str = Field(min_length=1, max_length=128)


class RegisterIn(BaseModel):
    full_name: str = Field(min_length=3, max_length=120)
    email: str = Field(pattern=EMAIL_PATTERN)
    password: str = Field(min_length=8, max_length=128)
    hk_patient_id: str = Field(min_length=3, max_length=15)
    date_of_birth: str  # 'YYYY-MM-DD', validated below


def _public_user(row: dict) -> dict:
    return {k: row[k] for k in ("id", "full_name", "email", "role")}


@router.post("/login")
def login(body: LoginIn, request: Request) -> dict:
    user = fetch_one(
        "SELECT id, full_name, email, password_hash, role, is_active "
        "FROM users WHERE email = :email",
        {"email": body.email},
    )
    if user is None or not verify_password(body.password, user["password_hash"]):
        log_action(
            user["id"] if user else None, "ACCESS_DENIED", "users",
            user["id"] if user else None, client_ip(request),
            {"reason": "invalid_credentials", "email": body.email},
        )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password.")
    if not user["is_active"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account deactivated. Contact the clinic.")

    token = create_token(user["id"], user["role"], user["full_name"])
    log_action(user["id"], "LOGIN", "users", user["id"], client_ip(request))
    return {"token": token, "user": _public_user(user)}


@router.post("/register")
def register(body: RegisterIn, request: Request) -> dict:
    # --- validate DOB format early (DB needs a clean DATE literal) ---
    try:
        from datetime import date

        date.fromisoformat(body.date_of_birth)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "date_of_birth must be YYYY-MM-DD.")

    # --- System Rule 3: resolve to an existing clinic record ---
    patient = fetch_one(
        "SELECT id, first_name, last_name, user_id FROM patients "
        "WHERE hk_patient_id = :hk AND date_of_birth = :dob",
        {"hk": body.hk_patient_id.strip().upper(), "dob": body.date_of_birth},
    )
    if patient is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "No clinic record matches that Hawkeyes ID and birth date. "
            "Please visit the front desk to be registered in person.",
        )
    if patient["user_id"] is not None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "This clinic record is already linked to an account.")

    if scalar("SELECT COUNT(*) FROM users WHERE email = :e", {"e": body.email}):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email is already registered.")

    new_user_id = execute(
        "INSERT INTO users (full_name, email, password_hash, role) "
        "VALUES (:n, :e, :p, 'patient')",
        {"n": body.full_name, "e": body.email,
         "p": hash_password(body.password)},
    )
    execute("UPDATE patients SET user_id = :uid, email = :email WHERE id = :pid",
            {"uid": new_user_id, "email": body.email, "pid": patient["id"]})

    ip = client_ip(request)
    log_action(new_user_id, "CREATE", "users", new_user_id, ip,
               {"via": "online_registration", "linked_patient_id": patient["id"]})
    log_action(new_user_id, "UPDATE", "patients", patient["id"], ip,
               {"linked_user_id": new_user_id})

    row = fetch_one("SELECT id, full_name, email, role FROM users WHERE id = :id",
                    {"id": new_user_id})
    return {"token": create_token(row["id"], row["role"], row["full_name"]),
            "user": row}


@router.get("/me")
def me(user: dict = Depends(get_current_user)) -> dict:
    return user
