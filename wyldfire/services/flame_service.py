"""Flame service: prototype lifecycle operations."""

from pathlib import Path
from typing import Any, Dict, List, Optional
import json

from wyldfire.core.project import Project
from wyldfire.core.events import create_event, check_agent_guardrail
from wyldfire.core.text_utils import resolve_text_or_file
from wyldfire.core.exceptions import WyldError
from wyldfire.core.constants import (
    FLAME_SPARKED,
    FLAME_BURNING,
    FLAME_TESTED,
    FLAME_CROWNED,
    FLAME_DOUSED,
    SMOKE_STAGED,
)


def spark_flame(
    project: Project,
    name: str,
    desc: Optional[str] = None,
    desc_file: Optional[Path] = None,
) -> Dict[str, Any]:
    name = name.strip()
    if not name:
        raise WyldError("flame name cannot be empty", "provide a flame name, e.g. wyld flame spark 'wildfire'")

    final_desc = resolve_text_or_file(desc, desc_file, "desc", required=False, default="")

    with project.get_connection() as conn:
        existing = conn.execute("SELECT id FROM flames WHERE name = ?", (name,)).fetchone()
        if existing:
            raise WyldError(f"flame '{name}' already exists", "use another name or 'wyld flame show <name>'")

    event = create_event("flame.sparked", {"name": name, "description": final_desc})
    project.store.append_event(event)
    return {"name": name, "description": final_desc, "state": FLAME_SPARKED, "version": 1}


def list_flames(project: Project) -> List[Dict[str, Any]]:
    with project.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT f.id, f.name, f.description, f.state, f.created_at,
                   max(s.created_at) as last_stoke_at,
                   count(s.id) as stoke_count,
                   (SELECT count(1) FROM flame_versions v WHERE v.flame_id = f.id) as version_count
            FROM flames f
            LEFT JOIN stokes s ON s.target_kind = 'flame' AND s.target_id = f.id
            GROUP BY f.id
            ORDER BY (last_stoke_at IS NOT NULL) DESC, last_stoke_at DESC, f.created_at DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]


def get_flame(project: Project, name: str) -> Dict[str, Any]:
    with project.get_connection() as conn:
        row = conn.execute("SELECT * FROM flames WHERE name = ?", (name,)).fetchone()
        if not row:
            raise WyldError(f"flame '{name}' not found", "run 'wyld flame list' to see available flames")

        flame = dict(row)
        flame_id = flame["id"]

        # Versions
        v_rows = conn.execute(
            "SELECT n, notes, created_at FROM flame_versions WHERE flame_id = ? ORDER BY n ASC",
            (flame_id,),
        ).fetchall()
        flame["versions"] = [dict(v) for v in v_rows]

        # Stokes
        s_rows = conn.execute(
            """
            SELECT s.id, s.tester, s.notes, s.excluded, s.exclude_reason, s.created_at,
                   v.n as version_n
            FROM stokes s
            LEFT JOIN flame_versions v ON s.flame_version_id = v.id
            WHERE s.target_kind = 'flame' AND s.target_id = ?
            ORDER BY s.created_at ASC
            """,
            (flame_id,),
        ).fetchall()

        stokes = []
        for s in s_rows:
            s_dict = dict(s)
            # Metrics for this stoke
            m_rows = conn.execute(
                "SELECT metric_name, value_text, value_num FROM stoke_metrics WHERE stoke_id = ?",
                (s["id"],),
            ).fetchall()
            s_dict["metrics"] = {m["metric_name"]: m["value_num"] if m["value_num"] is not None else m["value_text"] for m in m_rows}
            stokes.append(s_dict)
        flame["stokes"] = stokes

        # Staged smoke count
        staged_count = conn.execute(
            "SELECT count(1) as cnt FROM smoke WHERE status = ? AND context_kind = 'flame' AND context_ref = ?",
            (SMOKE_STAGED, name),
        ).fetchone()["cnt"]
        flame["staged_smoke_count"] = staged_count

        return flame


def version_flame(
    project: Project,
    name: str,
    notes: Optional[str] = None,
    notes_file: Optional[Path] = None,
) -> Dict[str, Any]:
    final_notes = resolve_text_or_file(notes, notes_file, "notes", required=True)

    flame = get_flame(project, name)
    current_versions = flame["versions"]
    next_n = len(current_versions) + 1

    event = create_event("flame.versioned", {"name": name, "notes": final_notes})
    project.store.append_event(event)

    new_state = FLAME_BURNING if next_n >= 2 and flame["state"] == FLAME_SPARKED else flame["state"]
    return {"name": name, "version": next_n, "notes": final_notes, "state": new_state}


def stoke_flame(
    project: Project,
    name: str,
    tester: str = "dev",
    notes: Optional[str] = None,
    notes_file: Optional[Path] = None,
    metrics: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    flame = get_flame(project, name)
    metrics = metrics or {}

    if metrics and tester in ("dev", "agent"):
        check_agent_guardrail("scoring flame metrics")

    final_notes = resolve_text_or_file(notes, notes_file, "notes", required=False, default="")

    # Find staged smoke for this flame
    with project.get_connection() as conn:
        staged_rows = conn.execute(
            "SELECT id FROM smoke WHERE status = ? AND context_kind = 'flame' AND context_ref = ?",
            (SMOKE_STAGED, name),
        ).fetchall()
        staged_ids = [r["id"] for r in staged_rows]

    # Rule: needs at least one of: notes, metric values, staged smoke
    if not final_notes and not metrics and not staged_ids:
        raise WyldError(
            "a stoke needs at least one of: notes, metric values, or staged smoke",
            "provide --notes '...', --metric name=val, or stage smoke first with 'wyld smoke stage'"
        )

    # Current flame version
    current_ver = len(flame["versions"]) if flame["versions"] else 1

    event = create_event(
        "stoke.logged",
        {
            "target_kind": "flame",
            "target_name": name,
            "flame_version": current_ver,
            "tester": tester,
            "notes": final_notes,
            "metrics": metrics,
            "staged_smoke_ids": staged_ids,
        },
    )
    project.store.append_event(event)

    return {
        "target_kind": "flame",
        "target_name": name,
        "tester": tester,
        "version": current_ver,
        "notes": final_notes,
        "metrics": metrics,
        "committed_smoke_ids": staged_ids,
    }


def crown_flame(project: Project, name: str, note: str) -> Dict[str, Any]:
    check_agent_guardrail("crowning a flame")
    note = note.strip()
    if not note:
        raise WyldError("note is required to crown a flame", "provide a note explaining why this flame was chosen")
    flame = get_flame(project, name)
    event = create_event("flame.crowned", {"name": name, "note": note})
    project.store.append_event(event)
    return {"name": name, "state": FLAME_CROWNED, "note": note}


def douse_flame(project: Project, name: str, note: str) -> Dict[str, Any]:
    note = note.strip()
    if not note:
        raise WyldError("note is required to douse a flame", "provide a note explaining why this flame was doused")
    flame = get_flame(project, name)
    event = create_event("flame.doused", {"name": name, "note": note})
    project.store.append_event(event)
    return {"name": name, "state": FLAME_DOUSED, "note": note}
