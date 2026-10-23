"""
Audit trail access (admin only) — Data Privacy transparency endpoint.
"""

from fastapi import APIRouter, Depends, Query

from app.api.deps import ROLE_ADMIN, require_roles
from app.database.connection import fetch_all, scalar

router = APIRouter(prefix="/api/audit-logs", tags=["audit"])

VALID_ACTIONS = {"CREATE", "READ", "UPDATE", "DELETE", "ARCHIVE",
                 "LOGIN", "LOGOUT", "ACCESS_DENIED"}


@router.get("")
def list_audit_logs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    action: str | None = Query(default=None),
    table_name: str | None = Query(default=None, pattern="^(patients|prescriptions|users|appointments)$"),
    user_id: int | None = Query(default=None, ge=1),
    user: dict = Depends(require_roles(ROLE_ADMIN)),
) -> dict:
    """Paged audit trail, newest first, with optional filters."""
    clauses, params = [], {}
    if action:
        if action not in VALID_ACTIONS:
            from fastapi import HTTPException, status
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                f"action must be one of {sorted(VALID_ACTIONS)}")
        clauses.append("a.action = :action")
        params["action"] = action
    if table_name:
        clauses.append("a.table_name = :table_name")
        params["table_name"] = table_name
    if user_id:
        clauses.append("a.user_id = :user_id")
        params["user_id"] = user_id

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    total = scalar(
        f"SELECT COUNT(*) FROM audit_logs a {where}", params,
    )
    rows = fetch_all(
        "SELECT a.id, a.user_id, u.full_name AS user_name, u.role AS user_role, "
        "a.action, a.table_name, a.record_id, a.ip_address, a.details, a.timestamp "
        f"FROM audit_logs a LEFT JOIN users u ON u.id = a.user_id {where} "
        "ORDER BY a.timestamp DESC LIMIT :lim OFFSET :off",
        {**params, "lim": page_size, "off": (page - 1) * page_size},
    )
    return {"total": total, "page": page, "page_size": page_size, "items": rows}
