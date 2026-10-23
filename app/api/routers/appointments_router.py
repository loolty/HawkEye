"""
Appointment booking + follow-up endpoints for Hawkeyes.

RBAC:
* book                 — patient (own linked record) or front_desk/admin (any record)
* list / today         — staff see all; patients see only their own
* update status        — front_desk/admin (confirm, cancel, no-show);
                         optometrist (mark completed)
* follow-ups           — staff: upcoming bookings (consumed by APScheduler later)
"""

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from app.api.deps import (ROLE_ADMIN, ROLE_FRONT_DESK, ROLE_OPTOMETRIST,
                          ROLE_PATIENT, require_roles)
from app.database.connection import execute, fetch_all, fetch_one, scalar
from app.services.audit_service import client_ip, log_action

router = APIRouter(prefix="/api/appointments", tags=["appointments"])

TABLE = "appointments"
VALID_STATUS = {"pending", "confirmed", "completed", "cancelled", "no_show"}

APPT_SELECT = (
    "SELECT a.id, a.patient_id, CONCAT(pt.first_name, ' ', pt.last_name) AS patient_name, "
    "pt.hk_patient_id, a.optometrist_id, u.full_name AS optometrist_name, "
    "a.appointment_date, TIME_FORMAT(a.start_time, '%H:%i') AS start_time, a.purpose, a.status, "
    "a.source, a.reminded_at, a.notes "
    "FROM appointments a "
    "JOIN patients pt ON pt.id = a.patient_id "
    "LEFT JOIN users u ON u.id = a.optometrist_id "
)


class AppointmentIn(BaseModel):
    patient_id: int | None = None          # required for staff booking
    appointment_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    start_time: str = Field(pattern=r"^\d{2}:\d{2}(:\d{2})?$")
    purpose: str = Field(min_length=3, max_length=255)
    optometrist_id: int | None = None      # optional assignment for staff
    notes: str | None = None


class StatusIn(BaseModel):
    status: str = Field(pattern="^(pending|confirmed|completed|cancelled|no_show)$")
    optometrist_id: int | None = None      # assign/confirm at the desk


class OptometristIn(BaseModel):
    optometrist_id: int | None = None      # explicit null = leave unassigned


def _time_bounds(appt_date: str) -> tuple[str, str]:
    """Reject dates in the past and keep bookings within 180 days."""
    day = dt.date.fromisoformat(appt_date)
    today = dt.date.today()
    if day < today:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Cannot book an appointment in the past.")
    if (day - today).days > 180:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Bookings open only 180 days ahead.")


@router.post("", status_code=status.HTTP_201_CREATED)
def book_appointment(
    body: AppointmentIn,
    request: Request,
    user: dict = Depends(require_roles(ROLE_PATIENT, ROLE_FRONT_DESK, ROLE_ADMIN)),
) -> dict:
    _time_bounds(body.appointment_date)

    if user["role"] == ROLE_PATIENT:
        # Online patients book only against their own linked clinic record.
        record = fetch_one("SELECT id FROM patients WHERE user_id = :uid AND is_archived = 0",
                           {"uid": user["id"]})
        if record is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Your account is not linked to a clinic record yet.")
        patient_id = record["id"]
        optometrist_id = None                    # desk assigns the optometrist later
        appt_status, source = "pending", "online"
    else:
        if body.patient_id is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "patient_id is required when booking for a patient.")
        patient_id = body.patient_id
        optometrist_id = body.optometrist_id
        appt_status, source = "confirmed", "walk_in"

    # no double-booking of the same patient at the same time, even unassigned
    patient_clash = scalar(
        "SELECT COUNT(*) FROM appointments WHERE patient_id = :pid AND "
        "appointment_date = :d AND start_time = :t AND status IN "
        "('pending','confirmed')",
        {"pid": patient_id, "d": body.appointment_date, "t": body.start_time},
    )
    if patient_clash:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "This patient already has an appointment at that time slot.")

    if optometrist_id is not None:
        if scalar("SELECT COUNT(*) FROM users WHERE id = :id AND role = 'optometrist'",
                  {"id": optometrist_id}) == 0:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "optometrist_id must be an optometrist account.")
        clash = scalar(
            "SELECT COUNT(*) FROM appointments WHERE optometrist_id = :oid AND "
            "appointment_date = :d AND start_time = :t AND status NOT IN "
            "('cancelled', 'no_show')",
            {"oid": optometrist_id, "d": body.appointment_date, "t": body.start_time},
        )
        if clash:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "That optometrist already has a booking at that time slot.")

    appt_id = execute(
        "INSERT INTO appointments (patient_id, optometrist_id, appointment_date, "
        "start_time, purpose, status, source, booked_by, notes) "
        "VALUES (:pid, :oid, :d, :t, :purpose, :st, :src, :by, :notes)",
        {"pid": patient_id, "oid": optometrist_id, "d": body.appointment_date,
         "t": body.start_time, "purpose": body.purpose, "st": appt_status,
         "src": source, "by": user["id"], "notes": body.notes},
    )
    log_action(user["id"], "CREATE", TABLE, appt_id, client_ip(request),
               {"patient_id": patient_id, "date": body.appointment_date})
    return {"id": appt_id, "status": appt_status,
            "message": "Appointment booked."}


