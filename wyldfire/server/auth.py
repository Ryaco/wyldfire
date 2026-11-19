"""Server-side authentication primitives for the users build (0.2.0).

Pure logic — no FastAPI, no database — so it is unit-testable in isolation.
Covers: token minting/hashing, argon2id passwords, TOTP enrollment and
verification, Fernet encryption of TOTP secrets at rest, and terminal QR
rendering for enrollment.

Security decisions (UPDATE_SPEC.md §1.4, all decided 2026-10-31):
- Passwords: argon2id, minimum length 12, no complexity rules.
- All tokens (user, agent, session, master): stored as SHA-256 hashes,
  never the token itself.
- TOTP secrets: encrypted at rest with a `.env` key (Fernet); they cannot
  be hashed because the server needs the secret to verify codes.
- Agent tokens: server-side hash store; no derivation from a master secret.
"""

from __future__ import annotations

import os
import secrets
from hashlib import sha256

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken
import pyotp

from wyldfire.core.totp import new_totp_secret, totp_uri, render_totp_qr

__all__ = [
    "AGENT_TOKEN_PREFIX", "SESSION_TOKEN_PREFIX", "MIN_PASSWORD_LENGTH",
    "sha256_hex", "new_agent_token", "new_session_token", "new_user_token",
    "hash_password", "verify_password", "new_totp_secret", "totp_uri",
    "verify_totp", "encrypt_totp_secret", "decrypt_totp_secret",
    "render_totp_qr", "AuthError", "AuthContext", "ensure_master_hash",
    "authenticate", "require_data_caller", "require_admin",
    "JUDGMENT_EVENT_TYPES", "is_judgment_event",
]

# Token prefixes. Sessions and agent tokens are distinguishable by prefix so
# the server can dispatch verification without trying every table.
AGENT_TOKEN_PREFIX = "wyld_at_"
SESSION_TOKEN_PREFIX = "wyld_sess_"

# Minimum password length (decided 2026-10-31). No complexity rules.
MIN_PASSWORD_LENGTH = 12

_ph = PasswordHasher()  # argon2id defaults


def sha256_hex(value: str) -> str:
    """SHA-256 hex digest of a token value. This is what is stored."""
    return sha256(value.encode("utf-8")).hexdigest()


def new_agent_token() -> str:
    """Mint an agent token value (shown once; only its hash is stored)."""
    return AGENT_TOKEN_PREFIX + secrets.token_hex(32)


def new_session_token() -> str:
    """Mint a session token value (shown once; only its hash is stored)."""
    return SESSION_TOKEN_PREFIX + secrets.token_hex(32)


def new_user_token() -> str:
    """Mint a held user token value (durable credential, renews sessions)."""
    return SESSION_TOKEN_PREFIX + secrets.token_hex(32)


def hash_password(password: str) -> str:
    """argon2id hash of a password. Raises ValueError if too short."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(
            f"password must be at least {MIN_PASSWORD_LENGTH} characters"
        )
    return _ph.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Check a password against its argon2id hash. False on any mismatch."""
    try:
        return _ph.verify(password_hash, password)
    except (VerifyMismatchError, Exception):
        return False


def verify_totp(secret: str, code: str) -> bool:
    """Verify a 6-digit TOTP code, allowing one step of clock skew either way."""
    code = str(code).strip()
    if not code.isdigit():
        return False
    try:
        return bool(pyotp.TOTP(secret).verify(code, valid_window=1))
    except Exception:
        return False


def _totp_key_path() -> Path:
    """Data-dir home for a generated TOTP encryption key."""
    from wyldfire.server import config

    return config.DATA_DIR / "totp.key"


def get_totp_fernet() -> Fernet:
    """Fernet for TOTP secrets at rest.

    Key source, in order: the ``WYLD_TOTP_KEY`` environment variable (the
    ``.env`` key the spec names), else a key generated once and kept in the
    server data dir with 0600 permissions. Either way the key lives with
    the deployment, not in the database.
    """
    env_key = os.environ.get("WYLD_TOTP_KEY", "").strip()
    if env_key:
        try:
            return Fernet(env_key.encode("utf-8"))
        except Exception as exc:
            raise RuntimeError("WYLD_TOTP_KEY is not a valid Fernet key") from exc
    key_path = _totp_key_path()
    if key_path.exists():
        return Fernet(key_path.read_bytes().strip())
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    key_path.write_bytes(key)
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass
    return Fernet(key)


def encrypt_totp_secret(secret: str) -> str:
    """Encrypt a TOTP secret for storage (Fernet, URL-safe base64 text)."""
    return get_totp_fernet().encrypt(secret.encode("utf-8")).decode("utf-8")


def decrypt_totp_secret(ciphertext: str) -> str:
    """Decrypt a stored TOTP secret. Raises ValueError on a bad key/ciphertext."""
    try:
        return get_totp_fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("stored TOTP secret cannot be decrypted") from exc


# ---------------------------------------------------------------------------
# Request authentication: who is calling, and with what kind of credential.
# The CLI is untrusted — every call is verified server-side (UPDATE_SPEC.md
# §1.4). Three credential kinds arrive as Bearer tokens:
#   - session tokens (wyld_sess_... in the sessions table) — everyday use;
#   - agent tokens (wyld_at_... in the agent_tokens table) — member scope,
#     even when the owning user is an admin; judgment actions refused;
#   - the master token (raw value, no prefix) — login and rotation only.
# ---------------------------------------------------------------------------

from dataclasses import dataclass
from typing import Optional


