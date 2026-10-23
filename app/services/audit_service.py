"""
Audit trail service — every sensitive CRUD call funnels through here.

System Rule 2: any create/read/update/delete on `patients` or
`prescriptions` must record user, action, table, record, IP and timestamp.
"""

import json
import logging
from typing import Any

from fastapi import Request

from app.database.connection import execute

logger = logging.getLogger("hawkeyes.audit")

INSERT_AUDIT_SQL = (
    "INSERT INTO audit_logs (user_id, action, table_name, record_id, ip_address, details) "
    "VALUES (:user_id, :action, :table_name, :record_id, :ip_address, :details)"
)


def client_ip(request: Request | None) -> str | None:
    """Best-effort client IP (respects X-Forwarded-For behind a proxy)."""
    if request is None:
        return None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def log_action(
    user_id: int | None,
    action: str,
    table_name: str,
    record_id: int | None,
    ip_address: str | None,
    details: dict[str, Any] | None = None,
) -> None:
    """
    Write one audit row. Never raises: the sensitive operation already
    succeeded, and an audit failure must not roll back patient care data.
    """
    try:
        details_json = json.dumps(details, default=str) if details else None
        execute(INSERT_AUDIT_SQL, {
            "user_id": user_id,
            "action": action,
            "table_name": table_name,
            "record_id": record_id,
            "ip_address": ip_address,
            "details": details_json,
        })
    except Exception:
        logger.exception("AUDIT WRITE FAILED (action=%s table=%s record=%s)",
                         action, table_name, record_id)
