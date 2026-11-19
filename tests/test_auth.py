"""Tests for the users build (0.2.0): auth, sessions, agent tokens, requests,
membership, and server-side enforcement."""

from pathlib import Path
import pyotp
import pytest
from fastapi.testclient import TestClient

from wyldfire.server import db as server_db
from wyldfire.server.app import create_app
from wyldfire.server import auth as server_auth

MASTER = "test-master-token-that-is-long-enough"
ADMIN_PASSWORD = "correct horse battery staple"
USER_PASSWORD = "another correct horse staple"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WYLD_SERVER_TOKEN", MASTER)
    monkeypatch.setattr("wyldfire.server.config.DATA_DIR", tmp_path)
    monkeypatch.setattr("wyldfire.server.config.DB_PATH", tmp_path / "server.db")
    app = create_app()
    with TestClient(app) as c:
        yield c


def bootstrap(c: TestClient, username: str = "GameGrue"):
    """Run the first-admin bootstrap; returns (session, user_token)."""
    secret = server_auth.new_totp_secret()
    code = pyotp.TOTP(secret).now()
    r = c.post("/api/v1/auth/admin-login", json={
        "master_token": MASTER,
        "username": username,
        "password": ADMIN_PASSWORD,
        "totp_secret": secret,
        "totp_code": code,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["bootstrap"] is True
    assert body["user"]["role"] == "admin"
    return body["session_token"], body["user_token"]


def auth_headers(token: str):
    return {"Authorization": f"Bearer {token}"}


def signup_user(c: TestClient, username="ryan", email="rj.cupar@gmail.com",
                password=USER_PASSWORD, with_totp=False):
    payload = {"username": username, "email": email, "password": password}
    secret = None
    if with_totp:
        secret = server_auth.new_totp_secret()
        payload["totp_secret"] = secret
        payload["totp_code"] = pyotp.TOTP(secret).now()
    r = c.post("/api/v1/auth/signup", json=payload)
    assert r.status_code == 201, r.text
    return r.json()["request_id"], secret


def approve(c: TestClient, admin_session: str, req_id: str):
    r = c.post(f"/api/v1/requests/{req_id}/approve", headers=auth_headers(admin_session))
    assert r.status_code == 200, r.text
    return r.json()


def login(c: TestClient, username, password, totp_code=None, totp_secret=None):
    payload = {"username": username, "password": password}
    if totp_code:
        payload["totp_code"] = totp_code
    if totp_secret:
        payload["totp_secret"] = totp_secret
    return c.post("/api/v1/auth/login", json=payload)


# --- Bootstrap + admin login ---------------------------------------------

def test_bootstrap_and_admin_login(client):
    session, _held = bootstrap(client)
    # Admin login after bootstrap: master token + TOTP code.
    admin = server_db.get_user_by_username("GameGrue")
    secret = server_auth.decrypt_totp_secret(admin["totp_secret_enc"])
    r = client.post("/api/v1/auth/admin-login", json={
        "master_token": MASTER,
        "totp_code": pyotp.TOTP(secret).now(),
    })
    assert r.status_code == 200, r.text
    assert r.json()["bootstrap"] is False
    assert r.json()["user"]["username"] == "GameGrue"


def test_bootstrap_wrong_master_token(client):
    secret = server_auth.new_totp_secret()
    r = client.post("/api/v1/auth/admin-login", json={
        "master_token": "wrong-token",
        "username": "GameGrue",
        "password": ADMIN_PASSWORD,
        "totp_secret": secret,
        "totp_code": pyotp.TOTP(secret).now(),
    })
    assert r.status_code == 401
    assert server_db.count_users() == 0  # nothing created on failure


def test_bootstrap_wrong_code_creates_no_user(client):
    secret = server_auth.new_totp_secret()
    r = client.post("/api/v1/auth/admin-login", json={
        "master_token": MASTER,
        "username": "GameGrue",
        "password": ADMIN_PASSWORD,
        "totp_secret": secret,
        "totp_code": "000000",
    })
    assert r.status_code == 401
    assert server_db.count_users() == 0


def test_master_token_refused_on_data_endpoints(client):
    bootstrap(client)
    r = client.get("/api/v1/projects", headers=auth_headers(MASTER))
    assert r.status_code == 401
    assert "login only" in r.json()["detail"]


# --- Signup / approval / login -------------------------------------------

def test_signup_approve_login_with_enrollment_at_login(client):
    admin_session, _ = bootstrap(client)
    req_id, _ = signup_user(client)
    # Pending: login refused.
    r = login(client, "ryan", USER_PASSWORD)
    assert r.status_code == 403 and "pending approval" in r.json()["detail"]
    approve(client, admin_session, req_id)
    # No TOTP yet: enrollment required, no session.
    r = login(client, "ryan", USER_PASSWORD)
    assert r.status_code == 200 and r.json()["status"] == "totp_enrollment_required"
    # Enroll inside the password-verified login.
    secret = server_auth.new_totp_secret()
    r = login(client, "ryan", USER_PASSWORD,
              totp_code=pyotp.TOTP(secret).now(), totp_secret=secret)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ok"
    assert r.json()["session_token"].startswith("wyld_sess_")
    assert r.json()["user_token"].startswith("wyld_sess_")
    # Next login: code required, wrong code refused.
    r = login(client, "ryan", USER_PASSWORD, totp_code="000000")
    assert r.status_code == 401


def test_signup_with_totp_then_login(client):
    admin_session, _ = bootstrap(client)
    req_id, secret = signup_user(client, with_totp=True)
    approve(client, admin_session, req_id)
    r = login(client, "ryan", USER_PASSWORD, totp_code=pyotp.TOTP(secret).now())
    assert r.status_code == 200, r.text
    assert r.json()["user"]["username"] == "ryan"


def test_signup_duplicate_username_and_email(client):
    bootstrap(client)
    signup_user(client)
    r = client.post("/api/v1/auth/signup", json={
        "username": "ryan", "email": "other@example.com", "password": USER_PASSWORD})
    assert r.status_code == 409 and "username taken" in r.json()["detail"]
    r = client.post("/api/v1/auth/signup", json={
        "username": "ryan2", "email": "rj.cupar@gmail.com", "password": USER_PASSWORD})
    assert r.status_code == 409 and "email already registered" in r.json()["detail"]


def test_deny_deletes_pending_secrets(client):
    admin_session, _ = bootstrap(client)
    req_id, _secret = signup_user(client, with_totp=True)
    r = client.post(f"/api/v1/requests/{req_id}/deny",
                    json={"reason": "not a collaborator"},
                    headers=auth_headers(admin_session))
    assert r.status_code == 200, r.text
    row = server_db.get_signup_request(req_id)
    assert row["status"] == "denied"
    assert row["password_hash"] is None and row["totp_secret_enc"] is None


def test_login_lockout_after_five_failures(client):
    admin_session, _ = bootstrap(client)
    req_id, _ = signup_user(client)
    approve(client, admin_session, req_id)
    for _ in range(5):
        r = login(client, "ryan", "wrong password")
        assert r.status_code == 401
    r = login(client, "ryan", USER_PASSWORD)
    assert r.status_code == 429 and "locked for 15 minutes" in r.json()["detail"]


def _admin_session(client, master_token=MASTER):
    admin = server_db.get_user_by_username("GameGrue")
    secret = server_auth.decrypt_totp_secret(admin["totp_secret_enc"])
    r = client.post("/api/v1/auth/admin-login", json={
        "master_token": master_token, "totp_code": pyotp.TOTP(secret).now()})
    assert r.status_code == 200, r.text
    return r.json()["session_token"], r.json()["user_token"]


def test_wrong_password_is_generic(client):
    bootstrap(client)
    r = login(client, "nosuchuser", "whatever")
    assert r.status_code == 401
    assert "incorrect username or password" in r.json()["detail"]


# --- Sessions / refresh / logout ------------------------------------------

def test_refresh_and_logout(client):
    admin_session, admin_held = bootstrap(client)
    r = client.post("/api/v1/auth/refresh", json={"held_token": admin_held})
    assert r.status_code == 200, r.text
    new_session = r.json()["session_token"]
    assert new_session != admin_session
    # Logout revokes the session and the held token.
    r = client.post("/api/v1/auth/logout", json={"held_token": admin_held},
                    headers=auth_headers(new_session))
    assert r.status_code == 200
    r = client.get("/api/v1/projects", headers=auth_headers(new_session))
    assert r.status_code == 401
    r = client.post("/api/v1/auth/refresh", json={"held_token": admin_held})
    assert r.status_code == 401


def test_session_list_and_revoke_all(client):
    admin_session, admin_held = bootstrap(client)
    r = client.get("/api/v1/sessions", headers=auth_headers(admin_session))
    assert r.status_code == 200
    sessions = r.json()["sessions"]
    assert len(sessions) == 1 and sessions[0]["self"] is True
    r = client.post("/api/v1/sessions/revoke-all", headers=auth_headers(admin_session))
    assert r.status_code == 200
    assert r.json()["sessions_revoked"] == 1
    r = client.get("/api/v1/projects", headers=auth_headers(admin_session))
    assert r.status_code == 401


# --- Agent tokens + server-side judgment refusal -------------------------

def _member_session(client, username="ryan"):
    admin_session, _ = bootstrap(client)
    req_id, secret = signup_user(client, username=username,
                                 email=f"{username}@example.com", with_totp=True)
    approve(client, admin_session, req_id)
    r = login(client, username, USER_PASSWORD, totp_code=pyotp.TOTP(secret).now())
    assert r.status_code == 200, r.text
    return admin_session, r.json()["session_token"]


def test_agent_token_judgment_refusal_and_stamping(client):
    admin_session, member_session = _member_session(client)
    # Member creates a project (becomes Owner).
    r = client.post("/api/v1/projects",
                    json={"project_id": "proj-1", "name": "ember_tdl"},
                    headers=auth_headers(member_session))
    assert r.status_code == 200, r.text
    assert r.json()["project"]["owner_id"] is not None
    # Mint an agent token.
    r = client.post("/api/v1/tokens", json={"name": "alder"},
                    headers=auth_headers(member_session))
    assert r.status_code == 200, r.text
    agent_token = r.json()["token"]
    assert agent_token.startswith("wyld_at_")
    # Normal event: accepted, stamped with the agent attribution.
    r = client.post("/api/v1/events", json={"project_id": "proj-1", "events": [
        {"id": "e1", "ts": "2026-11-19T00:00:00Z", "actor": "forged",
         "actor_email": "forged@example.com", "type": "flame.sparked",
         "payload": {"name": "f1"}}]},
        headers=auth_headers(agent_token))
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] == 1 and r.json()["rejected"] == []
    events = client.get("/api/v1/events", params={"project_id": "proj-1"},
                        headers=auth_headers(member_session)).json()["events"]
    assert events[0]["actor"] == "ryan (alder)"
    assert events[0]["actor_email"] == "ryan@example.com"
    # Judgment events: refused, reported, never silently dropped.
    r = client.post("/api/v1/events", json={"project_id": "proj-1", "events": [
        {"id": "e2", "ts": "2026-11-19T00:00:01Z", "actor": "ryan (alder)",
         "type": "gate.part1.passed", "payload": {"fire": "x"}},
        {"id": "e3", "ts": "2026-11-19T00:00:02Z", "actor": "ryan (alder)",
         "type": "smoke.cleared", "payload": {"id": 1}},
        {"id": "e4", "ts": "2026-11-19T00:00:03Z", "actor": "ryan (alder)",
         "type": "stoke.logged", "payload": {"metrics": {"enjoyment": 8}}},
        {"id": "e5", "ts": "2026-11-19T00:00:04Z", "actor": "ryan (alder)",
         "type": "stoke.logged", "payload": {"notes": "plain note, no metrics"}},
    ]}, headers=auth_headers(agent_token))
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] == 1  # only the metric-free stoke
    assert len(r.json()["rejected"]) == 3
    assert {x["type"] for x in r.json()["rejected"]} == {
        "gate.part1.passed", "smoke.cleared", "stoke.logged"}
    # A human session may record the same judgment events.
    r = client.post("/api/v1/events", json={"project_id": "proj-1", "events": [
        {"id": "e6", "ts": "2026-11-19T00:00:05Z", "actor": "ryan",
         "type": "gate.part1.passed", "payload": {"fire": "x"}}]},
        headers=auth_headers(member_session))
    assert r.json()["accepted"] == 1 and r.json()["rejected"] == []
    # Revoke the agent token: it stops working.
    r = client.delete("/api/v1/tokens/alder", headers=auth_headers(member_session))
    assert r.status_code == 200
    r = client.get("/api/v1/events", params={"project_id": "proj-1"},
                   headers=auth_headers(agent_token))
    assert r.status_code == 401