@router.get("")
def list_appointments(
    date: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    upcoming_only: bool = True,
    user: dict = Depends(require_roles(ROLE_PATIENT, ROLE_FRONT_DESK,
                                       ROLE_ADMIN, ROLE_OPTOMETRIST)),
) -> list[dict]:
    params: dict = {}
    tail = ""
    if user["role"] == ROLE_PATIENT:
        tail += "WHERE pt.user_id = :uid "
        params["uid"] = user["id"]
    if date:
        tail += ("WHERE " if "WHERE" not in tail else "AND ") + "a.appointment_date = :d "
        params["d"] = date
    elif upcoming_only:
        tail += ("WHERE " if "WHERE" not in tail else "AND ") + \
            "a.appointment_date >= CURDATE() "
    tail += "ORDER BY a.appointment_date, a.start_time"
    return fetch_all(APPT_SELECT + tail, params)


@router.get("/optometrists")
def list_optometrists(
    user: dict = Depends(require_roles(ROLE_FRONT_DESK, ROLE_ADMIN, ROLE_OPTOMETRIST)),
) -> list[dict]:
    """Active optometrists for the booking and assignment dropdowns."""
    return fetch_all(
        "SELECT id, full_name FROM users WHERE role = 'optometrist' "
        "AND is_active = 1 ORDER BY full_name",
    )


@router.put("/{appt_id}/optometrist")
def assign_optometrist(
    appt_id: int,
    body: OptometristIn,
    request: Request,
    user: dict = Depends(require_roles(ROLE_FRONT_DESK, ROLE_ADMIN)),
) -> dict:
    """Assign (or clear) the optometrist on a pending/confirmed appointment."""
    appt = fetch_one(
        "SELECT id, status, optometrist_id, "
        "DATE_FORMAT(appointment_date, '%Y-%m-%d') AS appointment_date, "
        "TIME_FORMAT(start_time, '%H:%i:%s') AS start_time "
        "FROM appointments WHERE id = :id",
        {"id": appt_id},
    )
    if appt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Appointment not found.")
    if appt["status"] in {"completed", "cancelled", "no_show"}:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Cannot change the optometrist for a '{appt['status']}' appointment.")
    if body.optometrist_id == appt["optometrist_id"]:
        return {"message": "Optometrist unchanged."}

    if body.optometrist_id is not None:
        if scalar("SELECT COUNT(*) FROM users WHERE id = :id AND role = 'optometrist' "
                  "AND is_active = 1", {"id": body.optometrist_id}) == 0:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "optometrist_id must be an active optometrist account.")
        # Matches uq_appt_slot: the slot is unique regardless of its status.
        clash = scalar(
            "SELECT COUNT(*) FROM appointments WHERE optometrist_id = :oid AND "
            "appointment_date = :d AND start_time = :t AND id <> :id",
            {"oid": body.optometrist_id, "d": appt["appointment_date"],
             "t": appt["start_time"], "id": appt_id},
        )
        if clash:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "That optometrist already has a record at that time slot.")

    execute("UPDATE appointments SET optometrist_id = :oid WHERE id = :id",
            {"oid": body.optometrist_id, "id": appt_id})
    log_action(user["id"], "UPDATE", TABLE, appt_id, client_ip(request),
               {"optometrist_id": {"from": appt["optometrist_id"],
                                   "to": body.optometrist_id}})
    return {"message": "Optometrist assigned." if body.optometrist_id
                       else "Optometrist removed."}


