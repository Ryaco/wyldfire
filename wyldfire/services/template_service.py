"""Template service: reusable bundle and fuel structures."""

from typing import Any, Dict, List, Optional
import json
import re

from wyldfire.core.project import Project
from wyldfire.core.events import create_event
from wyldfire.core.exceptions import WyldError


def parse_template_bundles(bundles_str: str) -> List[Dict[str, Any]]:
    """Parse 'X x3, Y x4, Z x2' into [{'name': 'X', 'count': 3}, ...]."""
    if not bundles_str:
        return []
    result = []
    for part in bundles_str.split(","):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^(.*?)\s*x\s*([0-9]+)$", part, re.IGNORECASE)
        if m:
            name = m.group(1).strip()
            count = int(m.group(2))
        else:
            name = part
            count = 1
        result.append({"name": name, "count": count})
    return result


def parse_template_fuels(fuels_str: str) -> List[Dict[str, Any]]:
    """Parse 'A:sprite, B:sprite, C:audio' into [{'name': 'A', 'type': 'sprite'}, ...]."""
    if not fuels_str:
        return []
    result = []
    for part in fuels_str.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            name, ftype = part.split(":", 1)
            result.append({"name": name.strip(), "type": ftype.strip()})
        else:
            result.append({"name": part, "type": "task"})
    return result


def create_template(
    project: Project,
    name: str,
    bundles_str: Optional[str] = None,
    fuels_str: Optional[str] = None,
) -> Dict[str, Any]:
    name = name.strip()
    if not name:
        raise WyldError("template name cannot be empty", "provide a name, e.g. 'area'")

    bundles = parse_template_bundles(bundles_str or "")
    fuels = parse_template_fuels(fuels_str or "")

    definition = {
        "bundles": bundles,
        "fuels": fuels,
    }

    event = create_event("template.created", {"name": name, "definition": definition})
    project.store.append_event(event)

    return {"name": name, "definition": definition}


def list_templates(project: Project) -> List[Dict[str, Any]]:
    with project.get_connection() as conn:
        rows = conn.execute("SELECT id, name, definition_json FROM templates ORDER BY name ASC").fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["definition"] = json.loads(d["definition_json"])
            except Exception:
                d["definition"] = {}
            result.append(d)
        return result


def get_template(project: Project, name: str) -> Dict[str, Any]:
    with project.get_connection() as conn:
        row = conn.execute("SELECT id, name, definition_json FROM templates WHERE name = ?", (name,)).fetchone()
        if not row:
            raise WyldError(f"template '{name}' not found", "run 'wyld template list' to see available templates")
        d = dict(row)
        try:
            d["definition"] = json.loads(d["definition_json"])
        except Exception:
            d["definition"] = {}
        return d


def delete_template(project: Project, name: str) -> Dict[str, Any]:
    get_template(project, name)
    event = create_event("template.deleted", {"name": name})
    project.store.append_event(event)
    return {"name": name, "deleted": True}
