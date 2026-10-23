# Quick start
1. Copy `.env.example` to `.env` and fill in your MySQL connection.
2. Install dependencies: `pip install -r requirements.txt`
3. (Optional) Seed the database: `python scripts/init_db.py --seed`
4. Run the server: `python -m uvicorn app.main:app --reload --port 8000`

For Windows, `run.bat` does steps 2–4 and tries to clear port 8000 first.

# Demo credentials
These accounts are created by `python scripts/init_db.py --seed` when the `users` table is empty.

| Role | Email | Password |
|---|---|---|
| Admin | `admin@hawkeyes.local` | `Admin@123` |
| Front desk | `frontdesk@hawkeyes.local` | `Front@123` |
| Optometrist | `optometrist@hawkeyes.local` | `Optom@123` |
| Patient | `patient@hawkeyes.local` | `Patient@123` |

MySQL demo login (used by `.env.example`): `DB_USER=root`, `DB_PASSWORD=hawkeye`.

# Architecture
- **Backend:** Python / FastAPI serving JSON under `/api/*`.
- **Frontend:** Bootstrap 5 + vanilla JS, served as static files at `/`.
- **Auth:** JWT tokens issued at `/api/auth/*`, with role-based access (admin, front_desk, optometrist, patient).
- **Database:** MySQL. `app/database/schema.sql` is the schema; `scripts/init_db.py` bootstraps and seeds.
- **Scheduler:** `app/services/scheduler.py` sends follow-up reminder emails for appointments that are coming up.

# Roles
- Admin and front desk can manage appointments (see `tests/test_appointments_users_audit.py` and `tests/test_auth_rbac.py`).
- Optometrists view their own schedule.
- Patients see their own appointments, prescriptions, and patient records.

# Tests
`pytest` runs the test suite. Secrets and virtual environments are gitignored; create your own `.env` from `.env.example`.
