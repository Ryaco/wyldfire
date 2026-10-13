"""Fire service: multi-stream game collections and fire lifecycle."""

from pathlib import Path
from typing import Any, Dict, List, Optional
import json

from wyldfire.core.project import Project
from wyldfire.core.events import create_event
from wyldfire.core.exceptions import WyldError, FireNotSelectedError
from wyldfire.core.constants import (
    PHASE_PROTOTYPE,
    PHASE_PRODUCTION,
    PHASE_SHIPPED,
    SMOKE_STAGED,
    SMOKE_OPEN,
    SMOKE_IDENTIFIED,
    FUEL_FINISHED,
)


def resolve_fire_name(project: Project, fire_name: Optional[str] = None) -> str:
    """Resolve fire name from argument or current checkout."""
    if fire_name:
        return fire_name.strip()
    current = project.current_fire
    if current:
        return current.strip()
    raise FireNotSelectedError()


def start_fire(
    project: Project,
    name: str,
    flames: List[str],
    desc: str = "",
) -> Dict[str, Any]:
    name = name.strip()
    if not name:
        raise WyldError("fire name cannot be empty", "provide a fire name, e.g. wyld fire start 'my-game'")

    with project.get_connection() as conn:
        existing = conn.execute("SELECT id FROM fires WHERE name = ?", (name,)).fetchone()
        if existing:
            raise WyldError(f"fire '{name}' already exists", "choose another name or checkout with 'wyld fire checkout'")

        # Verify all flames exist
        clean_flames = []
        for fl in flames:
            fl_clean = fl.strip()
            if not fl_clean:
                continue
            row = conn.execute("SELECT id FROM flames WHERE name = ?", (fl_clean,)).fetchone()
            if not row:
                raise WyldError(f"flame '{fl_clean}' does not exist", "spark it first with 'wyld flame spark'")
            clean_flames.append(fl_clean)

    event = create_event(
        "fire.started",
        {"name": name, "flames": clean_flames, "description": desc},
    )
    project.store.append_event(event)

    # Auto-checkout if no current fire
    if not project.current_fire:
        project.set_current_fire(name)

    return {
        "name": name,
        "description": desc,
        "phase": PHASE_PROTOTYPE,
        "flames": clean_flames,
    }


