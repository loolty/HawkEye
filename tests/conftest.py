"""
Pytest fixtures for the Hawkeyes API test suite.

Uses a dedicated test database (hawkeyes_test_db by default) so the real
clinic database is never touched. Every table is truncated between tests.

If MySQL credentials in .env are missing/wrong, every test skips with a
clear message instead of failing.
"""

import os
import re
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

# --- make `app` importable and force the TEST database BEFORE app imports ---
BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))
os.environ["DB_NAME"] = "hawkeyes_test_db"

import mysql.connector  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND_ROOT / ".env")
os.environ["DB_NAME"] = "hawkeyes_test_db"      # .env load must not override us

from app.core.security import hash_password  # noqa: E402
from app.database.connection import engine, execute, fetch_one, scalar  # noqa: E402

SKIP = "MySQL not reachable or DB credentials not configured in backend/.env"

SCHEMA_FILE = BACKEND_ROOT / "app" / "database" / "schema.sql"
TEST_DB = os.environ["DB_NAME"]


@pytest.fixture(scope="session")
def db():
    """Ensure the test database exists and its schema is applied."""
    try:
        conn = mysql.connector.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "3306")),
            user=os.getenv("DB_USER", "root"),
            password=os.getenv("DB_PASSWORD", ""),
        )
    except Exception as exc:                      # pragma: no cover - env depends
        pytest.skip(f"{SKIP} ({exc.__class__.__name__})")

    try:
        cur = conn.cursor()
        cur.execute(f"CREATE DATABASE IF NOT EXISTS `{TEST_DB}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        conn.commit()
        cur.close()

        # Re-run schema.sql with the database name rewritten to the test DB.
        sql = SCHEMA_FILE.read_text(encoding="utf-8")
        sql = re.sub(r"--[^\n]*", "", sql)
        sql = re.sub(r"\b(CREATE DATABASE[^\n]*?)(hawkeyes_db|hawkeyes_test_db)",
                     r"\1" + "`" + TEST_DB + "`", sql)
        sql = re.sub(r"\bUSE hawkeyes_db\b|\bUSE hawkeyes_test_db\b",
                     f"USE `{TEST_DB}`", sql)
        cur = conn.cursor()
        for stmt in (s.strip() for s in sql.split(";")):
            if stmt:
                cur.execute(stmt)
        conn.commit()
        cur.close()
    finally:
        conn.close()
    yield True


@pytest.fixture(autouse=True)
def clean_tables(db):
    """Truncate every table before each test for full isolation."""
    tables = ("audit_logs", "appointments", "prescriptions", "patients", "users")
    with engine.connect() as conn:
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        for t in tables:
            conn.execute(text(f"TRUNCATE TABLE {t}"))
        conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
        conn.commit()
    yield


@pytest.fixture
def client(db):
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as c:
        yield c


def make_user(email: str, password: str, role: str) -> int:
    """Insert a user directly (no HTTP) and return the id."""
    return execute(
        "INSERT INTO users (full_name, email, password_hash, role) "
        "VALUES (:n, :e, :p, :r)",
        {"n": f"Test {role.title()}", "e": email,
         "p": hash_password(password), "r": role},
    )


def auth_header(user_id: int) -> dict:
    """Create a JWT for an existing user id without an HTTP login call."""
    row = fetch_one("SELECT id, full_name, role FROM users WHERE id = :id", {"id": user_id})
    from app.core.tokens import create_token

    token = create_token(row["id"], row["role"], row["full_name"])
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin(client):
    uid = make_user("admin@test.local", "Admin@123", "admin")
    return uid, auth_header(uid)


@pytest.fixture
def front_desk(client):
    uid = make_user("desk@test.local", "Front@123", "front_desk")
    return uid, auth_header(uid)


@pytest.fixture
def optometrist(client):
    uid = make_user("optom@test.local", "Optom@123", "optometrist")
    return uid, auth_header(uid)
