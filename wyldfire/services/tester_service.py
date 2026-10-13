"""Tester service: playtester notes and registry."""

from typing import Any, Dict, List

from wyldfire.core.project import Project
from wyldfire.core.events import create_event
from wyldfire.core.exceptions import WyldError


def note_tester(project: Project, name: str, note: str) -> Dict[str, Any]:
    name = name.strip()
    if not name:
        raise WyldError("tester name cannot be empty", "provide tester name")
    note = note.strip()
    if not note:
        raise WyldError("note cannot be empty", "provide a note describing the tester's quirks or background")

    event = create_event("tester.noted", {"name": name, "note": note})
    project.store.append_event(event)
    return {"name": name, "note": note}


def list_testers(project: Project) -> List[Dict[str, Any]]:
    with project.get_connection() as conn:
        rows = conn.execute("SELECT name, note FROM testers ORDER BY name ASC").fetchall()
        return [dict(r) for r in rows]
