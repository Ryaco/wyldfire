"""Smoke service: issue tracking, transitions, and learning database."""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import sqlite3

from wyldfire.core.project import Project
from wyldfire.core.config import load_registry
from wyldfire.core.events import create_event
from wyldfire.core.text_utils import resolve_text_or_file
from wyldfire.core.exceptions import WyldError
from wyldfire.core.constants import (
    SMOKE_STAGED,
    SMOKE_OPEN,
    SMOKE_IDENTIFIED,
    SMOKE_CLEARED,
    SMOKE_STATUSES,
)


def parse_context(ctx_str: str) -> Tuple[str, str]:
    """Parse context string like 'flame/wildfire', 'fire/game', 'gate', 'production'."""
    s = ctx_str.strip()
    if "/" in s:
        kind, ref = s.split("/", 1)
        kind = kind.lower().strip()
        ref = ref.strip()
        if kind not in ("flame", "fire"):
            raise WyldError(f"invalid context '{ctx_str}'", "expected flame/<name>, fire/<name>, gate, or production")
        return kind, ref
    kind = s.lower()
    if kind not in ("gate", "production"):
        raise WyldError(f"invalid context '{ctx_str}'", "expected flame/<name>, fire/<name>, gate, or production")
    return kind, ""


def log_smoke(
    project: Project,
    title: str,
    on: str,
    severity: int = 2,
    tags: str = "",
    notes: Optional[str] = None,
    notes_file: Optional[Path] = None,
) -> Dict[str, Any]:
    title = title.strip()
    if not title:
        raise WyldError("smoke title cannot be empty", "provide a descriptive title")

    if severity not in (1, 2, 3):
        raise WyldError(f"invalid severity {severity}", "severity must be 1 (nit), 2 (problem), or 3 (critical)")

    ctx_kind, ctx_ref = parse_context(on)
    clean_tags = ",".join(t.strip() for t in tags.split(",") if t.strip())

    final_notes = resolve_text_or_file(notes, notes_file, "notes", required=False, default="")
    transition_note = final_notes if final_notes else title

    event = create_event(
        "smoke.opened",
        {
            "title": title,
            "context_kind": ctx_kind,
            "context_ref": ctx_ref,
            "severity": severity,
            "tags": clean_tags,
            "note": transition_note,
            "notes": final_notes,
        },
    )
    project.store.append_event(event)

    # Get the inserted smoke row id
    with project.get_connection() as conn:
        row = conn.execute("SELECT id FROM smoke ORDER BY id DESC LIMIT 1").fetchone()
        sm_id = row["id"] if row else 1

    return {
        "id": sm_id,
        "title": title,
        "context": on,
        "severity": severity,
        "status": SMOKE_OPEN,
        "tags": clean_tags,
        "notes": final_notes,
    }


def stage_smoke(
    project: Project,
    title: str,
    on: str,
    severity: int = 2,
    tags: str = "",
    notes: Optional[str] = None,
    notes_file: Optional[Path] = None,
) -> Dict[str, Any]:
    title = title.strip()
    if not title:
        raise WyldError("smoke title cannot be empty", "provide a descriptive title")

    if severity not in (1, 2, 3):
        raise WyldError(f"invalid severity {severity}", "severity must be 1 (nit), 2 (problem), or 3 (critical)")

    ctx_kind, ctx_ref = parse_context(on)
    if ctx_kind not in ("flame", "fire"):
        raise WyldError(
            f"cannot stage smoke on '{on}'",
            "staging is only supported on flame/<name> or fire/<name>; use 'wyld smoke log' for gate/production",
        )

    clean_tags = ",".join(t.strip() for t in tags.split(",") if t.strip())
    final_notes = resolve_text_or_file(notes, notes_file, "notes", required=False, default="")

    event = create_event(
        "smoke.staged",
        {
            "title": title,
            "context_kind": ctx_kind,
            "context_ref": ctx_ref,
            "severity": severity,
            "tags": clean_tags,
            "notes": final_notes,
        },
    )
    project.store.append_event(event)

    with project.get_connection() as conn:
        row = conn.execute("SELECT id FROM smoke ORDER BY id DESC LIMIT 1").fetchone()
        sm_id = row["id"] if row else 1

    return {
        "id": sm_id,
        "title": title,
        "context": on,
        "severity": severity,
        "status": SMOKE_STAGED,
        "tags": clean_tags,
    }


def unstage_smoke(project: Project, smoke_id: int) -> Dict[str, Any]:
    with project.get_connection() as conn:
        row = conn.execute("SELECT * FROM smoke WHERE id = ?", (smoke_id,)).fetchone()
        if not row:
            raise WyldError(f"smoke #{smoke_id} not found", "run 'wyld smoke staged' to see staged items")
        if row["status"] != SMOKE_STAGED:
            raise WyldError(f"smoke #{smoke_id} is not staged (current status: {row['status']})", "only staged smoke can be unstaged")
        smoke_dict = dict(row)

    event = create_event("smoke.unstaged", {"id": smoke_id})
    project.store.append_event(event)
    return smoke_dict


