"""
Database bootstrap script.

Usage (run from backend/):
    python scripts/init_db.py          # create DB + tables
    python scripts/init_db.py --seed   # also seed default users + sample patients

Safe to re-run: all DDL is IF NOT EXISTS, seeds are skipped if data exists.
"""

import argparse
import re
import sys
from pathlib import Path

import mysql.connector
from sqlalchemy.exc import SQLAlchemyError

# Make "app" importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings, validate_settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "app" / "database" / "schema.sql"

# (full_name, email, password, role)
SEED_USERS = [
    ("System Administrator", "admin@hawkeyes.local", "Admin@123", "admin"),
    ("Dr. Maria Santos",     "optometrist@hawkeyes.local", "Optom@123", "optometrist"),
    ("Front Desk Staff",     "frontdesk@hawkeyes.local",   "Front@123", "front_desk"),
    ("Sample Patient",       "patient@hawkeyes.local",     "Patient@123", "patient"),
]

# (hk_patient_id, first, last, dob 'YYYY-MM-DD', sex, contact, email)
SEED_PATIENTS = [
    ("HK-00001", "Juan",  "Dela Cruz", "1990-05-14", "male",   "09171234567", "juan@example.com"),
    ("HK-00002", "Angelo", "Reyes",     "1985-11-02", "male",   "09182223344", "angelo@example.com"),
    ("HK-00003", "Bea",   "Santos",    "2001-03-27", "female", "09193334455", "bea@example.com"),
]


def parse_schema() -> list[str]:
    """Split schema.sql into individual statements (no triggers/procedures used)."""
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    sql = re.sub(r"--[^\n]*", "", sql)  # strip comments
    return [stmt.strip() for stmt in sql.split(";") if stmt.strip()]


def apply_schema() -> None:
    """Execute every DDL statement in schema.sql."""
    raw = mysql.connector.connect(
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
    )
    try:
        cur = raw.cursor()
        for stmt in parse_schema():
            cur.execute(stmt)
        raw.commit()
        cur.close()
        print(f"✔ Schema applied from {SCHEMA_PATH.name}")
    finally:
        raw.close()


def seed() -> None:
    """Insert default staff/patient accounts + sample patients (skips if present)."""
    from app.database.connection import execute, execute_many, scalar

    INSERT_USER_SQL = (
        "INSERT INTO users (full_name, email, password_hash, role) "
        "VALUES (:n, :e, :p, :r)"
    )
    if scalar("SELECT COUNT(*) FROM users") > 0:
        print("• Users already exist — seeding skipped.")
    else:
        for full_name, email, password, role in SEED_USERS:
            execute(INSERT_USER_SQL, {"n": full_name, "e": email,
                                      "p": hash_password(password), "r": role})
            print(f"✔ Seeded {role:<12} {email}  (password: {password})")

    if scalar("SELECT COUNT(*) FROM patients") > 0:
        print("• Patients already exist — seeding skipped.")
        return

    INSERT_PATIENT_SQL = (
        "INSERT INTO patients (hk_patient_id, first_name, last_name, "
        "date_of_birth, sex, contact_number, email) "
        "VALUES (:hk, :f, :l, :dob, :sex, :contact, :email)"
    )
    stmts = [
        (INSERT_PATIENT_SQL,
         {"hk": hk, "f": f, "l": l, "dob": dob, "sex": sex,
          "contact": contact, "email": email})
        for hk, f, l, dob, sex, contact, email in SEED_PATIENTS
    ]
    execute_many(stmts)
    print(f"✔ Seeded {len(SEED_PATIENTS)} sample patients (with hk_patient_id).")

    # Link the demo online patient to a clinic record so the patient portal
    # (self record, my prescriptions, my appointments) is usable out of the box.
    execute(
        "UPDATE patients SET user_id = "
        "(SELECT id FROM users WHERE email = 'patient@hawkeyes.local') "
        "WHERE hk_patient_id = 'HK-00003' AND user_id IS NULL",
        {},
    )
    print("✔ Linked patient@hawkeyes.local to clinic record HK-00003")


def main() -> None:
    # Windows consoles default to cp1252; our progress marks are Unicode.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Bootstrap the Hawkeyes database.")
    parser.add_argument("--seed", action="store_true",
                        help="Also insert default users and sample patients.")
    args = parser.parse_args()

    problems = validate_settings()
    if problems:
        for p in problems:
            print(f"⚠ Config warning: {p}")

    print(f"Connecting to MySQL at {settings.DB_HOST}:{settings.DB_PORT} ...")
    try:
        apply_schema()
        if args.seed:
            seed()
    except mysql.connector.Error as exc:
        print(f"\n[X] MySQL error at {settings.DB_HOST}:{settings.DB_PORT}.")
        print(f"    {exc}")
        print("    Check that MySQL is running and DB_HOST / DB_PORT / DB_USER / DB_PASSWORD in .env are correct.")
        sys.exit(1)
    except SQLAlchemyError as exc:
        # keep it to the driver's first line; the full traceback only adds noise
        print(f"\n[X] Database setup failed at {settings.DB_HOST}:{settings.DB_PORT}.")
        print(f"    {str(exc).splitlines()[0]}")
        print("    Check the database credentials and schema in .env.")
        sys.exit(1)
    print("✅ Database ready.")


if __name__ == "__main__":
    main()