def list_fires(project: Project) -> List[Dict[str, Any]]:
    current = project.current_fire
    with project.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT f.id, f.name, f.description, f.phase, f.created_at,
                   count(ff.flame_id) as flame_count
            FROM fires f
            LEFT JOIN fire_flames ff ON f.id = ff.fire_id
            GROUP BY f.id
            ORDER BY f.created_at ASC
            """
        ).fetchall()

        result = []
        for r in rows:
            d = dict(r)
            d["is_current"] = (d["name"] == current)
            result.append(d)
        return result


def checkout_fire(project: Project, name: str) -> Dict[str, Any]:
    name = name.strip()
    with project.get_connection() as conn:
        row = conn.execute("SELECT name, phase FROM fires WHERE name = ?", (name,)).fetchone()
        if not row:
            raise WyldError(f"fire '{name}' not found", "list fires with 'wyld fire list'")

    project.set_current_fire(name)
    return {"name": name, "phase": row["phase"]}


def get_fire(project: Project, name: str) -> Dict[str, Any]:
    with project.get_connection() as conn:
        row = conn.execute("SELECT * FROM fires WHERE name = ?", (name,)).fetchone()
        if not row:
            raise WyldError(f"fire '{name}' not found", "run 'wyld fire list' to see available fires")

        fire = dict(row)
        fire["is_current"] = (fire["name"] == project.current_fire)
        try:
            fire["toys"] = json.loads(fire["toys_json"])
        except Exception:
            fire["toys"] = []

        try:
            fire["slice_bundles"] = json.loads(fire["slice_bundles_json"])
        except Exception:
            fire["slice_bundles"] = []

        # Flames
        fl_rows = conn.execute(
            """
            SELECT fl.id, fl.name, fl.state, ff.pinned_version, ff.added_at,
                   (SELECT count(1) FROM flame_versions v WHERE v.flame_id = fl.id) as current_version
            FROM fire_flames ff
            JOIN flames fl ON ff.flame_id = fl.id
            WHERE ff.fire_id = ?
            ORDER BY ff.added_at ASC
            """,
            (fire["id"],),
        ).fetchall()
        fire["flames"] = [dict(r) for r in fl_rows]

        # Gate config
        g_row = conn.execute("SELECT min_stokes, blocked_severity FROM gate_config WHERE fire_id = ?", (fire["id"],)).fetchone()
        if g_row:
            fire["gate_config"] = dict(g_row)
        else:
            fire["gate_config"] = {"min_stokes": 3, "blocked_severity": 2}

        # Stokes on this fire
        s_rows = conn.execute(
            "SELECT * FROM stokes WHERE target_kind = 'fire' AND target_id = ? ORDER BY created_at ASC",
            (fire["id"],),
        ).fetchall()
        stokes = []
        for s in s_rows:
            sd = dict(s)
            m_rows = conn.execute(
                "SELECT metric_name, value_text, value_num FROM stoke_metrics WHERE stoke_id = ?",
                (s["id"],),
            ).fetchall()
            sd["metrics"] = {m["metric_name"]: m["value_num"] if m["value_num"] is not None else m["value_text"] for m in m_rows}
            stokes.append(sd)
        fire["stokes"] = stokes

        # Wick summary
        w_counts = conn.execute(
            """
            SELECT count(1) as total_fuel,
                   sum(case when wf.state = 'finished' then 1 else 0 end) as finished_fuel,
                   sum(case when wb.cut = 1 then 1 else 0 end) as cut_bundles
            FROM wick_bundles wb
            LEFT JOIN wick_fuel wf ON wf.bundle_id = wb.id
            WHERE wb.fire_id = ?
            """,
            (fire["id"],),
        ).fetchone()
        fire["wick_summary"] = dict(w_counts) if w_counts else {"total_fuel": 0, "finished_fuel": 0, "cut_bundles": 0}

        return fire


def add_flames_to_fire(project: Project, name: str, flames: List[str]) -> Dict[str, Any]:
    fire = get_fire(project, name)
    clean_flames = []
    with project.get_connection() as conn:
        for fl in flames:
            fl_clean = fl.strip()
            if not fl_clean:
                continue
            row = conn.execute("SELECT id FROM flames WHERE name = ?", (fl_clean,)).fetchone()
            if not row:
                raise WyldError(f"flame '{fl_clean}' not found", "spark it first with 'wyld flame spark'")
            clean_flames.append(fl_clean)

    event = create_event("fire.flames_added", {"name": name, "flames": clean_flames})
    project.store.append_event(event)
    return {"name": name, "added_flames": clean_flames}


def remove_flames_from_fire(project: Project, name: str, flames: List[str]) -> Dict[str, Any]:
    fire = get_fire(project, name)
    clean_flames = [fl.strip() for fl in flames if fl.strip()]
    event = create_event("fire.flames_removed", {"name": name, "flames": clean_flames})
    project.store.append_event(event)
    return {"name": name, "removed_flames": clean_flames}


def set_core_loop(project: Project, fire_name: str, loop: str) -> Dict[str, Any]:
    loop = loop.strip()
    if not loop:
        raise WyldError("core loop cannot be empty", "declare the core loop, e.g. 'spot fire → cut firebreaks → starve it → score'")

    fire = get_fire(project, fire_name)
    event = create_event("fire.loop_set", {"name": fire_name, "core_loop": loop})
    project.store.append_event(event)
    return {"name": fire_name, "core_loop": loop, "stokes": fire["stokes"]}


def add_toy(project: Project, fire_name: str, toy: str) -> Dict[str, Any]:
    toy = toy.strip()
    if not toy:
        raise WyldError("toy declaration cannot be empty", "declare a playful system, e.g. 'cutting firebreaks'")

    fire = get_fire(project, fire_name)
    event = create_event("fire.toy_added", {"name": fire_name, "toy": toy})
    project.store.append_event(event)
    return {"name": fire_name, "toy": toy}


def stoke_fire(
    project: Project,
    name: str,
    tester: str = "dev",
    notes: Optional[str] = None,
    notes_file: Optional[Path] = None,
    metrics: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    fire = get_fire(project, name)
    metrics = metrics or {}

    final_notes = ""
    if notes_file:
        if not notes_file.exists():
            raise WyldError(f"notes file '{notes_file}' does not exist", "check file path")
        final_notes = notes_file.read_text(encoding="utf-8").strip()
    elif notes:
        final_notes = notes.strip()

    # Find staged smoke for this fire
    with project.get_connection() as conn:
        staged_rows = conn.execute(
            "SELECT id FROM smoke WHERE status = ? AND context_kind = 'fire' AND context_ref = ?",
            (SMOKE_STAGED, name),
        ).fetchall()
        staged_ids = [r["id"] for r in staged_rows]

    if not final_notes and not metrics and not staged_ids:
        raise WyldError(
            "a stoke needs at least one of: notes, metric values, or staged smoke",
            "provide --notes '...', --metric name=val, or stage smoke first with 'wyld smoke stage'"
        )

    event = create_event(
        "stoke.logged",
        {
            "target_kind": "fire",
            "target_name": name,
            "tester": tester,
            "notes": final_notes,
            "metrics": metrics,
            "staged_smoke_ids": staged_ids,
        },
    )
    project.store.append_event(event)

    return {
        "target_kind": "fire",
        "target_name": name,
        "tester": tester,
        "notes": final_notes,
        "metrics": metrics,
        "committed_smoke_ids": staged_ids,
    }


def ship_fire(project: Project, fire_name: str) -> Dict[str, Any]:
    fire = get_fire(project, fire_name)
    if fire["phase"] != PHASE_PRODUCTION:
        raise WyldError(
            f"cannot ship fire in phase '{fire['phase']}'",
            "a fire can only be shipped from 'production' phase"
        )

    # Validate ship requirements:
    # 1. Wick complete: every fuel finished or in a cut bundle
    with project.get_connection() as conn:
        unfinished_fuel = conn.execute(
            """
            SELECT wf.id, wf.name, wb.name as bundle_name
            FROM wick_fuel wf
            JOIN wick_bundles wb ON wf.bundle_id = wb.id
            WHERE wb.fire_id = ? AND wb.cut = 0 AND wf.state != ?
            """,
            (fire["id"], FUEL_FINISHED),
        ).fetchall()

        if unfinished_fuel:
            names = ", ".join(f"'{r['name']}' in bundle '{r['bundle_name']}'" for r in unfinished_fuel[:3])
            raise WyldError(
                f"wick is not complete ({len(unfinished_fuel)} unfinished fuel: {names})",
                "finish all remaining fuel with 'wyld wick finish' or cut bundles with 'wyld wick cut'"
            )

        # 2. >= 1 production (beta) stoke — notes required
        # A stoke on the fire with non-empty notes
        beta_stokes = conn.execute(
            "SELECT id, notes FROM stokes WHERE target_kind = 'fire' AND target_id = ? AND excluded = 0 AND notes != ''",
            (fire["id"],),
        ).fetchall()
        if not beta_stokes:
            raise WyldError(
                "no beta stoke with notes logged on this fire",
                "log a production stoke with notes: 'wyld fire stoke <name> --notes \"...\"'"
            )

        # 3. zero open smoke with severity >= 2 in fire's contexts
        # Contexts: member flames, fire/<name>, gate
        member_flames = [fl["name"] for fl in fire["flames"]]
        smoke_rows = conn.execute(
            """
            SELECT id, title, severity, tags, context_kind, context_ref
            FROM smoke
            WHERE status IN (?, ?)
            """,
            (SMOKE_OPEN, SMOKE_IDENTIFIED),
        ).fetchall()

        blocking_smoke = []
        polish_smoke = []
        for sm in smoke_rows:
            ck, cr = sm["context_kind"], sm["context_ref"]
            in_scope = (
                (ck == "fire" and cr == fire_name)
                or (ck == "flame" and cr in member_flames)
                or (ck in ("gate", "production"))
            )
            if not in_scope:
                continue

            if sm["severity"] >= 2:
                blocking_smoke.append(sm)
            tags_list = [t.strip().lower() for t in sm["tags"].split(",") if t.strip()]
            if "polish" in tags_list:
                polish_smoke.append(sm)

        if blocking_smoke:
            sm_titles = ", ".join(f"#{s['id']} ('{s['title']}')" for s in blocking_smoke[:3])
            raise WyldError(
                f"open smoke with severity >= 2 remains: {sm_titles}",
                "clear open smoke with 'wyld smoke clear <id> --note \"...\"'"
            )

        if polish_smoke:
            sm_titles = ", ".join(f"#{s['id']} ('{s['title']}')" for s in polish_smoke[:3])
            raise WyldError(
                f"open smoke tagged 'polish' remains: {sm_titles}",
                "clear polish smoke before shipping"
            )

    event = create_event("fire.shipped", {"name": fire_name})
    project.store.append_event(event)

    return {"name": fire_name, "phase": PHASE_SHIPPED}
