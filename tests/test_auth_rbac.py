"""Authentication + RBAC enforcement tests (System Rule 1)."""

import pytest


def test_login_success_returns_token_and_role(client, db):
    from tests.conftest import make_user
    make_user("login@test.local", "Good@123", "front_desk")
    res = client.post("/api/auth/login",
                      json={"email": "login@test.local", "password": "Good@123"})
    assert res.status_code == 200
    body = res.json()
    assert body["token"] and body["user"]["role"] == "front_desk"


def test_login_wrong_password_401(client, db):
    from tests.conftest import make_user
    make_user("login2@test.local", "Good@123", "front_desk")
    res = client.post("/api/auth/login",
                      json={"email": "login2@test.local", "password": "Wrong@123"})
    assert res.status_code == 401


def test_me_with_token_roundtrip(client, db):
    from tests.conftest import make_user, auth_header
    uid = make_user("me@test.local", "Good@123", "optometrist")
    res = client.get("/api/auth/me", headers=auth_header(uid))
    assert res.status_code == 200
    assert res.json()["email"] == "me@test.local"


def test_missing_token_is_401(client, db):
    assert client.get("/api/patients").status_code == 401


WHITELIST = [  # endpoint, method, roles allowed — patient must get 403 on staff ones
    ("/api/patients", "get", ["admin", "optometrist", "front_desk"]),
    ("/api/users", "get", ["admin"]),
    ("/api/audit-logs", "get", ["admin"]),
]


@pytest.mark.parametrize("path,method,allowed", WHITELIST)
def test_rbac_matrix(path, method, allowed, client, db):
    from tests.conftest import make_user, auth_header
    for role in ("admin", "optometrist", "front_desk", "patient"):
        uid = make_user(f"{role}@rbac.test", "Good@123", role)
        call = getattr(client, method)
        res = call(path, headers=auth_header(uid))
        expected = 200 if role in allowed else 403
        assert res.status_code == expected, (role, res.status_code, res.text)