@router.put("/{appt_id}/status")
def update_status(
    appt_id: int,
    body: StatusIn,
    request: Request,
    user: dict = Depends(require_roles(ROLE_FRONT_DESK, ROLE_ADMIN, ROLE_OPTOMETRIST)),
) -> dict:
    appt = fetch_one("SELECT id, status, patient_id, optometrist_id, appointment_date "
                     "FROM appointments WHERE id = :id", {"id": appt_id})
    if appt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Appointment not found.")
    if body.status == appt["status"]:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Appointment is already '{body.status}'.")

    # Optometrists may only complete their own consultations.
    if user["role"] == ROLE_OPTOMETRIST:
        if body.status not in {"completed", "no_show"}:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                "Optometrists may only mark completed / no_show.")
        if appt["optometrist_id"] != user["id"]:
            raise HTTPException(status.HTTP_403_FORBIDDEN,
                                "Only the assigned optometrist can do this.")

    sets = "status = :st"
    params: dict = {"st": body.status, "id": appt_id}
    if body.optometrist_id is not None:
        if scalar("SELECT COUNT(*) FROM users WHERE id = :id AND role = 'optometrist'",
                  {"id": body.optometrist_id}) == 0:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "optometrist_id must be an optometrist account.")
        sets = "status = :st, optometrist_id = :oid"
        params["oid"] = body.optometrist_id

    execute(f"UPDATE appointments SET {sets} WHERE id = :id", params)
    log_action(user["id"], "UPDATE", TABLE, appt_id, client_ip(request),
               {"from": appt["status"], "to": body.status})
    return {"message": f"Appointment marked {body.status}."}


@router.delete("/{appt_id}")
def cancel_appointment(
    appt_id: int,
    request: Request,
    user: dict = Depends(require_roles(ROLE_PATIENT, ROLE_FRONT_DESK, ROLE_ADMIN)),
) -> dict:
    """Patients cancel their own bookings; desk/admin cancel any."""
    appt = fetch_one(
        APPT_SELECT + " WHERE a.id = :id", {"id": appt_id},
    )
    if appt is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Appointment not found.")
    if user["role"] == ROLE_PATIENT:
        owner = scalar("SELECT user_id FROM patients WHERE id = :pid",
                       {"pid": appt["patient_id"]})
        if owner != user["id"]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your appointment.")
    if appt["status"] in {"completed", "cancelled"}:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Cannot cancel a '{appt['status']}' appointment.")

    execute("UPDATE appointments SET status = 'cancelled' WHERE id = :id", {"id": appt_id})
    log_action(user["id"], "UPDATE", TABLE, appt_id, client_ip(request),
               {"from": appt["status"], "to": "cancelled"})
    return {"message": "Appointment cancelled."}


@router.get("/follow-ups")
def follow_ups(
    days: int = Query(default=2, ge=1, le=30),
    user: dict = Depends(require_roles(ROLE_FRONT_DESK, ROLE_ADMIN, ROLE_OPTOMETRIST)),
) -> list[dict]:
    """Tab for staff: bookings in the next N days (scheduler reminder pool)."""
    return fetch_all(
        "SELECT DATEDIFF(ap.appointment_date, CURDATE()) AS days_away, ap.* FROM ("
        + APPT_SELECT + " WHERE a.appointment_date > CURDATE() AND "
        "a.appointment_date <= DATE_ADD(CURDATE(), INTERVAL :d DAY) AND "
        "a.status IN ('pending','confirmed')) ap "
        "ORDER BY ap.appointment_date, ap.start_time",
        {"d": days},
    )