# --- Membership gating ----------------------------------------------------

def test_membership_gating(client):
    admin_session, member_session = _member_session(client)
    r = client.post("/api/v1/projects",
                    json={"project_id": "proj-1", "name": "ember_tdl"},
                    headers=auth_headers(member_session))
    assert r.status_code == 200
    # A second member can see the project listed but cannot push to it.
    _admin2, member2_session = _second_member(client, admin_session)
    r = client.get("/api/v1/projects", headers=auth_headers(member2_session))
    assert r.status_code == 200
    assert any(p["project_id"] == "proj-1" for p in r.json()["projects"])
    r = client.post("/api/v1/events", json={"project_id": "proj-1", "events": [
        {"id": "e1", "ts": "2026-11-19T00:00:00Z", "actor": "x",
         "type": "flame.sparked", "payload": {}}]},
        headers=auth_headers(member2_session))
    assert r.status_code == 403 and "not a member" in r.json()["detail"]
    # Project owner adds them; now it works.
    r = client.post("/api/v1/projects/proj-1/members",
                    json={"username": "sam", "role": "member"},
                    headers=auth_headers(member_session))
    assert r.status_code == 200, r.text
    r = client.post("/api/v1/events", json={"project_id": "proj-1", "events": [
        {"id": "e1", "ts": "2026-11-19T00:00:00Z", "actor": "x",
         "type": "flame.sparked", "payload": {}}]},
        headers=auth_headers(member2_session))
    assert r.status_code == 200 and r.json()["accepted"] == 1


