"""
Patient record endpoints.

RBAC:
* search/list/get      — admin, optometrist, front_desk
* create/update/archive— admin, front_desk (archive: admin only)
* self lookup          — patient (only the record linked to their account)

System Rule 2: every CRUD on patients writes an audit_logs row.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from app.api.deps import (ROLE_ADMIN, ROLE_FRONT_DESK, ROLE_OPTOMETRIST,
                          ROLE_PATIENT, require_roles)
from app.database.connection import execute, fetch_all, fetch_one, scalar
from app.services.audit_service import client_ip, log_action

router = APIRouter(prefix="/api/patients", tags=["patients"])

TABLE = "patients"


class PatientIn(BaseModel):
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    date_of_birth: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    sex: str | None = Field(default=None, pattern="^(male|female|other)$")
    contact_number: str | None = None
    email: str | None = None
    address: str | None = None


@router.get("")
def list_patients(
    q: str = Query(default="", max_length=100),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: dict = Depends(require_roles(ROLE_ADMIN, ROLE_OPTOMETRIST, ROLE_FRONT_DESK)),
) -> dict:
    """Paged, searchable directory (last name, first name, or HK ID)."""
    pattern = f"%{q}%"
    total = scalar(
        "SELECT COUNT(*) FROM patients WHERE is_archived = 0 AND "
        "(last_name LIKE :p OR first_name LIKE :p OR hk_patient_id LIKE :p)",
        {"p": pattern},
    )
    rows = fetch_all(
        "SELECT id, hk_patient_id, first_name, last_name, date_of_birth, sex, "
        "contact_number, email, created_at FROM patients "
        "WHERE is_archived = 0 AND (last_name LIKE :p OR first_name LIKE :p "
        "OR hk_patient_id LIKE :p) "
        "ORDER BY last_name, first_name LIMIT :limit OFFSET :offset",
        {"p": pattern, "limit": page_size, "offset": (page - 1) * page_size},
    )
    # System Rule 2: bulk READ of patient data is itself audited.
    log_action(user["id"], "READ", TABLE, None, None,
               {"bulk_search": True, "query": q, "results": len(rows)})
    return {"total": total, "page": page, "page_size": page_size, "items": rows}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_patient(
    body: PatientIn,
    request: Request,
    user: dict = Depends(require_roles(ROLE_ADMIN, ROLE_FRONT_DESK)),
) -> dict:
    """Register a walk-in clinic patient; HK ID auto-generated HK-00001..."""
    if scalar("SELECT COUNT(*) FROM patients WHERE email = :e AND email IS NOT NULL "
              "AND :e <> ''", {"e": body.email or ""}):
        raise HTTPException(status.HTTP_409_CONFLICT, "A patient with that email already exists.")

    next_seq = int(scalar(
        "SELECT COALESCE(MAX(CAST(SUBSTRING(hk_patient_id, 4) AS UNSIGNED)), 0) + 1 "
        "FROM patients"
    ))
    hk_id = f"HK-{next_seq:05d}"
    patient_id = execute(
        "INSERT INTO patients (hk_patient_id, first_name, last_name, date_of_birth, "
        "sex, contact_number, email, address) VALUES (:hk, :f, :l, :dob, :sex, "
        ":contact, :email, :addr)",
        {"hk": hk_id, "f": body.first_name, "l": body.last_name,
         "dob": body.date_of_birth, "sex": body.sex, "contact": body.contact_number,
         "email": body.email or None, "addr": body.address},
    )
    log_action(user["id"], "CREATE", TABLE, patient_id, client_ip(request),
               {"hk_patient_id": hk_id})
    return {"id": int(patient_id), "hk_patient_id": hk_id,
            "message": f"Patient registered as {hk_id}."}


@router.get("/me")
def my_record(user: dict = Depends(require_roles(ROLE_PATIENT))) -> dict:
    """Online patients may read only their own clinic record."""
    row = fetch_one(
        "SELECT id, hk_patient_id, first_name, last_name, date_of_birth, sex, "
        "contact_number, email, address FROM patients WHERE user_id = :uid",
        {"uid": user["id"]},
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "No clinic record is linked to your account yet.")
    log_action(user["id"], "READ", TABLE, row["id"], None)
    return row


@router.get("/{patient_id}")
def get_patient(
    patient_id: int,
    user: dict = Depends(require_roles(ROLE_ADMIN, ROLE_OPTOMETRIST,
                                       ROLE_FRONT_DESK, ROLE_PATIENT)),
) -> dict:
    row = fetch_one(
        "SELECT * FROM patients WHERE id = :id AND is_archived = 0",
        {"id": patient_id},
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patient not found.")
    if user["role"] == ROLE_PATIENT and row["user_id"] != user["id"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You may only view your own record.")
    log_action(user["id"], "READ", TABLE, patient_id, None)
    return row


@router.put("/{patient_id}")
def update_patient(
    patient_id: int,
    body: PatientIn,
    request: Request,
    user: dict = Depends(require_roles(ROLE_ADMIN, ROLE_FRONT_DESK)),
) -> dict:
    existing = fetch_one("SELECT id FROM patients WHERE id = :id", {"id": patient_id})
    if existing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patient not found.")

    execute(
        "UPDATE patients SET first_name=:f, last_name=:l, date_of_birth=:dob, "
        "sex=:sex, contact_number=:contact, email=:email, address=:addr WHERE id=:id",
        {"f": body.first_name, "l": body.last_name, "dob": body.date_of_birth,
         "sex": body.sex, "contact": body.contact_number, "email": body.email,
         "addr": body.address, "id": patient_id})
    log_action(user["id"], "UPDATE", TABLE, patient_id, client_ip(request),
               body.model_dump())
    return {"message": "Patient updated."}


@router.delete("/{patient_id}")
def archive_patient(
    patient_id: int,
    request: Request,
    user: dict = Depends(require_roles(ROLE_ADMIN)),
) -> dict:
    """Soft-delete: patient history (prescriptions) must survive for care."""
    row = fetch_one("SELECT id FROM patients WHERE id = :id", {"id": patient_id})
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patient not found.")
    execute("UPDATE patients SET is_archived = 1 WHERE id = :id", {"id": patient_id})
    log_action(user["id"], "DELETE", TABLE, patient_id, client_ip(request),
               {"soft_archived": True})
    return {"message": "Patient archived (history preserved)."}


@router.get("/{patient_id}/prescriptions")
def patient_prescription_history(
    patient_id: int,
    user: dict = Depends(require_roles(ROLE_ADMIN, ROLE_OPTOMETRIST,
                                       ROLE_FRONT_DESK, ROLE_PATIENT)),
) -> list[dict]:
    """Full optical history for one patient (newest first)."""
    owner = fetch_one("SELECT id, user_id FROM patients WHERE id = :id", {"id": patient_id})
    if owner is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patient not found.")
    if user["role"] == ROLE_PATIENT and owner["user_id"] != user["id"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your record.")

    rows = fetch_all(
        "SELECT p.id, p.exam_date, p.od_sphere, p.od_cylinder, p.od_axis, p.od_add, "
        "p.os_sphere, p.os_cylinder, p.os_axis, p.os_add, p.pupillary_distance, "
        "p.lens_type, p.notes, u.full_name AS optometrist "
        "FROM prescriptions p JOIN users u ON u.id = p.optometrist_id "
        "WHERE p.patient_id = :pid AND p.is_archived = 0 ORDER BY p.exam_date DESC",
        {"pid": patient_id},
    )
    log_action(user["id"], "READ", TABLE, patient_id, None,
               {"prescription_history": len(rows)})
    return rows