class AuthError(Exception):
    """Authentication/authorization failure with an HTTP status + detail."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass
class AuthContext:
    kind: str  # "session" | "agent" | "master"
    user_id: Optional[str]
    username: str
    email: str
    role: str  # effective role: agent tokens are always "member"
    is_agent: bool = False
    session_id: Optional[str] = None
    agent_token_id: Optional[str] = None
    agent_name: Optional[str] = None
    user_token_id: Optional[str] = None


def ensure_master_hash() -> Optional[str]:
    """First-boot migration: hash the env master token into the database.

    The token value is unchanged; the database becomes authoritative from
    then on (UPDATE_SPEC.md §1.6c). Returns the stored hash or None when
    no master token is configured anywhere.
    """
    from wyldfire.server import db

    stored = db.get_master_hash()
    if stored:
        return stored
    env_token = os.environ.get("WYLD_SERVER_TOKEN", "").strip()
    if not env_token:
        return None
    hashed = sha256_hex(env_token)
    db.set_master_hash(hashed)
    return hashed


def _find_first_admin():
    """The bootstrap admin: earliest-created user with role admin."""
    from wyldfire.server import db

    for user in db.list_users():
        if user["role"] == "admin" and user["status"] == "active":
            return user
    return None


def authenticate(authorization: Optional[str]) -> AuthContext:
    """Verify a Bearer token and return who is calling.

    Raises AuthError on any failure. Session use slides the expiry
    (90 days, sliding) and records last use; agent-token use records
    last use. The master token authenticates as admin but is refused on
    data endpoints by the callers (see require_data_caller).
    """
    from wyldfire.server import db

    if not authorization:
        raise AuthError(401, "Missing Authorization header")
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        raise AuthError(401, "Invalid Authorization header scheme")
    token = authorization[len(prefix):].strip()
    if not token:
        raise AuthError(401, "Missing Authorization header")

    if token.startswith(AGENT_TOKEN_PREFIX):
        row = db.get_agent_token_by_hash(sha256_hex(token))
        if row is None or row["revoked"]:
            raise AuthError(401, "Invalid agent token")
        user = db.get_user_by_id(row["user_id"])
        if user is None or user["status"] == "revoked":
            raise AuthError(403, "account revoked (ask the admin)")
        if user["status"] != "active":
            raise AuthError(403, "account pending approval (try again after approval)")
        db.touch_agent_token(row["id"])
        return AuthContext(
            kind="agent",
            user_id=user["id"],
            username=user["username"],
            email=user["email"],
            role="member",  # agent tokens are capped at member scope
            is_agent=True,
            agent_token_id=row["id"],
            agent_name=row["name"],
        )

    if token.startswith(SESSION_TOKEN_PREFIX):
        row = db.get_session_by_hash(sha256_hex(token))
        if row is None or row["revoked"]:
            raise AuthError(401, "Invalid session (log in again)")
        if db._is_expired(row["expires_at"]):
            raise AuthError(401, "session expired (log in again)")
        user = db.get_user_by_id(row["user_id"])
        if user is None or user["status"] == "revoked":
            raise AuthError(403, "account revoked (ask the admin)")
        if user["status"] != "active":
            raise AuthError(403, "account pending approval (try again after approval)")
        db.touch_session(row["id"])
        return AuthContext(
            kind="session",
            user_id=user["id"],
            username=user["username"],
            email=user["email"],
            role=user["role"],
            session_id=row["id"],
            user_token_id=row["user_token_id"],
        )

    # Raw value: the master token.
    stored = ensure_master_hash()
    if stored is None or sha256_hex(token) != stored:
        raise AuthError(403, "Invalid API token")
    admin = _find_first_admin()
    return AuthContext(
        kind="master",
        user_id=admin["id"] if admin else None,
        username=admin["username"] if admin else "admin",
        email=admin["email"] if admin else "",
        role="admin",
    )


def require_data_caller(ctx: AuthContext) -> AuthContext:
    """Data endpoints (projects, events) take sessions or agent tokens only.

    The master token is for login and rotation; everyday requests carry
    the session (UPDATE_SPEC.md §1.4).
    """
    if ctx.kind == "master":
        raise AuthError(
            401,
            "master token is for login only — log in to get a session",
        )
    return ctx


def require_admin(ctx: AuthContext) -> AuthContext:
    """Admin work needs valid admin auth: an admin session or the master token."""
    if ctx.kind == "master":
        return ctx
    if ctx.kind == "session" and ctx.role == "admin":
        return ctx
    raise AuthError(403, "admin access required (log in as admin)")


# Event types an agent token may never record server-side (UPDATE_SPEC.md
# §1.2 + §3). The client also guards these locally, but the CLI is
# untrusted, so the server is the enforcement point. A refused event is
# reported in the sync response as a rejection, never silently dropped.
JUDGMENT_EVENT_TYPES = frozenset({
    # Gate verdicts (pass and hold are both verdicts).
    "gate.part1.passed", "gate.part1.held",
    "gate.part2.passed", "gate.part2.held",
    # Attestations, waivers, exclusions.
    "gate.scope_attested", "gate.check_waived", "stoke.excluded",
    "gate.slice_done", "gate.plan_done",
    # Crowning a flame, shipping a fire.
    "flame.crowned", "fire.shipped",
    # Smoke diagnosis / clearing.
    "smoke.identified", "smoke.cleared",
})


def is_judgment_event(event_type: str, payload: dict) -> bool:
    """True when an agent token must not record this event.

    Scoring (a stoke that carries metrics) is a judgment call too, but
    only when metrics are present — a plain stoke note from an agent is
    bookkeeping and is allowed.
    """
    if event_type in JUDGMENT_EVENT_TYPES:
        return True
    if event_type == "stoke.logged":
        metrics = payload.get("metrics") if isinstance(payload, dict) else None
        if metrics:
            return True
    return False
