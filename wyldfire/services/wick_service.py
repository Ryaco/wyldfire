"""Wick service: burn-down plan, bundles, fuel, traversal, and ETA."""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
import json

from wyldfire.core.project import Project
from wyldfire.core.events import create_event
from wyldfire.core.exceptions import WyldError
from wyldfire.core.constants import (
    PHASE_GATE_PART2,
    FUEL_QUEUED,
    FUEL_CREATING,
    FUEL_FINISHED,
)
from wyldfire.core.time_utils import parse_duration_to_minutes, format_minutes, utc_now
from wyldfire.services.fire_service import get_fire, resolve_fire_name
from wyldfire.services.template_service import get_template


def plan_wick(project: Project, fire_name: Optional[str] = None) -> Dict[str, Any]:
    resolved = resolve_fire_name(project, fire_name)
    event = create_event("wick.planned", {"fire": resolved})
    project.store.append_event(event)
    return {"fire": resolved, "message": f"wick initialized for fire '{resolved}'"}


def add_bundle(
    project: Project,
    name: str,
    parent: Optional[str] = None,
    metadata: Optional[Dict[str, str]] = None,
    template_name: Optional[str] = None,
    fire_name: Optional[str] = None,
) -> Dict[str, Any]:
    name = name.strip()
    if not name:
        raise WyldError("bundle name cannot be empty", "provide a bundle name, e.g. 'area 1'")

    resolved = resolve_fire_name(project, fire_name)
    fire = get_fire(project, resolved)
    meta = metadata or {}

    with project.get_connection() as conn:
        parent_id = None
        if parent:
            p_row = conn.execute(
                "SELECT id FROM wick_bundles WHERE fire_id = ? AND name = ?",
                (fire["id"], parent.strip()),
            ).fetchone()
            if not p_row:
                raise WyldError(f"parent bundle '{parent}' not found", "check existing bundles with 'wyld wick bundle list'")
            parent_id = p_row["id"]

        # Check unique bundle name under same parent
        existing = conn.execute(
            "SELECT id FROM wick_bundles WHERE fire_id = ? AND (parent_id IS ?) AND name = ?",
            (fire["id"], parent_id, name),
        ).fetchone()
        if existing:
            raise WyldError(f"bundle '{name}' already exists in this scope", "choose a unique bundle name")

    event = create_event(
        "wick.bundle_added",
        {
            "fire": resolved,
            "name": name,
            "parent": parent.strip() if parent else None,
            "metadata": meta,
        },
    )
    project.store.append_event(event)

    # If template specified, instantiate template
    instantiated_fuels = []
    instantiated_subbundles = []
    if template_name:
        tmpl = get_template(project, template_name)
        definition = tmpl["definition"]
        # Sub-bundles
        for b_def in definition.get("bundles", []):
            b_name = b_def["name"]
            count = b_def.get("count", 1)
            for i in range(1, count + 1):
                sub_name = f"{b_name} {i}" if count > 1 else b_name
                add_bundle(project, sub_name, parent=name, fire_name=resolved)
                instantiated_subbundles.append(sub_name)

        # Fuels
        for f_def in definition.get("fuels", []):
            f_name = f_def["name"]
            f_type = f_def.get("type", "task")
            add_fuel(project, f_name, bundle=name, type_tag=f_type, fire_name=resolved)
            instantiated_fuels.append(f"{f_name} ({f_type})")

    return {
        "fire": resolved,
        "name": name,
        "parent": parent,
        "metadata": meta,
        "template": template_name,
        "instantiated_subbundles": instantiated_subbundles,
        "instantiated_fuels": instantiated_fuels,
    }


def define_bundle_metadata(
    project: Project,
    name: str,
    metadata: Dict[str, str],
    fire_name: Optional[str] = None,
) -> Dict[str, Any]:
    resolved = resolve_fire_name(project, fire_name)
    fire = get_fire(project, resolved)

    with project.get_connection() as conn:
        row = conn.execute(
            "SELECT id, metadata_json FROM wick_bundles WHERE fire_id = ? AND name = ?",
            (fire["id"], name.strip()),
        ).fetchone()
        if not row:
            raise WyldError(f"bundle '{name}' not found", "check 'wyld wick bundle list'")

    event = create_event("wick.bundle_defined", {"fire": resolved, "name": name.strip(), "metadata": metadata})
    project.store.append_event(event)
    return {"fire": resolved, "name": name, "metadata": metadata}


