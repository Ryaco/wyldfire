"""Ember service: parked ideas lifecycle."""

from typing import Any, Dict, List, Optional

from wyldfire.core.project import Project
from wyldfire.core.events import create_event
from wyldfire.core.exceptions import WyldError
from wyldfire.core.constants import (
    EMBER_BANKED,
    EMBER_KINDLED,
    EMBER_DISMISSED,
    EMBER_KINDS,
)


def bank_ember(
    project: Project,
    title: str,
    note: str = "",
    kind: str = "content",
) -> Dict[str, Any]:
    title = title.strip()
    if not title:
        raise WyldError("ember title cannot be empty", "provide a title describing the parked idea")

    kind = kind.lower().strip()
    if kind not in EMBER_KINDS:
        raise WyldError(f"invalid ember kind '{kind}'", "kind must be 'content' or 'mechanic'")

    event = create_event(
        "ember.banked",
        {"title": title, "note": note, "kind": kind},
    )
    project.store.append_event(event)

    with project.get_connection() as conn:
        row = conn.execute("SELECT id FROM embers ORDER BY id DESC LIMIT 1").fetchone()
        em_id = row["id"] if row else 1

    return {
        "id": em_id,
        "title": title,
        "note": note,
        "kind": kind,
        "state": EMBER_BANKED,
    }


def list_embers(
    project: Project,
    kind: Optional[str] = None,
    state: Optional[str] = None,
) -> List[Dict[str, Any]]:
    query = "SELECT * FROM embers WHERE 1=1"
    params: List[Any] = []

    if kind:
        query += " AND kind = ?"
        params.append(kind.lower())
    if state:
        query += " AND state = ?"
        params.append(state.lower())

    query += " ORDER BY id ASC"

    with project.get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def get_ember(project: Project, ember_id: int) -> Dict[str, Any]:
    with project.get_connection() as conn:
        row = conn.execute("SELECT * FROM embers WHERE id = ?", (ember_id,)).fetchone()
        if not row:
            raise WyldError(f"ember #{ember_id} not found", "run 'wyld ember list' to see banked embers")
        return dict(row)


def kindle_ember(project: Project, ember_id: int, note: str) -> Dict[str, Any]:
    note = note.strip()
    if not note:
        raise WyldError("a note is required to kindle an ember", "provide a note explaining how it will be used")

    ember = get_ember(project, ember_id)
    event = create_event("ember.kindled", {"id": ember_id, "note": note})
    project.store.append_event(event)
    return {
        "id": ember_id,
        "title": ember["title"],
        "kind": ember["kind"],
        "state": EMBER_KINDLED,
        "note": note,
    }


def dismiss_ember(project: Project, ember_id: int, note: str) -> Dict[str, Any]:
    note = note.strip()
    if not note:
        raise WyldError("a note is required to dismiss an ember", "provide a note explaining why it is dismissed")

    ember = get_ember(project, ember_id)
    event = create_event("ember.dismissed", {"id": ember_id, "note": note})
    project.store.append_event(event)
    return {
        "id": ember_id,
        "title": ember["title"],
        "kind": ember["kind"],
        "state": EMBER_DISMISSED,
        "note": note,
    }


def set_ember_kind(project: Project, ember_id: int, kind: str, note: str) -> Dict[str, Any]:
    note = note.strip()
    if not note:
        raise WyldError("a note is required when reclassifying an ember", "provide a note explaining the change")

    kind = kind.lower().strip()
    if kind not in EMBER_KINDS:
        raise WyldError(f"invalid ember kind '{kind}'", "kind must be 'content' or 'mechanic'")

    ember = get_ember(project, ember_id)
    event = create_event("ember.kind_set", {"id": ember_id, "kind": kind, "note": note})
    project.store.append_event(event)
    return {
        "id": ember_id,
        "title": ember["title"],
        "kind": kind,
        "state": ember["state"],
        "note": note,
    }
