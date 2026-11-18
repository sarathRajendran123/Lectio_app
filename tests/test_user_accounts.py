"""Accounts an administrator creates must be usable straight away."""
import uuid

import pytest


@pytest.mark.parametrize("role", ["lecturer", "coordinator", "dept_head", "admin"])
def test_a_user_created_by_an_admin_can_log_in_and_see_courses(client, headers, role):
    email = f"New.User-{uuid.uuid4().hex[:8]}@Uni.example.org"     # mixed case, as people type it
    password = "Neues-Passwort-2026"                                # test value only
    r = client.post("/api/v1/admin/users", headers=headers, json={"email": email, "full_name": "Neue Lehrende", "password": password, "role": role})
    assert r.status_code == 201, r.text
    login = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    own = {"Authorization": f"Bearer {login.json()['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=own)
    assert me.status_code == 200 and role in me.json()["roles"], me.text
    assert client.get("/api/v1/courses", headers=own).status_code == 200


def test_an_admin_can_set_a_new_password_which_lifts_a_lockout_and_ends_old_sessions(client, headers):
    email = f"locked-{uuid.uuid4().hex[:8]}@example.org"
    r = client.post("/api/v1/admin/users", headers=headers, json={"email": email, "full_name": "Gesperrte Person", "password": "Erstes-Passwort-1", "role": "lecturer"})
    user_id = r.json()["id"]
    old_refresh = client.post("/api/v1/auth/login", json={"email": email, "password": "Erstes-Passwort-1"}).json()["refresh_token"]
    for _ in range(5):                                                 # five wrong passwords lock the account
        assert client.post("/api/v1/auth/login", json={"email": email, "password": "falsch-falsch"}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": email, "password": "Erstes-Passwort-1"}).status_code == 401   # locked
    assert client.patch(f"/api/v1/admin/users/{user_id}", headers=headers, json={"password": "kurz"}).status_code == 422
    assert client.patch(f"/api/v1/admin/users/{user_id}", headers=headers, json={"password": "Neues-Passwort-2"}).status_code == 200
    assert client.post("/api/v1/auth/login", json={"email": email, "password": "Neues-Passwort-2"}).status_code == 200
    assert client.post("/api/v1/auth/login", json={"email": email, "password": "Erstes-Passwort-1"}).status_code == 401
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh}).status_code == 401   # old session ended


def test_only_an_admin_can_set_another_users_password(client, headers):
    a = f"lect-{uuid.uuid4().hex[:8]}@example.org"
    b = client.post("/api/v1/admin/users", headers=headers, json={"email": f"other-{uuid.uuid4().hex[:8]}@example.org", "full_name": "Andere", "password": "Anderes-Pass-3", "role": "lecturer"}).json()["id"]
    client.post("/api/v1/admin/users", headers=headers, json={"email": a, "full_name": "Lehrende", "password": "Lehr-Passwort-4", "role": "lecturer"})
    token = client.post("/api/v1/auth/login", json={"email": a, "password": "Lehr-Passwort-4"}).json()["access_token"]
    assert client.patch(f"/api/v1/admin/users/{b}", headers={"Authorization": f"Bearer {token}"}, json={"password": "Uebernommen-5"}).status_code == 403