def _second_member(client, admin_session):
    req_id, secret = signup_user(client, username="sam",
                                 email="sam@example.com", with_totp=True)
    approve(client, admin_session, req_id)
    r = login(client, "sam", USER_PASSWORD, totp_code=pyotp.TOTP(secret).now())
    assert r.status_code == 200, r.text
    return admin_session, r.json()["session_token"]


# --- Rotation + revocation cascade ----------------------------------------

def test_master_rotation(client):
    bootstrap(client)
    r = client.post("/api/v1/auth/rotate-master", json={
        "current_master_token": MASTER,
        "new_master_token": "a-brand-new-master-token-value"})
    assert r.status_code == 200, r.text
    # Old token is dead immediately.
    r = client.post("/api/v1/auth/admin-login", json={
        "master_token": MASTER, "totp_code": "000000"})
    assert r.status_code == 401
    # Audit lists the rotation.
    admin_session, _ = _admin_session(client, master_token="a-brand-new-master-token-value")
    r = client.get("/api/v1/auth/master-audit", headers=auth_headers(admin_session))
    assert r.status_code == 200
    assert len(r.json()["rotations"]) == 1


def test_user_revocation_cascade(client):
    admin_session, member_session = _member_session(client)
    # Member mints an agent token first.
    r = client.post("/api/v1/tokens", json={"name": "alder"},
                    headers=auth_headers(member_session))
    agent_token = r.json()["token"]
    user = server_db.get_user_by_username("ryan")
    r = client.post(f"/api/v1/users/{user['id']}/revoke", headers=auth_headers(admin_session))
    assert r.status_code == 200, r.text
    assert r.json()["agent_tokens_revoked"] == 1
    assert r.json()["sessions_revoked"] == 1
    assert r.json()["user_tokens_revoked"] == 1
    # Everything of theirs is dead; login is refused.
    r = client.get("/api/v1/events", params={"project_id": "x"},
                   headers=auth_headers(agent_token))
    assert r.status_code == 401
    r = login(client, "ryan", USER_PASSWORD)
    assert r.status_code == 403 and "revoked" in r.json()["detail"]
