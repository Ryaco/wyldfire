"""Metric service: developer-defined measurements."""

from typing import Any, Dict, List, Optional
import statistics

from wyldfire.core.project import Project
from wyldfire.core.events import create_event
from wyldfire.core.exceptions import WyldError


def define_metric(
    project: Project,
    name: str,
    prompt: str,
    metric_type: str = "text",
) -> Dict[str, Any]:
    name = name.strip()
    if not name:
        raise WyldError("metric name cannot be empty", "provide a name, e.g. enjoyment")
    prompt = prompt.strip()
    if not prompt:
        raise WyldError("metric prompt cannot be empty", "provide a prompt, e.g. 'How much did you enjoy it? (1-10)'")

    metric_type = metric_type.lower().strip()
    if metric_type not in ("text", "number"):
        raise WyldError(f"invalid metric type '{metric_type}'", "type must be 'text' or 'number'")

    event = create_event(
        "metric.defined",
        {"name": name, "prompt": prompt, "type": metric_type},
    )
    project.store.append_event(event)
    return {"name": name, "prompt": prompt, "type": metric_type}


def list_metrics(project: Project) -> List[Dict[str, Any]]:
    with project.get_connection() as conn:
        rows = conn.execute("SELECT name, prompt, type, created_at FROM metrics ORDER BY name ASC").fetchall()
        return [dict(r) for r in rows]


def get_metric(project: Project, name: str) -> Dict[str, Any]:
    with project.get_connection() as conn:
        row = conn.execute("SELECT * FROM metrics WHERE name = ?", (name,)).fetchone()
        if not row:
            raise WyldError(f"metric '{name}' not found", "run 'wyld metric list' to see defined metrics")

        data = dict(row)
        # Fetch all recorded values across stokes
        val_rows = conn.execute(
            """
            SELECT sm.value_text, sm.value_num, s.target_kind, s.created_at, s.tester,
                   CASE WHEN s.target_kind = 'flame' THEN f.name ELSE fi.name END as target_name,
                   v.n as flame_version
            FROM stoke_metrics sm
            JOIN stokes s ON sm.stoke_id = s.id
            LEFT JOIN flames f ON s.target_kind = 'flame' AND s.target_id = f.id
            LEFT JOIN fires fi ON s.target_kind = 'fire' AND s.target_id = fi.id
            LEFT JOIN flame_versions v ON s.flame_version_id = v.id
            WHERE sm.metric_name = ?
            ORDER BY s.created_at ASC
            """,
            (name,),
        ).fetchall()

        values = [dict(vr) for vr in val_rows]
        data["values"] = values

        if data["type"] == "number":
            numeric_vals = [v["value_num"] for v in values if v["value_num"] is not None]
            if numeric_vals:
                data["mean"] = round(statistics.mean(numeric_vals), 2)
                data["min"] = min(numeric_vals)
                data["max"] = max(numeric_vals)
                data["count"] = len(numeric_vals)
            else:
                data["mean"] = None
                data["count"] = 0

        return data


def remove_metric(project: Project, name: str) -> Dict[str, Any]:
    with project.get_connection() as conn:
        row = conn.execute("SELECT id FROM metrics WHERE name = ?", (name,)).fetchone()
        if not row:
            raise WyldError(f"metric '{name}' not found", "run 'wyld metric list'")

    event = create_event("metric.removed", {"name": name})
    project.store.append_event(event)
    return {"name": name, "removed": True}