def identify_smoke(
    project: Project,
    smoke_id: int,
    note: Optional[str] = None,
    notes_file: Optional[Path] = None,
) -> Dict[str, Any]:
    final_notes = resolve_text_or_file(note, notes_file, "notes", required=True)

    with project.get_connection() as conn:
        row = conn.execute("SELECT * FROM smoke WHERE id = ?", (smoke_id,)).fetchone()
        if not row:
            raise WyldError(f"smoke #{smoke_id} not found", "check 'wyld smoke list'")
        if row["status"] == SMOKE_STAGED:
            raise WyldError(
                f"smoke #{smoke_id} is still staged",
                "commit it via a stoke first, or use 'wyld smoke log'"
            )

    event = create_event("smoke.identified", {"id": smoke_id, "note": final_notes})
    project.store.append_event(event)
    return {"id": smoke_id, "status": SMOKE_IDENTIFIED, "note": final_notes}


def clear_smoke(
    project: Project,
    smoke_id: int,
    note: Optional[str] = None,
    notes_file: Optional[Path] = None,
) -> Dict[str, Any]:
    final_notes = resolve_text_or_file(note, notes_file, "notes", required=True)

    with project.get_connection() as conn:
        row = conn.execute("SELECT * FROM smoke WHERE id = ?", (smoke_id,)).fetchone()
        if not row:
            raise WyldError(f"smoke #{smoke_id} not found", "check 'wyld smoke list'")

    event = create_event("smoke.cleared", {"id": smoke_id, "note": final_notes})
    project.store.append_event(event)
    return {"id": smoke_id, "status": SMOKE_CLEARED, "note": final_notes}


def tag_smoke(project: Project, smoke_id: int, tags: str) -> Dict[str, Any]:
    clean_tags = ",".join(t.strip() for t in tags.split(",") if t.strip())
    with project.get_connection() as conn:
        row = conn.execute("SELECT * FROM smoke WHERE id = ?", (smoke_id,)).fetchone()
        if not row:
            raise WyldError(f"smoke #{smoke_id} not found", "check 'wyld smoke list'")

    event = create_event("smoke.tagged", {"id": smoke_id, "tags": clean_tags})
    project.store.append_event(event)
    return {"id": smoke_id, "tags": clean_tags}


def get_smoke(project: Project, smoke_id: int) -> Dict[str, Any]:
    with project.get_connection() as conn:
        row = conn.execute("SELECT * FROM smoke WHERE id = ?", (smoke_id,)).fetchone()
        if not row:
            raise WyldError(f"smoke #{smoke_id} not found", "check 'wyld smoke list'")
        data = dict(row)
        t_rows = conn.execute(
            "SELECT to_status, note, created_at FROM smoke_transitions WHERE smoke_id = ? ORDER BY id ASC",
            (smoke_id,),
        ).fetchall()
        data["transitions"] = [dict(t) for t in t_rows]
        return data


def list_smoke(
    project: Project,
    on: Optional[str] = None,
    status: Optional[str] = None,
    severity: Optional[int] = None,
) -> List[Dict[str, Any]]:
    query = "SELECT * FROM smoke WHERE 1=1"
    params: List[Any] = []

    if on:
        kind, ref = parse_context(on)
        query += " AND context_kind = ? AND context_ref = ?"
        params.extend([kind, ref])

    if status:
        query += " AND status = ?"
        params.append(status)

    if severity is not None:
        query += " AND severity = ?"
        params.append(severity)

    query += " ORDER BY id ASC"

    with project.get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def search_smoke(
    project: Project,
    tags: str,
    status: Optional[str] = "cleared",
    all_projects: bool = False,
) -> Tuple[List[Dict[str, Any]], bool]:
    """Search cleared smoke by tags.
    
    Returns (results, widened) where widened indicates whether it widened to all local projects.
    """
    search_tags = [t.strip().lower() for t in tags.split(",") if t.strip()]
    if not search_tags:
        raise WyldError("no search tags specified", "provide --tags 'a,b'")

    def _search_in_db(db_path: Path, proj_name: str) -> List[Dict[str, Any]]:
        if not db_path.exists():
            return []
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM smoke").fetchall()
            matched = []
            for r in rows:
                if status and r["status"] != status:
                    continue
                row_tags = [t.strip().lower() for t in r["tags"].split(",") if t.strip()]
                # Check if any search tag matches
                if any(st in row_tags for st in search_tags):
                    d = dict(r)
                    d["project_name"] = proj_name
                    # Fetch transitions
                    t_rows = conn.execute(
                        "SELECT to_status, note, created_at FROM smoke_transitions WHERE smoke_id = ? ORDER BY id ASC",
                        (r["id"],),
                    ).fetchall()
                    d["transitions"] = [dict(t) for t in t_rows]
                    # Extract diagnosis (identified) and fix (cleared)
                    diag = ""
                    fix = ""
                    for tr in d["transitions"]:
                        if tr["to_status"] == SMOKE_IDENTIFIED:
                            diag = tr["note"]
                        elif tr["to_status"] == SMOKE_CLEARED:
                            fix = tr["note"]
                    d["diagnosis"] = diag
                    d["fix"] = fix
                    matched.append(d)
            conn.close()
            return matched
        except Exception:
            return []

    # 1. Search in current project first, unless all_projects is set
    local_results: List[Dict[str, Any]] = []
    if not all_projects:
        local_results = _search_in_db(project.db_path, project.name)
        if local_results:
            return local_results, False

    # 2. Widened search
    registry = load_registry()
    widened_results: List[Dict[str, Any]] = []
    for proj_path_str, proj_name in registry.items():
        p_db = Path(proj_path_str) / ".wyld" / "wyld.db"
        widened_results.extend(_search_in_db(p_db, proj_name))

    return widened_results, not all_projects
