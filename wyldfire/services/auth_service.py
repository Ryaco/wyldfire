"""Auth service: HTTP client for the users-build auth API + login flows.

All requests go through `_api`, which turns server errors into one-line
WyldErrors carrying the server's own detail (the fix is already inside
it). Secrets are never logged and never stored outside the credentials
file (0600).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import urllib.request
import urllib.error

from wyldfire.core import credentials as creds
from wyldfire.core.exceptions import WyldError


def _api(url: str, method: str, path: str, token: Optional[str] = None,
         body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    full = url.rstrip("/") + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(full, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8")).get("detail", e.reason)
        except Exception:
            detail = e.reason
        raise WyldError(str(detail), _fix_for_status(e.code))
    except urllib.error.URLError as e:
        raise WyldError(
            f"server at {url} unreachable ({e.reason})",
            "check the URL and that the server is running",
        )


def _fix_for_status(code: int) -> str:
    if code == 401:
        return "log in again"
    if code == 403:
        return "check your role and membership"
    if code == 404:
        return "check the name or id"
    if code == 409:
        return "pick another value or check the current state"
    if code == 429:
        return "wait and try again"
    return "check the server and try again"


def _parse_expiry(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def session_is_valid(entry: Optional[Dict[str, Any]]) -> bool:
    if not entry or not entry.get("session_token"):
        return False
    exp = _parse_expiry(entry.get("session_expires_at"))
    if exp is None:
        return False
    return datetime.now(timezone.utc) < exp


def get_stored_auth(remote_name: Optional[str]) -> Optional[Dict[str, Any]]:
    if not remote_name:
        return None
    return creds.get_remote_auth(remote_name)


def store_session(remote_name: str, result: Dict[str, Any], held_token: str,
                  held_kind: str) -> Dict[str, Any]:
    """Persist a login result (session + held token + identity)."""
    user = result.get("user", {})
    entry = {
        "session_token": result["session_token"],
        "session_expires_at": result.get("session_expires_at", ""),
        "held_token": held_token,
        "held_kind": held_kind,
        "username": user.get("username", ""),
        "email": user.get("email", ""),
        "role": user.get("role", "member"),
    }
    creds.set_remote_auth(remote_name, entry)
    return entry


def ensure_session(remote_name: Optional[str], url: str) -> str:
    """Return a valid session token for a remote, renewing silently from
    the held token when the session expired. Raises WyldError when no
    login exists or the held token is dead."""
    if not remote_name:
        raise WyldError(
            f"not logged in to {url} (ad-hoc server)",
            "log in with 'wyld remote login <name>' first, or register the server",
        )
    entry = get_stored_auth(remote_name)
    if entry is None:
        raise WyldError(
            f"not logged in to remote \"{remote_name}\"",
            f"log in with 'wyld remote login {remote_name}'",
        )
    if session_is_valid(entry):
        return entry["session_token"]
    held = entry.get("held_token", "")
    if not held:
        raise WyldError(
            f"session expired and no held token for remote \"{remote_name}\"",
            f"log in again with 'wyld remote login {remote_name}'",
        )
    try:
        result = _api(url, "POST", "/api/v1/auth/refresh", body={"held_token": held})
    except WyldError:
        raise WyldError(
            f"session expired and held token invalid for remote \"{remote_name}\"",
            f"log in again with 'wyld remote login {remote_name}'",
        )
    store_session(remote_name, result, held, entry.get("held_kind", "user"))
    return result["session_token"]


def login_user_request(url: str, username: str, password: str,
                       totp_code: Optional[str] = None,
                       totp_secret: Optional[str] = None) -> Dict[str, Any]:
    body: Dict[str, Any] = {"username": username, "password": password}
    if totp_code:
        body["totp_code"] = totp_code
    if totp_secret:
        body["totp_secret"] = totp_secret
    return _api(url, "POST", "/api/v1/auth/login", body=body)


def admin_login_request(url: str, master_token: str,
                        totp_code: Optional[str] = None,
                        username: Optional[str] = None,
                        password: Optional[str] = None,
                        totp_secret: Optional[str] = None) -> Dict[str, Any]:
    body: Dict[str, Any] = {"master_token": master_token}
    if totp_code:
        body["totp_code"] = totp_code
    if username:
        body["username"] = username
    if password:
        body["password"] = password
    if totp_secret:
        body["totp_secret"] = totp_secret
    return _api(url, "POST", "/api/v1/auth/admin-login", body=body)


def signup_request(url: str, username: str, email: str, password: str,
                   totp_secret: Optional[str] = None,
                   totp_code: Optional[str] = None) -> Dict[str, Any]:
    body: Dict[str, Any] = {"username": username, "email": email, "password": password}
    if totp_secret:
        body["totp_secret"] = totp_secret
    if totp_code:
        body["totp_code"] = totp_code
    return _api(url, "POST", "/api/v1/auth/signup", body=body)


def logout_request(url: str, session_token: str, held_token: Optional[str] = None) -> Dict[str, Any]:
    body: Dict[str, Any] = {}
    if held_token:
        body["held_token"] = held_token
    return _api(url, "POST", "/api/v1/auth/logout", token=session_token, body=body)


def refresh_request(url: str, held_token: str) -> Dict[str, Any]:
    return _api(url, "POST", "/api/v1/auth/refresh", body={"held_token": held_token})


def rotate_master_request(url: str, current: str, new: str) -> Dict[str, Any]:
    return _api(url, "POST", "/api/v1/auth/rotate-master",
                body={"current_master_token": current, "new_master_token": new})


def me_request(url: str, session_token: str) -> Dict[str, Any]:
    return _api(url, "GET", "/api/v1/auth/me", token=session_token)


# --- Agent tokens (server-registered) -------------------------------------

def mint_agent_token(url: str, session_token: str, name: str) -> Dict[str, Any]:
    return _api(url, "POST", "/api/v1/tokens", token=session_token, body={"name": name})


def list_agent_tokens(url: str, session_token: str) -> List[Dict[str, Any]]:
    return _api(url, "GET", "/api/v1/tokens", token=session_token).get("tokens", [])


def revoke_agent_token(url: str, session_token: str, name: str) -> Dict[str, Any]:
    return _api(url, "DELETE", f"/api/v1/tokens/{name}", token=session_token)


# --- Sessions --------------------------------------------------------------

def list_sessions(url: str, session_token: str, all_sessions: bool = False) -> List[Dict[str, Any]]:
    path = "/api/v1/sessions" + ("?all_sessions=true" if all_sessions else "")
    return _api(url, "GET", path, token=session_token).get("sessions", [])


def revoke_session(url: str, session_token: str, session_id: str) -> Dict[str, Any]:
    return _api(url, "DELETE", f"/api/v1/sessions/{session_id}", token=session_token)


def revoke_all_sessions(url: str, session_token: str, all_sessions: bool = False) -> Dict[str, Any]:
    path = "/api/v1/sessions/revoke-all" + ("?all_sessions=true" if all_sessions else "")
    return _api(url, "POST", path, token=session_token)


# --- Users (admin) ----------------------------------------------------------

def list_users(url: str, session_token: str) -> List[Dict[str, Any]]:
    return _api(url, "GET", "/api/v1/users", token=session_token).get("users", [])


def revoke_user(url: str, session_token: str, user_id: str) -> Dict[str, Any]:
    return _api(url, "POST", f"/api/v1/users/{user_id}/revoke", token=session_token)


# --- Signup requests (admin) ------------------------------------------------

def list_requests(url: str, session_token: str, status_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    path = "/api/v1/requests"
    if status_filter:
        path += f"?status_filter={status_filter}"
    return _api(url, "GET", path, token=session_token).get("requests", [])


def show_request(url: str, session_token: str, req_id: str) -> Dict[str, Any]:
    return _api(url, "GET", f"/api/v1/requests/{req_id}", token=session_token).get("request", {})


def approve_request(url: str, session_token: str, req_id: str) -> Dict[str, Any]:
    return _api(url, "POST", f"/api/v1/requests/{req_id}/approve", token=session_token)


def deny_request(url: str, session_token: str, req_id: str, reason: Optional[str] = None) -> Dict[str, Any]:
    body: Dict[str, Any] = {}
    if reason:
        body["reason"] = reason
    return _api(url, "POST", f"/api/v1/requests/{req_id}/deny", token=session_token, body=body)