def get_bundle(project: Project, name: str, fire_name: Optional[str] = None) -> Dict[str, Any]:
    resolved = resolve_fire_name(project, fire_name)
    fire = get_fire(project, resolved)

    with project.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM wick_bundles WHERE fire_id = ? AND name = ?",
            (fire["id"], name.strip()),
        ).fetchone()
        if not row:
            raise WyldError(f"bundle '{name}' not found", "check 'wyld wick bundle list'")

        b_dict = dict(row)
        try:
            b_dict["metadata"] = json.loads(b_dict["metadata_json"])
        except Exception:
            b_dict["metadata"] = {}

        # Fuels
        f_rows = conn.execute(
            "SELECT * FROM wick_fuel WHERE bundle_id = ? ORDER BY id ASC",
            (b_dict["id"],),
        ).fetchall()
        b_dict["fuels"] = [dict(f) for f in f_rows]

        # Children
        ch_rows = conn.execute(
            "SELECT name FROM wick_bundles WHERE parent_id = ? ORDER BY position ASC",
            (b_dict["id"],),
        ).fetchall()
        b_dict["children"] = [c["name"] for c in ch_rows]

        return b_dict


def list_bundles_tree(project: Project, fire_name: Optional[str] = None) -> List[Dict[str, Any]]:
    resolved = resolve_fire_name(project, fire_name)
    fire = get_fire(project, resolved)

    with project.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT wb.*,
                   count(wf.id) as fuel_count,
                   sum(case when wf.state = 'finished' then 1 else 0 end) as finished_count
            FROM wick_bundles wb
            LEFT JOIN wick_fuel wf ON wf.bundle_id = wb.id
            WHERE wb.fire_id = ?
            GROUP BY wb.id
            ORDER BY wb.position ASC
            """,
            (fire["id"],),
        ).fetchall()

        all_bundles = []
        for r in rows:
            d = dict(r)
            try:
                d["metadata"] = json.loads(d["metadata_json"])
            except Exception:
                d["metadata"] = {}
            all_bundles.append(d)

        # Build depth-first list
        by_parent: Dict[Optional[int], List[Dict[str, Any]]] = {}
        for b in all_bundles:
            pid = b["parent_id"]
            by_parent.setdefault(pid, []).append(b)

        result: List[Dict[str, Any]] = []

        def _traverse(parent_id: Optional[int], depth: int) -> None:
            children = by_parent.get(parent_id, [])
            children.sort(key=lambda x: x["position"])
            for child in children:
                child["depth"] = depth
                result.append(child)
                _traverse(child["id"], depth + 1)

        _traverse(None, 0)
        return result


def add_fuel(
    project: Project,
    name: str,
    bundle: str,
    fuel_kind: str = "task",
    type_tag: str = "",
    note: str = "",
    fire_name: Optional[str] = None,
) -> Dict[str, Any]:
    name = name.strip()
    if not name:
        raise WyldError("fuel name cannot be empty", "provide a fuel name")

    resolved = resolve_fire_name(project, fire_name)
    fire = get_fire(project, resolved)

    # In Gate Part 2 (vertical slice), only fuel inside designated slice bundles is allowed!
    if fire["phase"] == PHASE_GATE_PART2:
        slice_bundles = fire.get("slice_bundles", [])
        if bundle.strip() not in slice_bundles:
            raise WyldError(
                f"bundle '{bundle}' is outside vertical slice ({slice_bundles})",
                "in gate:part2, fuel work is restricted to designated slice bundles"
            )

    with project.get_connection() as conn:
        b_row = conn.execute(
            "SELECT id FROM wick_bundles WHERE fire_id = ? AND name = ?",
            (fire["id"], bundle.strip()),
        ).fetchone()
        if not b_row:
            raise WyldError(f"bundle '{bundle}' not found", "check 'wyld wick bundle list'")

        # Check unique fuel name in bundle
        existing = conn.execute(
            "SELECT id FROM wick_fuel WHERE bundle_id = ? AND name = ?",
            (b_row["id"], name),
        ).fetchone()
        if existing:
            raise WyldError(f"fuel '{name}' already exists in bundle '{bundle}'", "choose a unique fuel name")

    event = create_event(
        "wick.fuel_added",
        {
            "fire": resolved,
            "bundle": bundle.strip(),
            "name": name,
            "fuel_kind": fuel_kind,
            "type_tag": type_tag.strip(),
            "note": note.strip(),
        },
    )
    project.store.append_event(event)

    return {
        "fire": resolved,
        "bundle": bundle,
        "name": name,
        "fuel_kind": fuel_kind,
        "type_tag": type_tag,
        "state": FUEL_QUEUED,
    }


def define_fuel_placeholder(
    project: Project,
    bundle: str,
    note: str = "",
    fire_name: Optional[str] = None,
) -> Dict[str, Any]:
    fuel_name = f"define: {bundle.strip()}"
    return add_fuel(
        project,
        name=fuel_name,
        bundle=bundle,
        fuel_kind="define",
        type_tag="define",
        note=note,
        fire_name=fire_name,
    )


def start_fuel(project: Project, fuel_name: str, fire_name: Optional[str] = None) -> Dict[str, Any]:
    resolved = resolve_fire_name(project, fire_name)
    fire = get_fire(project, resolved)

    with project.get_connection() as conn:
        row = conn.execute(
            """
            SELECT wf.*, wb.name as bundle_name
            FROM wick_fuel wf
            JOIN wick_bundles wb ON wf.bundle_id = wb.id
            WHERE wb.fire_id = ? AND wf.name = ?
            """,
            (fire["id"], fuel_name.strip()),
        ).fetchone()
        if not row:
            raise WyldError(f"fuel '{fuel_name}' not found", "check 'wyld wick list'")

    event = create_event("wick.fuel_started", {"fire": resolved, "fuel": fuel_name.strip()})
    project.store.append_event(event)
    return {"fire": resolved, "fuel": fuel_name, "state": FUEL_CREATING}


def finish_fuel(project: Project, fuel_name: str, note: Optional[str] = None, fire_name: Optional[str] = None) -> Dict[str, Any]:
    resolved = resolve_fire_name(project, fire_name)
    fire = get_fire(project, resolved)

    with project.get_connection() as conn:
        row = conn.execute(
            """
            SELECT wf.*, wb.name as bundle_name
            FROM wick_fuel wf
            JOIN wick_bundles wb ON wf.bundle_id = wb.id
            WHERE wb.fire_id = ? AND wf.name = ?
            """,
            (fire["id"], fuel_name.strip()),
        ).fetchone()
        if not row:
            raise WyldError(f"fuel '{fuel_name}' not found", "check 'wyld wick list'")

    event = create_event(
        "wick.fuel_finished",
        {"fire": resolved, "fuel": fuel_name.strip(), "note": note.strip() if note else None},
    )
    project.store.append_event(event)
    return {"fire": resolved, "fuel": fuel_name, "state": FUEL_FINISHED, "note": note}


def log_fuel_time(project: Project, fuel_name: str, time_str: str, fire_name: Optional[str] = None) -> Dict[str, Any]:
    minutes = parse_duration_to_minutes(time_str)
    resolved = resolve_fire_name(project, fire_name)
    fire = get_fire(project, resolved)

    with project.get_connection() as conn:
        row = conn.execute(
            """
            SELECT wf.*, wb.name as bundle_name
            FROM wick_fuel wf
            JOIN wick_bundles wb ON wf.bundle_id = wb.id
            WHERE wb.fire_id = ? AND wf.name = ?
            """,
            (fire["id"], fuel_name.strip()),
        ).fetchone()
        if not row:
            raise WyldError(f"fuel '{fuel_name}' not found", "check 'wyld wick list'")
        new_total = row["time_min"] + minutes

    event = create_event(
        "wick.time_logged",
        {"fire": resolved, "fuel": fuel_name.strip(), "minutes": minutes},
    )
    project.store.append_event(event)
    return {
        "fire": resolved,
        "fuel": fuel_name,
        "logged_minutes": minutes,
        "total_time": format_minutes(new_total),
    }


def cut_bundle(project: Project, bundle_name: str, reason: str, fire_name: Optional[str] = None) -> Dict[str, Any]:
    reason = reason.strip()
    if not reason:
        raise WyldError("reason is required to cut a bundle", "provide a reason explaining why this bundle is cut")

    resolved = resolve_fire_name(project, fire_name)
    fire = get_fire(project, resolved)

    with project.get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM wick_bundles WHERE fire_id = ? AND name = ?",
            (fire["id"], bundle_name.strip()),
        ).fetchone()
        if not row:
            raise WyldError(f"bundle '{bundle_name}' not found", "check 'wyld wick bundle list'")

    event = create_event("wick.bundle_cut", {"fire": resolved, "name": bundle_name.strip(), "reason": reason})
    project.store.append_event(event)
    return {"fire": resolved, "bundle": bundle_name, "cut": True, "reason": reason}


def scope_change(project: Project, reason: str, fire_name: Optional[str] = None) -> Dict[str, Any]:
    reason = reason.strip()
    if not reason:
        raise WyldError("reason is required for a scope change", "provide a reason explaining the content addition")

    resolved = resolve_fire_name(project, fire_name)
    event = create_event("wick.scope_changed", {"fire": resolved, "reason": reason})
    project.store.append_event(event)
    return {"fire": resolved, "reason": reason}


def get_next_fuel(project: Project, fire_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Depth-first traversal order: find first unfinished, uncut fuel.
    
    If it is a define-fuel in 'queued' state, auto-start it to 'creating' and prompt user.
    """
    resolved = resolve_fire_name(project, fire_name)
    fire = get_fire(project, resolved)

    ordered_bundles = list_bundles_tree(project, fire_name=resolved)

    with project.get_connection() as conn:
        for b in ordered_bundles:
            if b["cut"] == 1:
                continue

            fuels = conn.execute(
                "SELECT * FROM wick_fuel WHERE bundle_id = ? ORDER BY id ASC",
                (b["id"],),
            ).fetchall()

            for f in fuels:
                if f["state"] != FUEL_FINISHED:
                    fuel_dict = dict(f)
                    fuel_dict["bundle_name"] = b["name"]

                    # Auto-advance define-fuel if queued
                    if fuel_dict["fuel_kind"] == "define" and fuel_dict["state"] == FUEL_QUEUED:
                        start_fuel(project, fuel_dict["name"], fire_name=resolved)
                        fuel_dict["state"] = FUEL_CREATING
                        fuel_dict["prompt_define"] = True
                    else:
                        fuel_dict["prompt_define"] = False

                    return fuel_dict

    return None


