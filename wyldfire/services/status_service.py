"""Status service: project dashboard."""

from typing import Any, Dict

from wyldfire.core.project import Project
from wyldfire.core.constants import (
    SMOKE_OPEN,
    SMOKE_IDENTIFIED,
    SMOKE_STAGED,
    EMBER_BANKED,
)
from wyldfire.services.fire_service import list_fires
from wyldfire.services.wick_service import get_next_fuel


def get_project_status(project: Project) -> Dict[str, Any]:
    fires = list_fires(project)
    current_fire_name = project.current_fire

    next_item = None
    if current_fire_name:
        try:
            next_item = get_next_fuel(project, current_fire_name)
        except Exception:
            next_item = None

    with project.get_connection() as conn:
        smoke_rows = conn.execute(
            "SELECT severity, status FROM smoke WHERE status IN (?, ?, ?)",
            (SMOKE_OPEN, SMOKE_IDENTIFIED, SMOKE_STAGED),
        ).fetchall()

        open_smoke = {1: 0, 2: 0, 3: 0}
        staged_smoke_count = 0
        for r in smoke_rows:
            if r["status"] == SMOKE_STAGED:
                staged_smoke_count += 1
            else:
                sev = r["severity"]
                open_smoke[sev] = open_smoke.get(sev, 0) + 1

        banked_embers = conn.execute(
            "SELECT count(1) as cnt FROM embers WHERE state = ?",
            (EMBER_BANKED,),
        ).fetchone()["cnt"]

    return {
        "project_name": project.name,
        "checked_out_fire": current_fire_name,
        "fires": fires,
        "wick_next": next_item,
        "open_smoke": open_smoke,
        "staged_smoke_count": staged_smoke_count,
        "banked_embers_count": banked_embers,
    }
