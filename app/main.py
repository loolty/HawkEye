"""
Hawkeyes FastAPI application factory.

* /api/*  — JSON REST endpoints (routers below)
* /*      — the Bootstrap 5 + vanilla JS frontend served as static files
"""

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routers import (appointments_router, audit_router, auth_router,
                             patients_router, prescriptions_router, stats_router,
                             users_router)
from app.core.config import settings
from app.services.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="Optical Prescription Management and Appointment Follow-Up System",
)

# CORS: the SPA is normally same-origin (served below). This middleware just
# allows frontends on other localhost ports during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000",
                   "http://localhost:5500", "http://127.0.0.1:5500"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

@app.middleware("http")
async def no_cache_frontend(request: Request, call_next):
    """Make browsers revalidate the static SPA so edits apply on a reload."""
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


# --- API routers ---------------------------------------------------------
app.include_router(auth_router.router)
app.include_router(patients_router.router)
app.include_router(prescriptions_router.router)
app.include_router(appointments_router.router)
app.include_router(audit_router.router)
app.include_router(stats_router.router)
app.include_router(users_router.router)


@app.on_event("startup")
def on_startup() -> None:
    """Start the background agenda: follow-up reminder flags."""
    start_scheduler()


@app.on_event("shutdown")
def on_shutdown() -> None:
    stop_scheduler()


@app.get("/api/health", tags=["meta"])
def health() -> dict:
    """Liveness probe + DB round-trip."""
    from app.database.connection import scalar
    try:
        scalar("SELECT 1")
        db = "ok"
    except Exception as exc:                      # pragma: no cover
        logging.getLogger("hawkeyes.health").error("DB check failed: %s", exc)
        db = "unreachable"
    return {"name": settings.APP_NAME, "status": "running", "database": db}


# --- Frontend ------------------------------------------------------------
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