def list_wick_full(project: Project, fire_name: Optional[str] = None) -> List[Dict[str, Any]]:
    resolved = resolve_fire_name(project, fire_name)
    fire = get_fire(project, resolved)
    ordered_bundles = list_bundles_tree(project, fire_name=resolved)

    result = []
    with project.get_connection() as conn:
        for b in ordered_bundles:
            b_item = dict(b)
            f_rows = conn.execute(
                "SELECT * FROM wick_fuel WHERE bundle_id = ? ORDER BY id ASC",
                (b["id"],),
            ).fetchall()
            b_item["fuels"] = [dict(f) for f in f_rows]
            result.append(b_item)

    return result


def calculate_eta(project: Project, fire_name: Optional[str] = None) -> Dict[str, Any]:
    resolved = resolve_fire_name(project, fire_name)
    fire = get_fire(project, resolved)

    with project.get_connection() as conn:
        # Finished fuels grouped by type_tag
        finished_rows = conn.execute(
            """
            SELECT coalesce(nullif(wf.type_tag, ''), 'task') as tag,
                   count(1) as finished_count,
                   sum(wf.time_min) as total_min
            FROM wick_fuel wf
            JOIN wick_bundles wb ON wf.bundle_id = wb.id
            WHERE wb.fire_id = ? AND wb.cut = 0 AND wf.state = 'finished'
            GROUP BY tag
            """,
            (fire["id"],),
        ).fetchall()

        # Remaining fuels grouped by type_tag
        remaining_rows = conn.execute(
            """
            SELECT coalesce(nullif(wf.type_tag, ''), 'task') as tag,
                   count(1) as remaining_count
            FROM wick_fuel wf
            JOIN wick_bundles wb ON wf.bundle_id = wb.id
            WHERE wb.fire_id = ? AND wb.cut = 0 AND wf.state != 'finished' AND wf.fuel_kind != 'define'
            GROUP BY tag
            """,
            (fire["id"],),
        ).fetchall()

        # Undefined bundles: bundles that have an unfinished define-fuel
        undefined_bundles_cnt = conn.execute(
            """
            SELECT count(DISTINCT wb.id) as cnt
            FROM wick_bundles wb
            JOIN wick_fuel wf ON wf.bundle_id = wb.id
            WHERE wb.fire_id = ? AND wb.cut = 0 AND wf.fuel_kind = 'define' AND wf.state != 'finished'
            """,
            (fire["id"],),
        ).fetchone()["cnt"]

        # Average total time of defined bundles (bundles with no unfinished define fuel)
        defined_bundle_times = conn.execute(
            """
            SELECT sum(wf.time_min) as b_time
            FROM wick_bundles wb
            JOIN wick_fuel wf ON wf.bundle_id = wb.id
            WHERE wb.fire_id = ? AND wb.cut = 0
              AND wb.id NOT IN (
                  SELECT bundle_id FROM wick_fuel WHERE fuel_kind = 'define' AND state != 'finished'
              )
            GROUP BY wb.id
            HAVING sum(wf.time_min) > 0
            """,
            (fire["id"],),
        ).fetchall()

    finished_map = {r["tag"]: {"count": r["finished_count"], "total_min": r["total_min"]} for r in finished_rows}
    remaining_map = {r["tag"]: r["remaining_count"] for r in remaining_rows}

    total_finished_min = sum(f["total_min"] for f in finished_map.values())
    total_finished_count = sum(f["count"] for f in finished_map.values())

    if total_finished_count == 0 or total_finished_min == 0:
        return {
            "fire": resolved,
            "status": "not enough data yet",
            "message": "not enough data yet (log time on finished fuel with 'wyld wick log <fuel> --time 2h')",
        }

    overall_avg_per_item = total_finished_min / total_finished_count

    all_tags = set(finished_map.keys()) | set(remaining_map.keys())
    breakdown = []
    total_projected_min = 0

    for tag in sorted(all_tags):
        fin_data = finished_map.get(tag, {"count": 0, "total_min": 0})
        f_cnt = fin_data["count"]
        f_tot = fin_data["total_min"]
        r_cnt = remaining_map.get(tag, 0)

        avg_min = (f_tot / f_cnt) if f_cnt > 0 else overall_avg_per_item
        tag_est_min = int(round(avg_min * r_cnt))
        total_projected_min += tag_est_min

        breakdown.append({
            "type": tag,
            "finished_count": f_cnt,
            "avg_hours": round(avg_min / 60.0, 1),
            "remaining_count": r_cnt,
            "estimated_hours": round(tag_est_min / 60.0, 1),
        })

    # Add undefined bundles estimate
    undefined_hours = 0.0
    if undefined_bundles_cnt > 0:
        if defined_bundle_times:
            avg_b_min = sum(r["b_time"] for r in defined_bundle_times) / len(defined_bundle_times)
        else:
            avg_b_min = overall_avg_per_item * 5  # heuristic fallback
        undefined_min = int(round(avg_b_min * undefined_bundles_cnt))
        total_projected_min += undefined_min
        undefined_hours = round(undefined_min / 60.0, 1)

    # Calculate projected finish date assuming 4 productive hours/day (solo dev pace)
    hours_left = total_projected_min / 60.0
    days_needed = max(1, int(round(hours_left / 4.0)))
    finish_date = (utc_now() + timedelta(days=days_needed)).strftime("%Y-%m-%d")

    return {
        "fire": resolved,
        "status": "calculated",
        "breakdown": breakdown,
        "undefined_bundles_count": undefined_bundles_cnt,
        "undefined_bundles_hours": undefined_hours,
        "total_estimated_hours": round(total_projected_min / 60.0, 1),
        "projected_finish": finish_date,
    }
