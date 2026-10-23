"""
Dashboard statistics — feed for the admin / front-desk / optometrist home.
"""

from fastapi import APIRouter, Depends

from app.api.deps import ROLE_ADMIN, ROLE_FRONT_DESK, ROLE_OPTOMETRIST, require_roles
from app.database.connection import fetch_one

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("/clinic")
def clinic_stats(
    user: dict = Depends(require_roles(ROLE_ADMIN, ROLE_FRONT_DESK, ROLE_OPTOMETRIST)),
) -> dict:
    """Snapshot counters for the staff dashboard."""
    return fetch_one(
        "SELECT "
        "(SELECT COUNT(*) FROM patients WHERE is_archived = 0) AS total_patients, "
        "(SELECT COUNT(*) FROM prescriptions WHERE is_archived = 0 ) AS total_prescriptions, "
        "(SELECT COUNT(*) FROM appointments WHERE appointment_date = CURDATE() "
        " AND status IN ('pending','confirmed')) AS today_appointments, "
        "(SELECT COUNT(*) FROM appointments WHERE appointment_date > CURDATE() "
        " AND status = 'confirmed') AS upcoming_followups, "
        "(SELECT COUNT(*) FROM audit_logs a WHERE DATE(a.timestamp) = CURDATE()) AS audits_today",
        {},
    )
