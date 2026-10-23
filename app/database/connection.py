"""
Database connection layer (SQLAlchemy Core on top of PyMySQL).

Every module in Hawkeyes talks to MySQL through this file — no raw
connection strings anywhere else. All queries use bound parameters
(text(":param")) so SQL injection is structurally impossible.
"""

import logging
from contextlib import contextmanager
from typing import Any, Iterable

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from app.core.config import settings

logger = logging.getLogger("hawkeyes.database")

engine = create_engine(
    settings.sqlalchemy_url,
    pool_pre_ping=True,      # drop dead connections transparently
    pool_recycle=3600,       # recycle after 1h (avoids MySQL wait_timeout drops)
    pool_size=5,
    max_overflow=10,
    echo=settings.DEBUG and settings.APP_ENV == "development",
    future=True,
)


def get_connection() -> Connection:
    """Acquire a pooled connection: `with get_connection() as conn: ...`."""
    return engine.connect()


@contextmanager
def transaction() -> Iterable[Connection]:
    """
    Run a block inside a single transaction.

    Commits on success, rolls back on any exception:

        with transaction() as conn:
            conn.execute(...)

    """
    with get_connection() as conn:
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            logger.exception("Transaction rolled back.")
            raise


def fetch_all(query: str, params: dict[str, Any] | None = None) -> list[dict]:
    """Run a SELECT and return rows as plain dicts."""
    with get_connection() as conn:
        result = conn.execute(text(query), params or {})
        return [dict(row._mapping) for row in result]


def fetch_one(query: str, params: dict[str, Any] | None = None) -> dict | None:
    """Run a SELECT and return the first row as a dict, or None."""
    with get_connection() as conn:
        result = conn.execute(text(query), params or {})
        row = result.first()
        return dict(row._mapping) if row is not None else None


def scalar(query: str, params: dict[str, Any] | None = None) -> Any:
    """Run a query and return a single scalar value (e.g. COUNT(*))."""
    with get_connection() as conn:
        return conn.execute(text(query), params or {}).scalar()


def execute(query: str, params: dict[str, Any] | None = None) -> int:
    """
    Run a single INSERT/UPDATE/DELETE in its own transaction.

    Returns the auto-increment / lastrowid when available, else affected rows.
    """
    with transaction() as conn:
        result = conn.execute(text(query), params or {})
        try:
            return result.lastrowid or result.rowcount
        except Exception:
            return result.rowcount


def execute_many(
    statements: Iterable[tuple[str, dict[str, Any] | None]],
) -> None:
    """
    Run several statements atomically in one transaction.

    `statements` is an iterable of (query, params) tuples.
    """
    with transaction() as conn:
        for query, params in statements:
            conn.execute(text(query), params or {})
