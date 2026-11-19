"""Server-side SQLite storage for projects and synced events."""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import json
import sqlite3

from wyldfire.core.time_utils import utc_iso_now
from wyldfire.server import config


def get_server_db() -> sqlite3.Connection:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(config.DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn


def init_server_db() -> None:
    with get_server_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS server_projects (
            project_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS server_events (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            ts TEXT NOT NULL,
            actor TEXT NOT NULL,
            type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        -- Users build (0.2.0): accounts, sessions, agent tokens, requests.
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'member',
            status TEXT NOT NULL DEFAULT 'active',
            totp_secret_enc TEXT,
            totp_enrolled INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            approved_at TEXT,
            revoked_at TEXT
        );

        CREATE TABLE IF NOT EXISTS user_tokens (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            last_used_at TEXT,
            revoked INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            user_token_id TEXT,
            token_hash TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            last_used_at TEXT,
            revoked INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS agent_tokens (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            name TEXT NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            last_used_at TEXT,
            revoked INTEGER NOT NULL DEFAULT 0,
            UNIQUE(user_id, name)
        );

        CREATE TABLE IF NOT EXISTS signup_requests (
            id TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            email TEXT NOT NULL,
            password_hash TEXT,
            totp_secret_enc TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            requested_at TEXT NOT NULL,
            decided_at TEXT,
            reason TEXT
        );

        CREATE TABLE IF NOT EXISTS project_members (
            project_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'member',
            added_at TEXT NOT NULL,
            PRIMARY KEY (project_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS rate_limits (
            key TEXT PRIMARY KEY,
            failures INTEGER NOT NULL DEFAULT 0,
            locked_until TEXT,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS master_token (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            token_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            rotated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS master_token_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            old_hash_prefix TEXT NOT NULL,
            rotated_at TEXT NOT NULL
        );
        """)
        # Migration: pre-users projects have no owner. Added idempotently.
        cols = [r[1] for r in conn.execute("PRAGMA table_info(server_projects)")]
        if "owner_id" not in cols:
            conn.execute("ALTER TABLE server_projects ADD COLUMN owner_id TEXT")
        # Migration: pre-users events have no actor email. Added idempotently.
        cols = [r[1] for r in conn.execute("PRAGMA table_info(server_events)")]
        if "actor_email" not in cols:
            conn.execute("ALTER TABLE server_events ADD COLUMN actor_email TEXT")
        conn.commit()


def get_or_create_project(project_id: str, name: str, owner_id: Optional[str] = None) -> Dict[str, Any]:
    init_server_db()
    with get_server_db() as conn:
        row = conn.execute("SELECT * FROM server_projects WHERE project_id = ?", (project_id,)).fetchone()
        if row:
            return dict(row)
        now = utc_iso_now()
        conn.execute(
            "INSERT INTO server_projects (project_id, name, created_at, owner_id) VALUES (?, ?, ?, ?)",
            (project_id, name, now, owner_id),
        )
        if owner_id:
            conn.execute(
                "INSERT OR IGNORE INTO project_members (project_id, user_id, role, added_at) VALUES (?, ?, 'owner', ?)",
                (project_id, owner_id, now),
            )
        conn.commit()
        return {"project_id": project_id, "name": name, "created_at": now, "owner_id": owner_id}


def save_events(project_id: str, events: List[Dict[str, Any]]) -> Tuple[int, int]:
    init_server_db()
    accepted = 0
    skipped = 0
    now = utc_iso_now()

    with get_server_db() as conn:
        for ev in events:
            ev_id = str(ev["id"])
            existing = conn.execute("SELECT 1 FROM server_events WHERE id = ?", (ev_id,)).fetchone()
            if existing:
                skipped += 1
                continue

            conn.execute(
                """
                INSERT INTO server_events (id, project_id, ts, actor, actor_email, type, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ev_id,
                    project_id,
                    str(ev["ts"]),
                    str(ev.get("actor", "dev")),
                    str(ev.get("actor_email", "")),
                    str(ev["type"]),
                    json.dumps(ev.get("payload", {})),
                    now,
                ),
            )
            accepted += 1
        conn.commit()

    return accepted, skipped


def get_events(project_id: str, since: Optional[str] = None) -> List[Dict[str, Any]]:
    init_server_db()
    with get_server_db() as conn:
        query = "SELECT * FROM server_events WHERE project_id = ?"
        params = [project_id]

        if since:
            query += " AND ts > ?"
            params.append(since)

        query += " ORDER BY ts ASC, id ASC"

        rows = conn.execute(query, params).fetchall()
        result = []
        for r in rows:
            try:
                payload = json.loads(r["payload_json"])
            except Exception:
                payload = {}
            result.append({
                "id": r["id"],
                "project_id": r["project_id"],
                "ts": r["ts"],
                "actor": r["actor"],
                "actor_email": r["actor_email"] if "actor_email" in r.keys() else "",
                "type": r["type"],
                "payload": payload,
            })
        return result


# ---------------------------------------------------------------------------
# Users build (0.2.0): accounts, tokens, sessions, requests, membership.
# ---------------------------------------------------------------------------

import uuid as _uuid
from datetime import datetime as _datetime, timedelta as _timedelta, timezone as _timezone


def _now_iso() -> str:
    return utc_iso_now()


def _parse_iso(value: Optional[str]) -> Optional[_datetime]:
    if not value:
        return None
    try:
        return _datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _is_expired(expires_at: Optional[str]) -> bool:
    exp = _parse_iso(expires_at)
    if exp is None:
        return True
    now = _datetime.now(_timezone.utc)
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=_timezone.utc)
    return now >= exp


# --- Users ---------------------------------------------------------------

def create_user(username: str, email: str, password_hash: str, role: str = "member",
                status: str = "active", totp_secret_enc: Optional[str] = None) -> Dict[str, Any]:
    init_server_db()
    user_id = str(_uuid.uuid4())
    now = _now_iso()
    with get_server_db() as conn:
        conn.execute(
            """INSERT INTO users (id, username, email, password_hash, role, status,
                   totp_secret_enc, totp_enrolled, created_at, approved_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, username, email, password_hash, role, status,
             totp_secret_enc, 1 if totp_secret_enc else 0, now,
             now if status == "active" else None),
        )
        conn.commit()
    return get_user_by_id(user_id)  # type: ignore[return-value]


def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    init_server_db()
    with get_server_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return dict(row) if row else None


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    init_server_db()
    with get_server_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    init_server_db()
    with get_server_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


def count_users() -> int:
    init_server_db()
    with get_server_db() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()
        return int(row["n"])


def list_users() -> List[Dict[str, Any]]:
    init_server_db()
    with get_server_db() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY created_at ASC").fetchall()
        return [dict(r) for r in rows]


def set_user_totp(user_id: str, totp_secret_enc: str) -> None:
    init_server_db()
    with get_server_db() as conn:
        conn.execute(
            "UPDATE users SET totp_secret_enc = ?, totp_enrolled = 1 WHERE id = ?",
            (totp_secret_enc, user_id),
        )
        conn.commit()


def revoke_user(user_id: str) -> Dict[str, int]:
    """Revoke a user and cascade: agent tokens, sessions, held user tokens.

    Past events stay in history untouched; attribution is intact. Future
    logins are refused because status becomes 'revoked'.
    """
    init_server_db()
    now = _now_iso()
    with get_server_db() as conn:
        agents = conn.execute(
            "UPDATE agent_tokens SET revoked = 1 WHERE user_id = ? AND revoked = 0",
            (user_id,),
        ).rowcount
        sessions = conn.execute(
            "UPDATE sessions SET revoked = 1 WHERE user_id = ? AND revoked = 0",
            (user_id,),
        ).rowcount
        held = conn.execute(
            "UPDATE user_tokens SET revoked = 1 WHERE user_id = ? AND revoked = 0",
            (user_id,),
        ).rowcount
        conn.execute(
            "UPDATE users SET status = 'revoked', revoked_at = ? WHERE id = ?",
            (now, user_id),
        )
        conn.commit()
    return {"agent_tokens_revoked": agents, "sessions_revoked": sessions,
            "user_tokens_revoked": held}


def backfill_project_owners(admin_user_id: str) -> int:
    """Migration: pre-users projects get the bootstrap admin as Owner."""
    init_server_db()
    now = _now_iso()
    with get_server_db() as conn:
        rows = conn.execute(
            "SELECT project_id FROM server_projects WHERE owner_id IS NULL"
        ).fetchall()
        for r in rows:
            conn.execute(
                "UPDATE server_projects SET owner_id = ? WHERE project_id = ?",
                (admin_user_id, r["project_id"]),
            )
            conn.execute(
                "INSERT OR IGNORE INTO project_members (project_id, user_id, role, added_at)"
                " VALUES (?, ?, 'owner', ?)",
                (r["project_id"], admin_user_id, now),
            )
        conn.commit()
        return len(rows)


# --- Held user tokens (durable credential; renews sessions) ---------------

def create_user_token(user_id: str, token_hash: str) -> Dict[str, Any]:
    init_server_db()
    token_id = str(_uuid.uuid4())
    now = _now_iso()
    with get_server_db() as conn:
        conn.execute(
            "INSERT INTO user_tokens (id, user_id, token_hash, created_at) VALUES (?, ?, ?, ?)",
            (token_id, user_id, token_hash, now),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM user_tokens WHERE id = ?", (token_id,)).fetchone()
        return dict(row)


def get_user_token_by_hash(token_hash: str) -> Optional[Dict[str, Any]]:
    init_server_db()
    with get_server_db() as conn:
        row = conn.execute(
            "SELECT * FROM user_tokens WHERE token_hash = ?", (token_hash,)
        ).fetchone()
        return dict(row) if row else None


def touch_user_token(token_id: str) -> None:
    init_server_db()
    with get_server_db() as conn:
        conn.execute(
            "UPDATE user_tokens SET last_used_at = ? WHERE id = ?", (_now_iso(), token_id)
        )
        conn.commit()


def revoke_user_token(token_id: str) -> None:
    init_server_db()
    with get_server_db() as conn:
        conn.execute("UPDATE user_tokens SET revoked = 1 WHERE id = ?", (token_id,))
        conn.commit()


def revoke_all_user_tokens(user_id: str) -> int:
    init_server_db()
    with get_server_db() as conn:
        n = conn.execute(
            "UPDATE user_tokens SET revoked = 1 WHERE user_id = ? AND revoked = 0",
            (user_id,),
        ).rowcount
        conn.commit()
        return n


# --- Sessions (90 days, sliding) ------------------------------------------

SESSION_DAYS = 90


def session_expiry_from_now() -> str:
    exp = _datetime.now(_timezone.utc) + _timedelta(days=SESSION_DAYS)
    return exp.strftime("%Y-%m-%dT%H:%M:%SZ")


def create_session(user_id: str, token_hash: str, user_token_id: Optional[str] = None) -> Dict[str, Any]:
    init_server_db()
    session_id = str(_uuid.uuid4())
    now = _now_iso()
    with get_server_db() as conn:
        conn.execute(
            """INSERT INTO sessions (id, user_id, user_token_id, token_hash, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, user_id, user_token_id, token_hash, now, session_expiry_from_now()),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return dict(row)


def get_session_by_hash(token_hash: str) -> Optional[Dict[str, Any]]:
    init_server_db()
    with get_server_db() as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE token_hash = ?", (token_hash,)
        ).fetchone()
        return dict(row) if row else None


def touch_session(session_id: str) -> None:
    """Slide the session expiry forward 90 days and record last use."""
    init_server_db()
    with get_server_db() as conn:
        conn.execute(
            "UPDATE sessions SET last_used_at = ?, expires_at = ? WHERE id = ?",
            (_now_iso(), session_expiry_from_now(), session_id),
        )
        conn.commit()


def revoke_session(session_id: str) -> None:
    init_server_db()
    with get_server_db() as conn:
        conn.execute("UPDATE sessions SET revoked = 1 WHERE id = ?", (session_id,))
        conn.commit()


def revoke_all_sessions(user_id: str) -> int:
    init_server_db()
    with get_server_db() as conn:
        n = conn.execute(
            "UPDATE sessions SET revoked = 1 WHERE user_id = ? AND revoked = 0",
            (user_id,),
        ).rowcount
        conn.commit()
        return n


def list_sessions(user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    init_server_db()
    with get_server_db() as conn:
        if user_id:
            rows = conn.execute(
                "SELECT * FROM sessions WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM sessions ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]


# --- Agent tokens (no expiry by default; revocable) -----------------------

def create_agent_token(user_id: str, name: str, token_hash: str) -> Dict[str, Any]:
    init_server_db()
    token_id = str(_uuid.uuid4())
    now = _now_iso()
    with get_server_db() as conn:
        conn.execute(
            "INSERT INTO agent_tokens (id, user_id, name, token_hash, created_at) VALUES (?, ?, ?, ?, ?)",
            (token_id, user_id, name, token_hash, now),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM agent_tokens WHERE id = ?", (token_id,)).fetchone()
        return dict(row)


def get_agent_token_by_hash(token_hash: str) -> Optional[Dict[str, Any]]:
    init_server_db()
    with get_server_db() as conn:
        row = conn.execute(
            "SELECT * FROM agent_tokens WHERE token_hash = ?", (token_hash,)
        ).fetchone()
        return dict(row) if row else None


def get_agent_token_by_name(user_id: str, name: str) -> Optional[Dict[str, Any]]:
    init_server_db()
    with get_server_db() as conn:
        row = conn.execute(
            "SELECT * FROM agent_tokens WHERE user_id = ? AND name = ?", (user_id, name)
        ).fetchone()
        return dict(row) if row else None


def list_agent_tokens(user_id: str) -> List[Dict[str, Any]]:
    init_server_db()
    with get_server_db() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_tokens WHERE user_id = ? ORDER BY created_at ASC",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def touch_agent_token(token_id: str) -> None:
    init_server_db()
    with get_server_db() as conn:
        conn.execute(
            "UPDATE agent_tokens SET last_used_at = ? WHERE id = ?", (_now_iso(), token_id)
        )
        conn.commit()


def revoke_agent_token(token_id: str) -> None:
    init_server_db()
    with get_server_db() as conn:
        conn.execute("UPDATE agent_tokens SET revoked = 1 WHERE id = ?", (token_id,))
        conn.commit()


def revoke_all_agent_tokens(user_id: str) -> int:
    init_server_db()
    with get_server_db() as conn:
        n = conn.execute(
            "UPDATE agent_tokens SET revoked = 1 WHERE user_id = ? AND revoked = 0",
            (user_id,),
        ).rowcount
        conn.commit()
        return n


# --- Signup requests ------------------------------------------------------

def create_signup_request(username: str, email: str, password_hash: str,
                          totp_secret_enc: Optional[str] = None) -> Dict[str, Any]:
    init_server_db()
    req_id = str(_uuid.uuid4())
    now = _now_iso()
    with get_server_db() as conn:
        conn.execute(
            """INSERT INTO signup_requests (id, username, email, password_hash,
                   totp_secret_enc, status, requested_at)
               VALUES (?, ?, ?, ?, ?, 'open', ?)""",
            (req_id, username, email, password_hash, totp_secret_enc, now),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM signup_requests WHERE id = ?", (req_id,)).fetchone()
        return dict(row)


def get_signup_request(req_id: str) -> Optional[Dict[str, Any]]:
    init_server_db()
    with get_server_db() as conn:
        row = conn.execute("SELECT * FROM signup_requests WHERE id = ?", (req_id,)).fetchone()
        return dict(row) if row else None


def list_signup_requests(status: Optional[str] = None) -> List[Dict[str, Any]]:
    init_server_db()
    with get_server_db() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM signup_requests WHERE status = ? ORDER BY requested_at ASC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM signup_requests ORDER BY requested_at ASC"
            ).fetchall()
        return [dict(r) for r in rows]


def decide_signup_request(req_id: str, status: str, reason: Optional[str] = None) -> None:
    """Mark a request approved/denied. On denial, the pending account's
    password hash and TOTP secret are deleted (spec §3)."""
    init_server_db()
    now = _now_iso()
    with get_server_db() as conn:
        if status == "denied":
            conn.execute(
                """UPDATE signup_requests SET status = 'denied', decided_at = ?, reason = ?,
                       password_hash = NULL, totp_secret_enc = NULL WHERE id = ?""",
                (now, reason, req_id),
            )
        else:
            conn.execute(
                "UPDATE signup_requests SET status = ?, decided_at = ?, reason = ? WHERE id = ?",
                (status, now, reason, req_id),
            )
        conn.commit()


# --- Project membership ---------------------------------------------------

def add_member(project_id: str, user_id: str, role: str = "member") -> None:
    init_server_db()
    with get_server_db() as conn:
        conn.execute(
            """INSERT INTO project_members (project_id, user_id, role, added_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(project_id, user_id) DO UPDATE SET role = excluded.role""",
            (project_id, user_id, role, _now_iso()),
        )
        conn.commit()


def get_member_role(project_id: str, user_id: str) -> Optional[str]:
    init_server_db()
    with get_server_db() as conn:
        row = conn.execute(
            "SELECT role FROM project_members WHERE project_id = ? AND user_id = ?",
            (project_id, user_id),
        ).fetchone()
        return row["role"] if row else None


def list_members(project_id: str) -> List[Dict[str, Any]]:
    init_server_db()
    with get_server_db() as conn:
        rows = conn.execute(
            """SELECT pm.user_id, pm.role, pm.added_at, u.username, u.email
               FROM project_members pm JOIN users u ON u.id = pm.user_id
               WHERE pm.project_id = ? ORDER BY pm.added_at ASC""",
            (project_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def list_projects() -> List[Dict[str, Any]]:
    """All server projects (visible to any server member; joining is gated)."""
    init_server_db()
    with get_server_db() as conn:
        rows = conn.execute(
            "SELECT * FROM server_projects ORDER BY created_at ASC"
        ).fetchall()
        return [dict(r) for r in rows]


# --- Rate limiting (5 failed attempts -> 15-minute lockout) ----------------

LOCKOUT_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


def is_locked(key: str) -> bool:
    init_server_db()
    with get_server_db() as conn:
        row = conn.execute(
            "SELECT locked_until FROM rate_limits WHERE key = ?", (key,)
        ).fetchone()
        if not row or not row["locked_until"]:
            return False
        until = _parse_iso(row["locked_until"])
        if until is None:
            return False
        now = _datetime.now(_timezone.utc)
        if until.tzinfo is None:
            until = until.replace(tzinfo=_timezone.utc)
        return now < until


def record_failed_attempt(key: str, max_attempts: int = LOCKOUT_ATTEMPTS,
                          lockout_minutes: int = LOCKOUT_MINUTES) -> bool:
    """Record a failure; returns True if this failure triggered a lockout."""
    init_server_db()
    now = _now_iso()
    with get_server_db() as conn:
        row = conn.execute(
            "SELECT failures, locked_until FROM rate_limits WHERE key = ?", (key,)
        ).fetchone()
        failures = row["failures"] if row else 0
        if row and row["locked_until"]:
            until = _parse_iso(row["locked_until"])
            if until is not None:
                now_dt = _datetime.now(_timezone.utc)
                if until.tzinfo is None:
                    until = until.replace(tzinfo=_timezone.utc)
                if now_dt >= until:
                    # Lockout expired: fresh window, not a permanent lock.
                    failures = 0
        failures += 1
        locked_until = None
        if failures >= max_attempts:
            locked_until = (
                _datetime.now(_timezone.utc) + _timedelta(minutes=lockout_minutes)
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute(
            """INSERT INTO rate_limits (key, failures, locked_until, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET failures = excluded.failures,
                 locked_until = excluded.locked_until, updated_at = excluded.updated_at""",
            (key, failures, locked_until, now),
        )
        conn.commit()
        return locked_until is not None


def clear_rate_limit(key: str) -> None:
    init_server_db()
    with get_server_db() as conn:
        conn.execute("DELETE FROM rate_limits WHERE key = ?", (key,))
        conn.commit()


# --- Master token ---------------------------------------------------------

def get_master_hash() -> Optional[str]:
    init_server_db()
    with get_server_db() as conn:
        row = conn.execute("SELECT token_hash FROM master_token WHERE id = 1").fetchone()
        return row["token_hash"] if row else None


def set_master_hash(token_hash: str) -> None:
    init_server_db()
    now = _now_iso()
    with get_server_db() as conn:
        conn.execute(
            """INSERT INTO master_token (id, token_hash, created_at) VALUES (1, ?, ?)
               ON CONFLICT(id) DO UPDATE SET token_hash = excluded.token_hash""",
            (token_hash, now),
        )
        conn.commit()


def rotate_master_hash(new_hash: str, old_hash_prefix: str) -> None:
    """Hard cutover: replace the hash and record the old prefix + timestamp."""
    init_server_db()
    now = _now_iso()
    with get_server_db() as conn:
        conn.execute(
            "INSERT INTO master_token_audit (old_hash_prefix, rotated_at) VALUES (?, ?)",
            (old_hash_prefix, now),
        )
        conn.execute(
            """INSERT INTO master_token (id, token_hash, created_at, rotated_at) VALUES (1, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET token_hash = excluded.token_hash,
                 rotated_at = excluded.rotated_at""",
            (new_hash, now, now),
        )
        conn.commit()


def list_master_audit() -> List[Dict[str, Any]]:
    init_server_db()
    with get_server_db() as conn:
        rows = conn.execute(
            "SELECT * FROM master_token_audit ORDER BY rotated_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
