"""FastAPI application for Wyldfire hosted sync server (users build 0.2.0).

Auth model (UPDATE_SPEC.md §1): users with argon2id passwords and TOTP,
a master token that is the bootstrap/recovery credential (stays valid after
bootstrap, decided 2026-11-19), agent tokens capped at member scope, and
90-day sliding sessions. The CLI is untrusted: every call is verified
server-side, identity stamps are replaced with the token owner's identity,
and judgment events from agent tokens are refused (never silently dropped).
"""

from typing import Any, Dict, List, Optional
import os

try:
    from fastapi import FastAPI, Depends, HTTPException, Header, Request, status
    from pydantic import BaseModel
except ImportError:
    # If fastapi not installed in local environment, provide placeholder
    FastAPI = None  # type: ignore
    Depends = lambda *args, **kwargs: None  # type: ignore
    HTTPException = None  # type: ignore
    Header = lambda *args, **kwargs: None  # type: ignore
    Request = None  # type: ignore
    status = None  # type: ignore
    BaseModel = object  # type: ignore

from wyldfire.server import auth, db


def _err(exc: auth.AuthError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.detail)


def create_app():
    server_token = os.environ.get("WYLD_SERVER_TOKEN")
    if not server_token:
        raise RuntimeError("WYLD_SERVER_TOKEN environment variable must be set")

    if FastAPI is None:
        raise RuntimeError("FastAPI is not installed. Install with 'pip install wyldfire[server]'")

    app = FastAPI(title="Wyldfire Sync Server", version="0.2.0")

    # --- Request models -------------------------------------------------

    class SignupRequest(BaseModel):
        username: str
        email: str
        password: str
        totp_secret: Optional[str] = None
        totp_code: Optional[str] = None

    class LoginRequest(BaseModel):
        username: str
        password: str
        totp_code: Optional[str] = None
        totp_secret: Optional[str] = None

    class AdminLoginRequest(BaseModel):
        master_token: str
        totp_code: Optional[str] = None
        username: Optional[str] = None
        password: Optional[str] = None
        totp_secret: Optional[str] = None

    class RefreshRequest(BaseModel):
        held_token: str

    class LogoutRequest(BaseModel):
        held_token: Optional[str] = None

    class RotateMasterRequest(BaseModel):
        current_master_token: str
        new_master_token: str

    class MintTokenRequest(BaseModel):
        name: str

    class DenyRequest(BaseModel):
        reason: Optional[str] = None

    class AddMemberRequest(BaseModel):
        username: str
        role: str = "member"

    class ProjectRequest(BaseModel):
        project_id: str
        name: str

    class PushEventsRequest(BaseModel):
        project_id: str
        events: List[Dict[str, Any]]

    # --- Auth plumbing --------------------------------------------------

    def client_ip(request: Request) -> str:
        if request.client is None:
            return "unknown"
        return request.client.host or "unknown"

    def get_caller(authorization: Optional[str] = Header(None)) -> auth.AuthContext:
        try:
            return auth.authenticate(authorization)
        except auth.AuthError as exc:
            raise _err(exc)

    def get_data_caller(ctx: auth.AuthContext = Depends(get_caller)) -> auth.AuthContext:
        try:
            return auth.require_data_caller(ctx)
        except auth.AuthError as exc:
            raise _err(exc)

    def get_admin(ctx: auth.AuthContext = Depends(get_caller)) -> auth.AuthContext:
        try:
            return auth.require_admin(ctx)
        except auth.AuthError as exc:
            raise _err(exc)

    def user_summary(user: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": user["id"],
            "username": user["username"],
            "email": user["email"],
            "role": user["role"],
            "status": user["status"],
            "totp_enrolled": bool(user["totp_enrolled"]),
            "created_at": user["created_at"],
        }

    def issue_session(user: Dict[str, Any]) -> Dict[str, Any]:
        """Mint a held user token + a 90-day session for a user. Returns both
        raw values (shown once) plus the session expiry."""
        user_token_value = auth.new_user_token()
        user_token = db.create_user_token(user["id"], auth.sha256_hex(user_token_value))
        session_value = auth.new_session_token()
        session = db.create_session(
            user["id"], auth.sha256_hex(session_value), user_token_id=user_token["id"]
        )
        return {
            "session_token": session_value,
            "user_token": user_token_value,
            "session_expires_at": session["expires_at"],
            "user": user_summary(user),
        }

    # --- Health ---------------------------------------------------------

    @app.get("/health")
    def health():
        return {"status": "ok", "app": "wyldfire-sync-server"}

    # --- Signup / login -------------------------------------------------

    @app.post("/api/v1/auth/signup", status_code=201)
    def signup(req: SignupRequest, request: Request):
        ip = client_ip(request)
        ip_key = f"signup:ip:{ip}"
        if db.is_locked(ip_key):
            raise HTTPException(
                status_code=429,
                detail="too many signup requests from this address (try again later)",
            )
        username = req.username.strip()
        email = req.email.strip()
        if not username or len(username) > 64 or any(c.isspace() for c in username):
            raise HTTPException(status_code=400, detail="invalid username (no spaces, up to 64 characters)")
        if "@" not in email or len(email) > 254:
            raise HTTPException(status_code=400, detail="invalid email address")
        # Username/email taken — across users AND open requests.
        if db.get_user_by_username(username) or any(
            r["username"] == username for r in db.list_signup_requests(status="open")
        ):
            raise HTTPException(status_code=409, detail="username taken (choose another)")
        if db.get_user_by_email(email) or any(
            r["email"] == email for r in db.list_signup_requests(status="open")
        ):
            raise HTTPException(status_code=409, detail="email already registered (log in, or sign up with another email)")
        try:
            password_hash = auth.hash_password(req.password)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        totp_secret_enc = None
        if req.totp_secret:
            if not req.totp_code or not auth.verify_totp(req.totp_secret, req.totp_code):
                raise HTTPException(status_code=400, detail="incorrect code (codes refresh every 30s; wait for a new code and retry)")
            totp_secret_enc = auth.encrypt_totp_secret(req.totp_secret)
        db.record_failed_attempt(ip_key, max_attempts=5, lockout_minutes=60)
        created = db.create_signup_request(username, email, password_hash, totp_secret_enc)
        return {"status": "pending", "request_id": created["id"],
                "detail": "signup request sent (pending admin approval)"}

    @app.post("/api/v1/auth/login")
    def login(req: LoginRequest, request: Request):
        ip = client_ip(request)
        username = req.username.strip()
        user_key = f"login:username:{username}"
        ip_key = f"login:ip:{ip}"
        if db.is_locked(user_key) or db.is_locked(ip_key):
            raise HTTPException(
                status_code=429,
                detail="too many failed attempts — login locked for 15 minutes (ask the admin to unlock, or wait)",
            )
        user = db.get_user_by_username(username)
        if user is None:
            # A pending signup is not a user yet — but the spec names it:
            # "account pending approval", not the generic wrong-credentials
            # line. A denied or never-requested name stays generic.
            if any(r["username"] == username
                   for r in db.list_signup_requests(status="open")):
                raise HTTPException(
                    status_code=403,
                    detail="account pending approval (the admin hasn't approved your signup yet — try again after approval)",
                )
            db.record_failed_attempt(ip_key)
            raise HTTPException(
                status_code=401, detail="incorrect username or password (check caps lock and try again)"
            )
        if not auth.verify_password(user["password_hash"], req.password):
            # Generic on purpose: never says whether the username exists.
            db.record_failed_attempt(ip_key)
            db.record_failed_attempt(user_key)
            raise HTTPException(
                status_code=401, detail="incorrect username or password (check caps lock and try again)"
            )
        if user["status"] == "revoked":
            raise HTTPException(status_code=403, detail="account revoked (ask the admin)")
        if user["status"] == "pending":
            raise HTTPException(
                status_code=403,
                detail="account pending approval (the admin hasn't approved your signup yet — try again after approval)",
            )
        # TOTP: enrolled users verify a code; unenrolled users enroll here,
        # inside the password-verified login — no session until a code verifies.
        if user["totp_enrolled"] and user["totp_secret_enc"]:
            if not req.totp_code:
                raise HTTPException(status_code=401, detail="TOTP code required (enter the code from your authenticator app)")
            secret = auth.decrypt_totp_secret(user["totp_secret_enc"])
            if not auth.verify_totp(secret, req.totp_code):
                db.record_failed_attempt(ip_key)
                db.record_failed_attempt(user_key)
                raise HTTPException(
                    status_code=401,
                    detail="incorrect code (codes refresh every 30s; wait for a new code and retry)",
                )
        elif req.totp_secret and req.totp_code:
            if not auth.verify_totp(req.totp_secret, req.totp_code):
                db.record_failed_attempt(ip_key)
                db.record_failed_attempt(user_key)
                raise HTTPException(
                    status_code=401,
                    detail="incorrect code (codes refresh every 30s; wait for a new code and retry)",
                )
            db.set_user_totp(user["id"], auth.encrypt_totp_secret(req.totp_secret))
        elif req.totp_secret or req.totp_code:
            raise HTTPException(status_code=400, detail="TOTP enrollment needs both the secret and a code")
        else:
            db.clear_rate_limit(user_key)
            db.clear_rate_limit(ip_key)
            return {"status": "totp_enrollment_required", "username": user["username"]}
        db.clear_rate_limit(user_key)
        db.clear_rate_limit(ip_key)
        result = issue_session(user)
        result["status"] = "ok"
        return result

    @app.post("/api/v1/auth/admin-login")
    def admin_login(req: AdminLoginRequest, request: Request):
        ip = client_ip(request)
        ip_key = f"master:ip:{ip}"
        if db.is_locked(ip_key):
            raise HTTPException(
                status_code=429,
                detail="too many failed attempts — login locked for 15 minutes (wait, or recover via the server console)",
            )
        stored = auth.ensure_master_hash()
        if stored is None or auth.sha256_hex(req.master_token) != stored:
            db.record_failed_attempt(ip_key)
            raise HTTPException(
                status_code=401, detail="incorrect master token (check the token and try again)"
            )
        if db.count_users() == 0:
            # Bootstrap: no users exist yet. The CLI probes with just the
            # master token first; the server answers bootstrap_required and
            # the CLI then runs the enrollment walk and re-posts with the
            # full bootstrap fields. The admin user is created atomically
            # when a TOTP code verifies — aborting before that leaves no
            # user behind.
            if not req.username or not req.totp_secret or not req.totp_code:
                return {"status": "bootstrap_required",
                        "detail": "no users exist yet — setting up the admin account"}
            username = req.username.strip()
            password = req.password or ""
            if not username or len(username) > 64 or any(c.isspace() for c in username):
                raise HTTPException(status_code=400, detail="invalid username (no spaces, up to 64 characters)")
            try:
                password_hash = auth.hash_password(password)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc))
            if not auth.verify_totp(req.totp_secret, req.totp_code):
                db.record_failed_attempt(ip_key)
                raise HTTPException(
                    status_code=401,
                    detail="incorrect code (codes refresh every 30s; wait for a new code and retry)",
                )
            user = db.create_user(
                username, "", password_hash, role="admin", status="active",
                totp_secret_enc=auth.encrypt_totp_secret(req.totp_secret),
            )
            db.backfill_project_owners(user["id"])
            db.clear_rate_limit(ip_key)
            result = issue_session(user)
            result["status"] = "ok"
            result["bootstrap"] = True
            return result
        admin = auth._find_first_admin()
        if admin is None:
            raise HTTPException(status_code=403, detail="no admin user exists (run the bootstrap login first)")
        if not admin["totp_enrolled"] or not admin["totp_secret_enc"]:
            raise HTTPException(
                status_code=400, detail="admin TOTP not enrolled (recover via the server console)"
            )
        if not req.totp_code:
            raise HTTPException(status_code=401, detail="TOTP code required (enter the code from your authenticator app)")
        secret = auth.decrypt_totp_secret(admin["totp_secret_enc"])
        if not auth.verify_totp(secret, req.totp_code):
            db.record_failed_attempt(ip_key)
            raise HTTPException(
                status_code=401,
                detail="incorrect code (codes refresh every 30s; wait for a new code and retry)",
            )
        db.clear_rate_limit(ip_key)
        result = issue_session(admin)
        result["status"] = "ok"
        result["bootstrap"] = False
        return result

    @app.post("/api/v1/auth/refresh")
    def refresh(req: RefreshRequest):
        held = req.held_token.strip()
        if not held:
            raise HTTPException(status_code=401, detail="held token invalid (log in again)")
        if held.startswith(auth.SESSION_TOKEN_PREFIX):
            row = db.get_user_token_by_hash(auth.sha256_hex(held))
            if row is None or row["revoked"]:
                raise HTTPException(status_code=401, detail="held token invalid (log in again)")
            user = db.get_user_by_id(row["user_id"])
            if user is None or user["status"] != "active":
                raise HTTPException(status_code=403, detail="account revoked (ask the admin)")
            db.touch_user_token(row["id"])
            session_value = auth.new_session_token()
            session = db.create_session(
                user["id"], auth.sha256_hex(session_value), user_token_id=row["id"]
            )
            return {"status": "ok", "session_token": session_value,
                    "session_expires_at": session["expires_at"], "user": user_summary(user)}
        stored = auth.ensure_master_hash()
        if stored is None or auth.sha256_hex(held) != stored:
            raise HTTPException(status_code=401, detail="held token invalid (log in again)")
        admin = auth._find_first_admin()
        if admin is None:
            raise HTTPException(
                status_code=403, detail="no users exist yet — run the admin bootstrap login first"
            )
        session_value = auth.new_session_token()
        session = db.create_session(admin["id"], auth.sha256_hex(session_value))
        return {"status": "ok", "session_token": session_value,
                "session_expires_at": session["expires_at"], "user": user_summary(admin)}

    @app.post("/api/v1/auth/logout")
    def logout(req: LogoutRequest, ctx: auth.AuthContext = Depends(get_caller)):
        if ctx.kind == "session" and ctx.session_id:
            db.revoke_session(ctx.session_id)
        if req.held_token and req.held_token.startswith(auth.SESSION_TOKEN_PREFIX):
            row = db.get_user_token_by_hash(auth.sha256_hex(req.held_token))
            if row is not None:
                db.revoke_user_token(row["id"])
        return {"status": "ok"}

    @app.get("/api/v1/auth/me")
    def me(ctx: auth.AuthContext = Depends(get_data_caller)):
        if ctx.kind != "session":
            raise HTTPException(status_code=403, detail="sessions only (log in as a user)")
        user = db.get_user_by_id(ctx.user_id)  # type: ignore[arg-type]
        if user is None:
            raise HTTPException(status_code=404, detail="user not found")
        return {"status": "ok", "user": user_summary(user)}

    @app.post("/api/v1/auth/rotate-master")
    def rotate_master(req: RotateMasterRequest, request: Request):
        ip = client_ip(request)
        ip_key = f"master:ip:{ip}"
        if db.is_locked(ip_key):
            raise HTTPException(
                status_code=429,
                detail="too many failed attempts — login locked for 15 minutes (wait, or recover via the server console)",
            )
        stored = auth.ensure_master_hash()
        if stored is None or auth.sha256_hex(req.current_master_token) != stored:
            db.record_failed_attempt(ip_key)
            raise HTTPException(status_code=401, detail="incorrect master token (check the token and try again)")
        if len(req.new_master_token) < 20:
            raise HTTPException(status_code=400, detail="new master token must be at least 20 characters")
        db.rotate_master_hash(
            auth.sha256_hex(req.new_master_token), auth.sha256_hex(req.current_master_token)[:8]
        )
        db.clear_rate_limit(ip_key)
        return {"status": "ok", "detail": "master token rotated (old token is dead immediately; user tokens survive)"}

    @app.get("/api/v1/auth/master-audit")
    def master_audit(ctx: auth.AuthContext = Depends(get_admin)):
        return {"status": "ok", "rotations": db.list_master_audit()}

    # --- Agent tokens ---------------------------------------------------

    @app.post("/api/v1/tokens")
    def mint_token(req: MintTokenRequest, ctx: auth.AuthContext = Depends(get_data_caller)):
        if ctx.kind != "session":
            raise HTTPException(
                status_code=403, detail="agent tokens are minted from a user session (log in as a user first)"
            )
        name = req.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="agent token name cannot be empty")
        existing = db.get_agent_token_by_name(ctx.user_id, name)  # type: ignore[arg-type]
        if existing is not None and not existing["revoked"]:
            raise HTTPException(
                status_code=409, detail=f"agent token '{name}' already exists — revoke it first"
            )
        value = auth.new_agent_token()
        db.create_agent_token(ctx.user_id, name, auth.sha256_hex(value))  # type: ignore[arg-type]
        return {"status": "ok", "name": name, "scope": "member",
                "token": value,
                "detail": "token shown once — store it securely, it won't be shown again"}

    @app.get("/api/v1/tokens")
    def list_tokens(ctx: auth.AuthContext = Depends(get_data_caller)):
        if ctx.kind != "session":
            raise HTTPException(status_code=403, detail="agent tokens are listed from a user session")
        rows = [r for r in db.list_agent_tokens(ctx.user_id) if not r["revoked"]]  # type: ignore[arg-type]
        return {"status": "ok", "tokens": [
            {"name": r["name"], "scope": "member", "created": r["created_at"],
             "last_used": r["last_used_at"]} for r in rows
        ]}

    @app.delete("/api/v1/tokens/{name}")
    def revoke_token(name: str, ctx: auth.AuthContext = Depends(get_data_caller)):
        if ctx.kind != "session":
            raise HTTPException(status_code=403, detail="agent tokens are revoked from a user session")
        row = db.get_agent_token_by_name(ctx.user_id, name)  # type: ignore[arg-type]
        if row is None or row["revoked"]:
            raise HTTPException(status_code=404, detail=f"agent token '{name}' not found")
        db.revoke_agent_token(row["id"])
        return {"status": "ok", "revoked": name,
                "detail": "agent token revoked (sessions made with it are revoked too)"}

    # --- Sessions -------------------------------------------------------

    @app.get("/api/v1/sessions")
    def list_sessions(all_sessions: bool = False, ctx: auth.AuthContext = Depends(get_data_caller)):
        if ctx.kind != "session":
            raise HTTPException(status_code=403, detail="sessions are listed from a user session")
        if all_sessions:
            auth.require_admin(ctx)
            rows = db.list_sessions(None)
        else:
            rows = db.list_sessions(ctx.user_id)
        out = []
        for r in rows:
            user = db.get_user_by_id(r["user_id"])
            out.append({
                "id": r["id"],
                "username": user["username"] if user else "?",
                "created_at": r["created_at"],
                "expires_at": r["expires_at"],
                "last_used_at": r["last_used_at"],
                "revoked": bool(r["revoked"]),
                "self": r["id"] == ctx.session_id,
            })
        return {"status": "ok", "sessions": out}

    @app.delete("/api/v1/sessions/{session_id}")
    def revoke_session(session_id: str, ctx: auth.AuthContext = Depends(get_data_caller)):
        if ctx.kind != "session":
            raise HTTPException(status_code=403, detail="sessions are revoked from a user session")
        rows = db.list_sessions(ctx.user_id)
        target = next((r for r in rows if r["id"] == session_id), None)
        if target is None:
            if ctx.role == "admin":
                all_rows = db.list_sessions(None)
                target = next((r for r in all_rows if r["id"] == session_id), None)
            if target is None:
                raise HTTPException(status_code=404, detail="session not found")
        db.revoke_session(session_id)
        return {"status": "ok", "revoked": session_id}

    @app.post("/api/v1/sessions/revoke-all")
    def revoke_all_sessions(all_sessions: bool = False, ctx: auth.AuthContext = Depends(get_data_caller)):
        if ctx.kind != "session":
            raise HTTPException(status_code=403, detail="sessions are revoked from a user session")
        if all_sessions:
            auth.require_admin(ctx)
            users = db.list_users()
            total_sessions = sum(db.revoke_all_sessions(u["id"]) for u in users)
            total_tokens = sum(db.revoke_all_user_tokens(u["id"]) for u in users)
            return {"status": "ok", "sessions_revoked": total_sessions,
                    "user_tokens_revoked": total_tokens,
                    "detail": "all sessions and held tokens revoked (every machine logged out — log in again everywhere)"}
        sessions = db.revoke_all_sessions(ctx.user_id)  # type: ignore[arg-type]
        tokens = db.revoke_all_user_tokens(ctx.user_id)  # type: ignore[arg-type]
        return {"status": "ok", "sessions_revoked": sessions, "user_tokens_revoked": tokens}

    # --- Users (admin) --------------------------------------------------

    @app.get("/api/v1/users")
    def list_users(ctx: auth.AuthContext = Depends(get_admin)):
        return {"status": "ok", "users": [user_summary(u) for u in db.list_users()]}

    @app.post("/api/v1/users/{user_id}/revoke")
    def revoke_user(user_id: str, ctx: auth.AuthContext = Depends(get_admin)):
        if ctx.user_id == user_id:
            raise HTTPException(status_code=400, detail="cannot revoke your own account")
        user = db.get_user_by_id(user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="user not found")
        if user["status"] == "revoked":
            raise HTTPException(status_code=409, detail="user already revoked")
        counts = db.revoke_user(user_id)
        return {"status": "ok", "username": user["username"],
                "agent_tokens_revoked": counts["agent_tokens_revoked"],
                "sessions_revoked": counts["sessions_revoked"],
                "user_tokens_revoked": counts["user_tokens_revoked"]}

    # --- Signup requests (admin) ----------------------------------------

    @app.get("/api/v1/requests")
    def list_requests(status_filter: Optional[str] = None, ctx: auth.AuthContext = Depends(get_admin)):
        rows = db.list_signup_requests(status=status_filter)
        return {"status": "ok", "requests": [
            {"id": r["id"], "type": "signup", "username": r["username"], "email": r["email"],
             "status": r["status"], "requested_at": r["requested_at"],
             "decided_at": r["decided_at"], "reason": r["reason"]} for r in rows
        ]}

    @app.get("/api/v1/requests/{req_id}")
    def show_request(req_id: str, ctx: auth.AuthContext = Depends(get_admin)):
        row = db.get_signup_request(req_id)
        if row is None:
            raise HTTPException(status_code=404, detail="request not found")
        return {"status": "ok", "request": {
            "id": row["id"], "type": "signup", "username": row["username"],
            "email": row["email"], "status": row["status"],
            "requested_at": row["requested_at"], "decided_at": row["decided_at"],
            "reason": row["reason"]}}

    @app.post("/api/v1/requests/{req_id}/approve")
    def approve_request(req_id: str, ctx: auth.AuthContext = Depends(get_admin)):
        row = db.get_signup_request(req_id)
        if row is None:
            raise HTTPException(status_code=404, detail="request not found")
        if row["status"] != "open":
            raise HTTPException(status_code=409, detail="request already decided")
        if db.get_user_by_username(row["username"]) or db.get_user_by_email(row["email"]):
            raise HTTPException(status_code=409, detail="username or email already registered")
        user = db.create_user(
            row["username"], row["email"], row["password_hash"], role="member",
            status="active", totp_secret_enc=row["totp_secret_enc"],
        )
        db.decide_signup_request(req_id, "approved")
        return {"status": "ok", "username": user["username"],
                "detail": "signup approved (they can now log in; TOTP enrollment at first login if not already enrolled at signup)"}

    @app.post("/api/v1/requests/{req_id}/deny")
    def deny_request(req_id: str, req: DenyRequest, ctx: auth.AuthContext = Depends(get_admin)):
        row = db.get_signup_request(req_id)
        if row is None:
            raise HTTPException(status_code=404, detail="request not found")
        if row["status"] != "open":
            raise HTTPException(status_code=409, detail="request already decided")
        db.decide_signup_request(req_id, "denied", reason=req.reason)
        return {"status": "ok", "username": row["username"],
                "detail": "signup denied (pending account and its TOTP secret deleted)"}

    # --- Projects + membership ------------------------------------------

    @app.get("/api/v1/projects")
    def list_projects(ctx: auth.AuthContext = Depends(get_data_caller)):
        return {"status": "ok", "projects": [
            {"project_id": p["project_id"], "name": p["name"],
             "owner_id": p.get("owner_id"), "created_at": p["created_at"]}
            for p in db.list_projects()
        ]}

    @app.post("/api/v1/projects")
    def create_or_link_project(req: ProjectRequest, ctx: auth.AuthContext = Depends(get_data_caller)):
        existing = next(
            (p for p in db.list_projects() if p["project_id"] == req.project_id), None
        )
        if existing is not None:
            role = db.get_member_role(req.project_id, ctx.user_id)  # type: ignore[arg-type]
            if role is None and ctx.kind != "master":
                raise HTTPException(
                    status_code=403,
                    detail="not a member of this project (ask a project admin to add you)",
                )
            return {"status": "ok", "project": existing}
        proj = db.get_or_create_project(req.project_id, req.name, owner_id=ctx.user_id)
        return {"status": "ok", "project": proj, "created": True}

    @app.get("/api/v1/projects/{project_id}/members")
    def list_project_members(project_id: str, ctx: auth.AuthContext = Depends(get_data_caller)):
        role = db.get_member_role(project_id, ctx.user_id)  # type: ignore[arg-type]
        if role is None and not (ctx.kind == "session" and ctx.role == "admin"):
            raise HTTPException(
                status_code=403,
                detail="not a member of this project (ask a project admin to add you)",
            )
        return {"status": "ok", "members": db.list_members(project_id)}

    @app.post("/api/v1/projects/{project_id}/members")
    def add_project_member(project_id: str, req: AddMemberRequest, ctx: auth.AuthContext = Depends(get_data_caller)):
        role = db.get_member_role(project_id, ctx.user_id)  # type: ignore[arg-type]
        is_server_admin = ctx.kind == "session" and ctx.role == "admin"
        if role not in ("owner", "admin") and not is_server_admin:
            raise HTTPException(
                status_code=403, detail="only a project admin can add members"
            )
        if req.role not in ("member", "admin"):
            raise HTTPException(status_code=400, detail="role must be member or admin")
        user = db.get_user_by_username(req.username.strip())
        if user is None or user["status"] != "active":
            raise HTTPException(status_code=404, detail="user not found or not active")
        db.add_member(project_id, user["id"], role=req.role)
        return {"status": "ok", "project_id": project_id,
                "username": user["username"], "role": req.role}

    # --- Events (with server-side enforcement) --------------------------

    @app.post("/api/v1/events")
    def push_events(req: PushEventsRequest, ctx: auth.AuthContext = Depends(get_data_caller)):
        existing = next(
            (p for p in db.list_projects() if p["project_id"] == req.project_id), None
        )
        if existing is None:
            raise HTTPException(status_code=404, detail="project not found (link it first)")
        role = db.get_member_role(req.project_id, ctx.user_id)  # type: ignore[arg-type]
        if role is None:
            raise HTTPException(
                status_code=403,
                detail="not a member of this project (ask a project admin to add you)",
            )
        # Identity stamping: the server replaces the stamp with the token
        # owner's identity, so a crafted stamp can't impersonate anyone.
        if ctx.is_agent:
            actor = f"{ctx.username} ({ctx.agent_name})"
        else:
            actor = ctx.username
        accepted_events: List[Dict[str, Any]] = []
        rejected: List[Dict[str, Any]] = []
        for ev in req.events:
            ev_type = str(ev.get("type", ""))
            payload = ev.get("payload", {}) if isinstance(ev.get("payload"), dict) else {}
            if ctx.is_agent and auth.is_judgment_event(ev_type, payload):
                rejected.append({
                    "id": ev.get("id"),
                    "type": ev_type,
                    "reason": f"event \"{ev_type}\" refused — agent tokens cannot record gate verdicts",
                })
                continue
            stamped = dict(ev)
            stamped["actor"] = actor
            stamped["actor_email"] = ctx.email
            accepted_events.append(stamped)
        accepted, skipped = db.save_events(req.project_id, accepted_events)
        return {"status": "ok", "accepted": accepted, "skipped": skipped, "rejected": rejected}

    @app.get("/api/v1/events")
    def pull_events(project_id: str, since: Optional[str] = None,
                    ctx: auth.AuthContext = Depends(get_data_caller)):
        existing = next((p for p in db.list_projects() if p["project_id"] == project_id), None)
        if existing is None:
            raise HTTPException(status_code=404, detail="project not found (link it first)")
        role = db.get_member_role(project_id, ctx.user_id)  # type: ignore[arg-type]
        if role is None:
            raise HTTPException(
                status_code=403,
                detail="not a member of this project (ask a project admin to add you)",
            )
        events = db.get_events(project_id, since=since)
        return {"status": "ok", "project_id": project_id, "events": events}

    return app


class MissingTokenApp:
    def __call__(self, scope, receive, send):
        raise RuntimeError("WYLD_SERVER_TOKEN environment variable must be set")


# Lazy-loaded instance for uvicorn
app = None
if FastAPI is not None:
    if os.environ.get("WYLD_SERVER_TOKEN"):
        app = create_app()
    else:
        app = MissingTokenApp()
