"""
Background scheduler (APScheduler) — Appointment Follow-Up rule.

Job:
* Every hour scans appointments in the next APPOINTMENT_REMINDER_HOURS
  (default 24) whose status is 'confirmed' or 'pending' and not yet
  reminded (reminded_at IS NULL), then stamps reminded_at and logs an
  audit entry per reminder.

It starts with the FastAPI app (see app.main) in the same process so it
shares the DB pool — no extra services required for a capstone deploy.
"""

import datetime as dt
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import settings
from app.database.connection import fetch_all, scalar

logger = logging.getLogger("hawkeyes.scheduler")

REMINDER_INTERVAL_MINUTES = 60

_scheduler: BackgroundScheduler | None = None


def _next_hour_start() -> dt.datetime:
    """First reminder pass: the top of the next hour (naive local time)."""
    return (dt.datetime.now() + dt.timedelta(hours=1)).replace(
        minute=0, second=0, microsecond=0)



def _flag_due_appointments() -> None:
    """Stamp reminded_at on appointments inside the reminder window."""
    rows = fetch_all(
        "SELECT a.id, a.patient_id, a.appointment_date, a.start_time, a.status "
        "FROM appointments a "
        "WHERE a.reminded_at IS NULL "
        "AND a.status IN ('pending','confirmed') "
        "AND a.appointment_date >= CURDATE() "
        "AND a.appointment_date <= DATE_ADD(NOW(), INTERVAL :window_hours HOUR) "
        "ORDER BY a.appointment_date",
        {"window_hours": settings.APPOINTMENT_REMINDER_HOURS},
    )
    if not rows:
        return
    from app.database.connection import execute_many
    from app.services.audit_service import log_action  # local import avoids import cycle

    # One transaction: reminders are atomic — either all flagged or none.
    execute_many(
        [("UPDATE appointments SET reminded_at = NOW() WHERE id = :id",
          {"id": r["id"]}) for r in rows]
    )

    for r in rows:
        # user_id NULL = automated system action (kept out of staff stats)
        log_action(None, "UPDATE", "appointments", r["id"], None,
                   {"reminder_sent": True, "appointment_date": r["appointment_date"]})
    logger.info("Flagged %d upcoming appointment reminder(s).", len(rows))


def start_scheduler() -> BackgroundScheduler:
    """Create (once) and start the background scheduler."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return _scheduler

    _scheduler = BackgroundScheduler(timezone="Asia/Manila")
    _scheduler.add_job(
        _flag_due_appointments,
        IntervalTrigger(minutes=REMINDER_INTERVAL_MINUTES,
                        start_date=_next_hour_start()),
        id="appointment-reminders",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    logger.info("Scheduler started (reminders every %d min, window %dh).",
                REMINDER_INTERVAL_MINUTES, settings.APPOINTMENT_REMINDER_HOURS)
    return _scheduler


def stop_scheduler() -> None:
    """Shutdown cleanly (used by FastAPI shutdown event / tests)."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None


def pending_reminders_count() -> int:
    """Helper for dashboards/tests: how many appointments still need flags."""
    return scalar(
        "SELECT COUNT(*) FROM appointments WHERE reminded_at IS NULL AND "
        "status IN ('pending','confirmed') AND appointment_date >= CURDATE()",
    ) or 0
