"""Appointments (double-booking, status), user management, and the
APScheduler reminder job tests."""

import datetime as dt

from app.database.connection import fetch_one, scalar
from tests.conftest import auth_header, execute, make_user


def _book_as_desk(client, hdr, patient_id, day=None, time="10:00", purpose="Exam"):
    return client.post("/api/appointments", headers=dict(hdr), json={
        "patient_id": patient_id, "appointment_date": day or str(dt.date.today()),
        "start_time": time, "purpose": purpose, "optometrist_id": None,
    })


def test_double_booking_same_slot_409(client, front_desk, optometrist):
    _, desk = front_desk
    oid, ohdr = optometrist
    patient_id = client.post("/api/patients", headers=desk, json={
        "first_name": "Du", "last_name": "Bell", "date_of_birth": "1992-01-01"}).json()["id"]

    first = client.post("/api/appointments", headers=desk, json={
        "patient_id": patient_id, "appointment_date": str(dt.date.today()),
        "start_time": "09:00:00", "purpose": "First", "optometrist_id": oid})
    second = client.post("/api/appointments", headers=desk, json={
        "patient_id": patient_id, "appointment_date": str(dt.date.today()),
        "start_time": "09:00:00", "purpose": "Clash", "optometrist_id": oid})
    assert first.status_code == 201, first.text
    assert second.status_code == 409, "double-booking must be rejected"


def test_patient_books_own_and_cannot_see_others(client, db):
    # one linked patient record
    pid = execute(
        "INSERT INTO patients (hk_patient_id, first_name, last_name, date_of_birth, user_id) "
        "VALUES ('HK-00009', 'Own', 'ly', '1995-06-06', NULL)")
    uid = make_user("owner@test.local", "Good@123", "patient")
    execute("UPDATE patients SET user_id = :u WHERE id = :p", {"u": uid, "p": pid})

    # second patient (no link)
    make_user("other@test.local", "Good@123", "patient")

    hdr = auth_header(uid)
    res = client.post("/api/appointments", headers=hdr, json={
        "appointment_date": str(dt.date.today() + dt.timedelta(days=3)),
        "start_time": "14:00:00", "purpose": "Follow-up"})
    assert res.status_code == 201, res.text

    listing = client.get("/api/appointments", headers=hdr).json()
    assert all(a["patient_name"] == "Own ly" and a["patient_id"] == pid for a in listing)


def test_reminder_job_flags_tomorrow_appointments(client, front_desk, db):
    _, desk = front_desk
    patient_id = client.post("/api/patients", headers=desk, json={
        "first_name": "Re", "last_name": "Minder", "date_of_birth": "2000-03-03"}).json()["id"]
    tomorrow = dt.date.today() + dt.timedelta(days=1)
    appt = client.post("/api/appointments", headers=desk, json={
        "patient_id": patient_id, "appointment_date": str(tomorrow),
        "start_time": "10:00:00", "purpose": "Checkup"})
    assert appt.status_code == 201, appt.text

    from app.services.scheduler import _flag_due_appointments
    _flag_due_appointments()

    assert fetch_one("SELECT reminded_at FROM appointments WHERE id = :id",
                     {"id": appt.json()["id"]})["reminded_at"] is not None
    audit = scalar("SELECT COUNT(*) FROM audit_logs WHERE details LIKE '%reminder_sent%'")
    assert audit == 1

    # idempotent: running again must not duplicate or touch anything else
    _flag_due_appointments()
    assert scalar("SELECT COUNT(*) FROM audit_logs WHERE details LIKE '%reminder_sent%'") == 1


