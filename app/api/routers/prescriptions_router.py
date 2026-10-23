"""
Optical prescription endpoints.

RBAC:
* create/update        — optometrist, admin
* archive (soft delete)— admin only
* read                 — staff, or a patient for their own records

System Rules: OD/OS optical precision are enforced by pydantic here and by
SQL CHECK constraints in the schema; every write/read is audited.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, model_validator

from app.api.deps import ROLE_ADMIN, ROLE_OPTOMETRIST, ROLE_PATIENT, require_roles
from app.database.connection import execute, fetch_all, fetch_one
from app.services.audit_service import client_ip, log_action

router = APIRouter(prefix="/api/prescriptions", tags=["prescriptions"])

TABLE = "prescriptions"

RX_SUMMARY_SQL = (
    "SELECT r.id, r.patient_id, CONCAT(pt.first_name, ' ', pt.last_name) AS patient_name, "
    "pt.hk_patient_id, r.exam_date, r.od_sphere, r.od_cylinder, r.od_axis, r.od_add, "
    "r.os_sphere, r.os_cylinder, r.os_axis, r.os_add, r.pupillary_distance, "
    "r.lens_type, r.notes, u.full_name AS optometrist "
    "FROM prescriptions r "
    "JOIN patients pt ON pt.id = r.patient_id "
    "JOIN users u ON u.id = r.optometrist_id "
)


class EyeParams(BaseModel):
    sphere: float = Field(ge=-30.0, le=30.0)
    cylinder: float = Field(default=0.0, ge=-10.0, le=10.0)
    axis: int | None = Field(default=None, ge=0, le=180)
    add: float | None = Field(default=None, ge=0.0, le=4.0)

    @model_validator(mode="after")
    def _axis_requires_cyl(self) -> "EyeParams":
        if self.axis is not None and abs(self.cylinder) < 0.001:
            raise ValueError("axis is only meaningful when a cylinder is prescribed.")
        return self


class PrescriptionIn(BaseModel):
    patient_id: int
    od: EyeParams
    os: EyeParams
    pupillary_distance: float | None = Field(default=None, ge=40.0, le=85.0)
    lens_type: str | None = Field(
        default=None, pattern="^(single_vision|bifocal|progressive|reading)$")
    notes: str | None = Field(default=None, max_length=2000)


def _write_audit(user: dict, request: Request, action: str,
                 record_id: int | None, extra: dict | None = None) -> None:
    log_action(user["id"], action, TABLE, record_id,
               client_ip(request), extra)


@router.post("", status_code=status.HTTP_201_CREATED)
def create_prescription(
    body: PrescriptionIn,
    request: Request,
    user: dict = Depends(require_roles(ROLE_OPTOMETRIST, ROLE_ADMIN)),
) -> dict:
    patient = fetch_one(
        "SELECT id, user_id FROM patients WHERE id = :id AND is_archived = 0",
        {"id": body.patient_id},
    )
    if patient is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Patient not found.")

    rx_id = execute(
        "INSERT INTO prescriptions (patient_id, optometrist_id, od_sphere, od_cylinder, "
        "od_axis, od_add, os_sphere, os_cylinder, os_axis, os_add, pupillary_distance, "
        "lens_type, notes, created_by, exam_date) "
        "VALUES (:pid, :oid, :ods, :odc, :oda, :odadd, :oss, :osc, :osa, :osadd, "
        ":pd, :lens, :notes, :created, NOW())",
        {
            "pid": body.patient_id, "oid": user["id"],
            "ods": body.od.sphere, "odc": body.od.cylinder,
            "oda": body.od.axis, "odadd": body.od.add,
            "oss": body.os.sphere, "osc": body.os.cylinder,
            "osa": body.os.axis, "osadd": body.os.add,
            "pd": body.pupillary_distance, "lens": body.lens_type,
            "notes": body.notes, "created": user["id"],
        },
    )
    _write_audit(user, request, "CREATE", rx_id,
                 {"patient_id": body.patient_id})
    return {"id": rx_id, "message": "Prescription recorded."}


@router.get("/recent")
def recent_prescriptions(
    limit: int = 20,
    user: dict = Depends(require_roles(ROLE_OPTOMETRIST, ROLE_ADMIN)),
) -> list[dict]:
    rows = fetch_all(RX_SUMMARY_SQL + "WHERE r.is_archived = 0 "
                     "ORDER BY r.exam_date DESC LIMIT :lim", {"lim": limit})
    log_action(user["id"], "READ", TABLE, None, None, {"recent": len(rows)})
    return rows


@router.get("/my")
def my_prescriptions(user: dict = Depends(require_roles(ROLE_PATIENT))) -> list[dict]:
    """Online patients see only prescriptions tied to their linked record."""
    rows = fetch_all(
        RX_SUMMARY_SQL + "WHERE r.is_archived = 0 AND pt.user_id = :uid "
        "ORDER BY r.exam_date DESC", {"uid": user["id"]},
    )
    log_action(user["id"], "READ", TABLE, None, None, {"self_history": len(rows)})
    return rows


@router.get("/{rx_id}")
def get_prescription(
    rx_id: int,
    user: dict = Depends(require_roles(ROLE_OPTOMETRIST, ROLE_ADMIN,
                                       ROLE_PATIENT)),
) -> dict:
    row = fetch_one(
        RX_SUMMARY_SQL + "WHERE r.id = :rid", {"rid": rx_id},
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Prescription not found.")
    if user["role"] == ROLE_PATIENT:
        owner = fetch_one("SELECT user_id FROM patients WHERE id = :pid ",
                          {"pid": row["patient_id"]})
        if owner is None or owner["user_id"] != user["id"]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your prescription.")
    log_action(user["id"], "READ", TABLE, rx_id, None)
    return row


@router.put("/{rx_id}")
def update_prescription(
    rx_id: int,
    body: PrescriptionIn,
    request: Request,
    user: dict = Depends(require_roles(ROLE_OPTOMETRIST, ROLE_ADMIN)),
) -> dict:
    existing = fetch_one("SELECT id, patient_id FROM prescriptions WHERE id = :id",
                         {"id": rx_id})
    if existing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Prescription not found.")
    if existing["patient_id"] != body.patient_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Cannot move a prescription between patients.")

    execute(
        "UPDATE prescriptions SET od_sphere=:ods, od_cylinder=:odc, od_axis=:oda, "
        "od_add=:odadd, os_sphere=:oss, os_cylinder=:osc, os_axis=:osa, os_add=:osadd, "
        "pupillary_distance=:pd, lens_type=:lens, notes=:notes WHERE id=:id",
        {
            "ods": body.od.sphere, "odc": body.od.cylinder,
            "oda": body.od.axis, "odadd": body.od.add,
            "oss": body.os.sphere, "osc": body.os.cylinder,
            "osa": body.os.axis, "osadd": body.os.add,
            "pd": body.pupillary_distance, "lens": body.lens_type,
            "notes": body.notes, "id": rx_id,
        },
    )
    _write_audit(user, request, "UPDATE", rx_id, {"patient_id": body.patient_id})
    return {"message": "Prescription updated."}


@router.delete("/{rx_id}")
def archive_prescription(
    rx_id: int,
    request: Request,
    user: dict = Depends(require_roles(ROLE_ADMIN)),
) -> dict:
    if fetch_one("SELECT id FROM prescriptions WHERE id = :id", {"id": rx_id}) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Prescription not found.")
    execute("UPDATE prescriptions SET is_archived = 1 WHERE id = :id", {"id": rx_id})
    _write_audit(user, request, "DELETE", rx_id, {"soft_archived": True})
    return {"message": "Prescription archived (audit trail kept)."}
