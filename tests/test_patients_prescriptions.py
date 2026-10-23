"""Patient CRUD, HK-ID generation, OD/OS validation + audit trail tests
(System Rules 2, 3, 4)."""

from app.database.connection import fetch_all


def _head(headers):  # dict copy helper
    return {k: v for k, v in headers.items()}


def test_front_desk_creates_patient_with_hk_id_and_audit(client, front_desk):
    _, hdr = front_desk
    res = client.post("/api/patients", headers=_head(hdr), json={
        "first_name": "Mika", "last_name": "Loren", "date_of_birth": "1999-04-21",
        "sex": "female", "contact_number": "09171112222",
    })
    assert res.status_code == 201
    hk = res.json()["hk_patient_id"]
    assert hk.startswith("HK-") and len(hk) == 8 and hk[3:].isdigit()

    audit = fetch_all("SELECT action, table_name FROM audit_logs")
    assert ("CREATE", "patients") in [(a["action"], a["table_name"]) for a in audit]


def test_patient_cannot_create_patient(client, db):
    from tests.conftest import make_user, auth_header
    uid = make_user("pt@test.local", "Good@123", "patient")
    res = client.post("/api/patients", headers=auth_header(uid), json={
        "first_name": "No", "last_name": "Access", "date_of_birth": "2000-01-01"})
    assert res.status_code == 403


def test_identity_resolution_links_record(client, db):
    from tests.conftest import execute, auth_header, make_user
    pid = execute(
        "INSERT INTO patients (hk_patient_id, first_name, last_name, date_of_birth) "
        "VALUES ('HK-00042', 'Sonny', 'Test', '1988-08-08')")
    uid = make_user("link@test.local", "Good@123", "patient")

    res = client.get("/api/patients/me", headers=auth_header(uid))
    assert res.status_code == 404, "no link yet"

    # register (link) via identity resolution endpoint
    res = client.post("/api/auth/register", json={
        "full_name": "Sonny Test", "email": "sonny@test.com",
        "password": "Good@12345", "hk_patient_id": "HK-00042",
        "date_of_birth": "1988-08-08"})
    assert res.status_code == 200
    # the account register created is the one linked to the clinic record
    linked_token = res.json()["token"]
    res = client.get("/api/patients/me",
                     headers={"Authorization": f"Bearer {linked_token}"})
    assert res.status_code == 200 and res.json()["hk_patient_id"] == "HK-00042"


def test_optometrist_creates_prescription_validated(client, optometrist, front_desk):
    _, desk = front_desk
    _, hdr = optometrist

    mk = client.post("/api/patients", headers=_head(desk), json={
        "first_name": "Ann", "last_name": "Eyes", "date_of_birth": "1990-01-01"})
    patient_id = mk.json()["id"]

    res = client.post("/api/prescriptions", headers=_head(hdr), json={
        "patient_id": patient_id,
        "od": {"sphere": -2.25, "cylinder": -1.0, "axis": 175},
        "os": {"sphere": -2.5, "cylinder": -0.75, "axis": 10, "add": 2.5},
        "lens_type": "progressive",
    })
    assert res.status_code == 201, res.text

    rows = fetch_all("SELECT od_axis, od_add FROM prescriptions")
    assert rows[0]["od_axis"] == 175 or rows[0]["od_axis"] == 175  # stored intact


def test_axis_without_cylinder_rejected_422(client, optometrist, front_desk):
    _, desk = front_desk
    _, hdr = optometrist
    patient_id = client.post("/api/patients", headers=_head(desk), json={
        "first_name": "Bo", "last_name": "Axle", "date_of_birth": "1980-02-02"}).json()["id"]

    res = client.post("/api/prescriptions", headers=_head(hdr), json={
        "patient_id": patient_id,
        "od": {"sphere": -1.0, "cylinder": 0.0, "axis": 90},
        "os": {"sphere": -1.0},
    })
    assert res.status_code == 422  # axis only meaningful with cylinder


def test_front_desk_cannot_create_prescription(client, front_desk):
    _, hdr = front_desk
    patient_id = client.post("/api/patients", headers=_head(hdr), json={
        "first_name": "Ced", "last_name": "Desk", "date_of_birth": "1970-01-01"}).json()["id"]
    res = client.post("/api/prescriptions", headers=_head(hdr), json={
        "patient_id": patient_id,
        "od": {"sphere": 0.0}, "os": {"sphere": 0.0}})
    assert res.status_code == 403


def test_archive_soft_delete_and_audit(client, admin):
    _, hdr = admin
    patient_id = client.post("/api/patients", headers=_head(hdr), json={
        "first_name": "Del", "last_name": "Ete", "date_of_birth": "1985-01-01"}).json()["id"]

    res = client.delete(f"/api/patients/{patient_id}", headers=_head(hdr))
    assert res.status_code == 200
    state = client.get(f"/api/patients/{patient_id}", headers=_head(hdr))
    assert state.status_code == 404  # hidden from directory
    audit = fetch_all("SELECT action FROM audit_logs WHERE table_name='patients'")
    assert ("DELETE",) in [(a["action"],) for a in audit]