def test_admin_creates_and_deactivates_account(client, admin):
    _, hdr = admin
    created = client.post("/api/users", headers=hdr, json={
        "full_name": "New Optom", "email": "newoptom@test.com",
        "password": "Good@12345", "role": "optometrist"})
    assert created.status_code == 201, created.text
    new_id = created.json()["id"]

    me = client.get("/api/auth/me", headers=auth_header(new_id))
    assert me.status_code == 200

    deact = client.delete(f"/api/users/{new_id}", headers=hdr)
    assert deact.status_code == 200
    # deactivated accounts cannot log in
    blocked = client.post("/api/auth/login", json={
        "email": "newoptom@test.com", "password": "Good@12345"})
    assert blocked.status_code == 403


def test_admin_cannot_deactivate_self(client, admin):
    uid, hdr = admin
    res = client.delete(f"/api/users/{uid}", headers=hdr)
    assert res.status_code == 409


def test_non_admin_cannot_manage_users(client, front_desk):
    _, hdr = front_desk
    assert client.get("/api/users", headers=hdr).status_code == 403


def test_optometrist_assignment_rbac_and_conflicts(client, front_desk, optometrist, admin):
    desk_id, desk = front_desk
    oid, optom_hdr = optometrist
    _, admin_hdr = admin

    # staff can list the assignment directory; patients and anonymous cannot
    assert client.get("/api/appointments/optometrists", headers=desk).status_code == 200
    assert client.get("/api/appointments/optometrists", headers=optom_hdr).status_code == 200
    assert client.get("/api/appointments/optometrists", headers=admin_hdr).status_code == 200

    patient_uid = make_user("assign-patient@test.local", "Good@123", "patient")
    patient_hdr = auth_header(patient_uid)
    assert client.get("/api/appointments/optometrists", headers=patient_hdr).status_code == 403
    assert client.get("/api/appointments/optometrists").status_code == 401

    p1 = client.post("/api/patients", headers=desk, json={
        "first_name": "Assign", "last_name": "One",
        "date_of_birth": "1990-01-01"}).json()["id"]
    p2 = client.post("/api/patients", headers=desk, json={
        "first_name": "Assign", "last_name": "Two",
        "date_of_birth": "1991-02-02"}).json()["id"]

    day = str(dt.date.today())
    a1 = _book_as_desk(client, desk, p1, day=day, time="10:00").json()["id"]
    a2 = _book_as_desk(client, desk, p2, day=day, time="10:00").json()["id"]

    def listed(appt_id):
        rows = client.get(f"/api/appointments?date={day}", headers=desk).json()
        return next(r for r in rows if r["id"] == appt_id)

    # assign, clear, re-assign
    assert client.put(f"/api/appointments/{a1}/optometrist", headers=desk,
                      json={"optometrist_id": oid}).status_code == 200
    row = listed(a1)
    assert row["optometrist_id"] == oid
    assert row["optometrist_name"] == "Test Optometrist"

    assert client.put(f"/api/appointments/{a1}/optometrist", headers=desk,
                      json={"optometrist_id": None}).status_code == 200
    assert listed(a1)["optometrist_id"] is None

    assert client.put(f"/api/appointments/{a1}/optometrist", headers=desk,
                      json={"optometrist_id": oid}).status_code == 200

    # the same doctor cannot take two records in the same slot
    clash = client.put(f"/api/appointments/{a2}/optometrist", headers=desk,
                       json={"optometrist_id": oid})
    assert clash.status_code == 409, clash.text

    # only an active optometrist account can be assigned, and only by desk/admin
    assert client.put(f"/api/appointments/{a2}/optometrist", headers=desk,
                      json={"optometrist_id": desk_id}).status_code == 422
    assert client.put(f"/api/appointments/{a2}/optometrist", headers=optom_hdr,
                      json={"optometrist_id": oid}).status_code == 403
    assert client.put(f"/api/appointments/{a2}/optometrist", headers=patient_hdr,
                      json={"optometrist_id": oid}).status_code == 403

    # finished appointments are locked
    assert client.put(f"/api/appointments/{a1}/status", headers=desk,
                      json={"status": "completed"}).status_code == 200
    assert client.put(f"/api/appointments/{a1}/optometrist", headers=desk,
                      json={"optometrist_id": oid}).status_code == 409
