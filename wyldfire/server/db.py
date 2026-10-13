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
        """)
        conn.commit()


def get_or_create_project(project_id: str, name: str) -> Dict[str, Any]:
    init_server_db()
    with get_server_db() as conn:
        row = conn.execute("SELECT * FROM server_projects WHERE project_id = ?", (project_id,)).fetchone()
        if row:
            return dict(row)
        now = utc_iso_now()
        conn.execute(
            "INSERT INTO server_projects (project_id, name, created_at) VALUES (?, ?, ?)",
            (project_id, name, now),
        )
        conn.commit()
        return {"project_id": project_id, "name": name, "created_at": now}


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
                INSERT INTO server_events (id, project_id, ts, actor, type, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ev_id,
                    project_id,
                    str(ev["ts"]),
                    str(ev.get("actor", "dev")),
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
                "type": r["type"],
                "payload": payload,
            })
        return result
