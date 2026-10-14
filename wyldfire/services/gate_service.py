"""Gate service: Part 1 verdict, Part 2 vertical slice, Part 3 content plan, laps."""

from typing import Any, Dict, List, Optional, Tuple
import json

from wyldfire.core.project import Project
from wyldfire.core.events import create_event, check_agent_guardrail
from wyldfire.core.exceptions import WyldError
from wyldfire.core.constants import (
    PHASE_PROTOTYPE,
    PHASE_GATE_PART1,
    PHASE_GATE_PART2,
    PHASE_GATE_PART3,
    PHASE_PRODUCTION,
    PHASE_SHIPPED,
    SMOKE_OPEN,
    SMOKE_IDENTIFIED,
    EMBER_BANKED,
    FUEL_FINISHED,
)
from wyldfire.services.fire_service import get_fire, resolve_fire_name


def evaluate_gate_checks(project: Project, fire_name: str) -> Dict[str, Any]:
    fire = get_fire(project, fire_name)
    fire_id = fire["id"]
    cfg = fire["gate_config"]
    min_stokes = cfg["min_stokes"]
    blocked_severity = cfg["blocked_severity"]

    with project.get_connection() as conn:
        # Check for active waivers
        waiver_rows = conn.execute(
            "SELECT check_name, reason FROM gate_overrides WHERE fire_id = ? AND kind = 'waive'",
            (fire_id,),
        ).fetchall()
        waivers = {r["check_name"]: r["reason"] for r in waiver_rows}

        checks = []

        # 1. Playtest evidence
        # Count non-excluded stokes on this fire, or fallback to member flames
        fire_stokes = conn.execute(
            "SELECT s.* FROM stokes s WHERE s.target_kind = 'fire' AND s.target_id = ? AND s.excluded = 0",
            (fire_id,),
        ).fetchall()

        excluded_stokes = conn.execute(
            "SELECT count(1) as cnt FROM stokes WHERE target_kind = 'fire' AND target_id = ? AND excluded = 1",
            (fire_id,),
        ).fetchone()["cnt"]

        flame_stokes = []
        flame_excluded = 0
        if fire["flames"]:
            flame_ids = [fl["id"] for fl in fire["flames"]]
            fl_placeholders = ",".join("?" for _ in flame_ids)
            flame_stokes = conn.execute(
                f"SELECT s.* FROM stokes s WHERE s.target_kind = 'flame' AND s.target_id IN ({fl_placeholders}) AND s.excluded = 0",
                flame_ids,
            ).fetchall()
            flame_excluded = conn.execute(
                f"SELECT count(1) as cnt FROM stokes WHERE target_kind = 'flame' AND target_id IN ({fl_placeholders}) AND excluded = 1",
                flame_ids,
            ).fetchone()["cnt"]

        total_stokes = len(fire_stokes) + len(flame_stokes)
        total_excluded = excluded_stokes + flame_excluded
        if len(fire_stokes) >= min_stokes:
            stokes_count = len(fire_stokes)
            stoke_source = "fire stokes"
        else:
            stokes_count = total_stokes
            stoke_source = f"{len(fire_stokes)} fire + {len(flame_stokes)} member flame stokes"

        playtest_passed = (stokes_count >= min_stokes)
        playtest_detail = f"{stokes_count} stokes ({total_excluded} excluded) — requires ≥ {min_stokes} ({stoke_source})"
        if "playtest" in waivers:
            checks.append({
                "name": "playtest",
                "label": "Playtest evidence",
                "passed": True,
                "provenance": f"waived ({waivers['playtest']})",
                "detail": playtest_detail,
            })
        else:
            checks.append({
                "name": "playtest",
                "label": "Playtest evidence",
                "passed": playtest_passed,
                "provenance": "custom" if min_stokes != 3 else "default",
                "detail": playtest_detail,
            })

        # 2. Core loop
        loop_declared = bool(fire["core_loop"] and fire["core_loop"].strip())
        loop_detail = f'"{fire["core_loop"]}"' if loop_declared else "not declared"
        if "core_loop" in waivers:
            checks.append({
                "name": "core_loop",
                "label": "Core loop",
                "passed": True,
                "provenance": f"waived ({waivers['core_loop']})",
                "detail": loop_detail,
            })
        else:
            checks.append({
                "name": "core_loop",
                "label": "Core loop",
                "passed": loop_declared,
                "provenance": "default",
                "detail": loop_detail,
            })

        # 3. Toys
        toys_count = len(fire["toys"])
        toys_detail = f"{toys_count} declared: {', '.join(fire['toys'])}" if toys_count > 0 else "0 declared"
        if "toys" in waivers:
            checks.append({
                "name": "toys",
                "label": "Toys declared",
                "passed": True,
                "provenance": f"waived ({waivers['toys']})",
                "detail": toys_detail,
            })
        else:
            checks.append({
                "name": "toys",
                "label": "Toys declared",
                "passed": toys_count >= 1,
                "provenance": "default",
                "detail": toys_detail,
            })

        # 4. Scope attested
        scope_attested = bool(fire["scope_attested_at"])
        scope_detail = fire["scope_attest_note"] if scope_attested else "dev attestation required"
        if "scope" in waivers:
            checks.append({
                "name": "scope",
                "label": "Scope attested",
                "passed": True,
                "provenance": f"waived ({waivers['scope']})",
                "detail": scope_detail,
            })
        else:
            checks.append({
                "name": "scope",
                "label": "Scope attested",
                "passed": scope_attested,
                "provenance": "default",
                "detail": scope_detail,
            })

        # 5. Smoke
        # zero open smoke with severity >= blocked_severity in fire's contexts
        member_flames = [fl["name"] for fl in fire["flames"]]
        smoke_rows = conn.execute(
            "SELECT id, title, severity, context_kind, context_ref FROM smoke WHERE status IN (?, ?)",
            (SMOKE_OPEN, SMOKE_IDENTIFIED),
        ).fetchall()

        blocking_smoke = []
        for sm in smoke_rows:
            ck, cr = sm["context_kind"], sm["context_ref"]
            in_scope = (
                (ck == "fire" and cr == fire_name)
                or (ck == "flame" and cr in member_flames)
                or (ck in ("gate", "production"))
            )
            if in_scope and sm["severity"] >= blocked_severity:
                blocking_smoke.append(sm)

        smoke_passed = (len(blocking_smoke) == 0)
        smoke_detail = (
            f"0 open smoke at severity ≥ {blocked_severity}"
            if smoke_passed
            else f"{len(blocking_smoke)} open smoke at severity ≥ {blocked_severity}: "
            + ", ".join(f"#{s['id']} ('{s['title']}')" for s in blocking_smoke[:3])
        )
        if "smoke" in waivers:
            checks.append({
                "name": "smoke",
                "label": "Smoke cleared",
                "passed": True,
                "provenance": f"waived ({waivers['smoke']})",
                "detail": smoke_detail,
            })
        else:
            checks.append({
                "name": "smoke",
                "label": "Smoke cleared",
                "passed": smoke_passed,
                "provenance": "custom" if blocked_severity != 2 else "default",
                "detail": smoke_detail,
            })

        # 6. Embers
        banked_count = conn.execute(
            "SELECT count(1) as cnt FROM embers WHERE state = ?",
            (EMBER_BANKED,),
        ).fetchone()["cnt"]
        embers_passed = (banked_count == 0)
        embers_detail = f"{banked_count} banked embers remaining" if banked_count > 0 else "all reviewed (0 banked)"
        if "embers" in waivers:
            checks.append({
                "name": "embers",
                "label": "Embers reviewed",
                "passed": True,
                "provenance": f"waived ({waivers['embers']})",
                "detail": embers_detail,
            })
        else:
            checks.append({
                "name": "embers",
                "label": "Embers reviewed",
                "passed": embers_passed,
                "provenance": "default",
                "detail": embers_detail,
            })

        all_passed = all(c["passed"] for c in checks)
        return {
            "fire": fire_name,
            "phase": fire["phase"],
            "all_passed": all_passed,
            "checks": checks,
        }


def get_gate_status(project: Project, fire_name: Optional[str] = None) -> Dict[str, Any]:
    resolved = resolve_fire_name(project, fire_name)
    return evaluate_gate_checks(project, resolved)


def open_gate(project: Project, fire_name: Optional[str] = None) -> Dict[str, Any]:
    resolved = resolve_fire_name(project, fire_name)
    fire = get_fire(project, resolved)
    eval_result = evaluate_gate_checks(project, resolved)

    # Determine if this is an initial gate or a LAP
    # A lap occurs if the fire is in production, shipped, or post-Part1 pass
    is_lap = fire["phase"] in (PHASE_PRODUCTION, PHASE_SHIPPED, PHASE_GATE_PART2, PHASE_GATE_PART3)

    lap_no = None
    if is_lap:
        with project.get_connection() as conn:
            cnt = conn.execute(
                "SELECT count(1) as cnt FROM gate_verdicts WHERE fire_id = ? AND kind = 'lap'",
                (fire["id"],),
            ).fetchone()["cnt"]
            lap_no = cnt + 1

    if eval_result["all_passed"]:
        # Pass: pin current versions of member flames
        pinned_versions = {}
        for fl in fire["flames"]:
            pinned_versions[fl["name"]] = fl["current_version"]

        event = create_event(
            "gate.part1.passed",
            {
                "fire": resolved,
                "pinned_versions": pinned_versions,
                "is_lap": is_lap,
                "lap_no": lap_no,
            },
        )
        project.store.append_event(event)

        new_phase = PHASE_PRODUCTION if is_lap else PHASE_GATE_PART2
        return {
            "fire": resolved,
            "verdict": "pass",
            "is_lap": is_lap,
            "lap_no": lap_no,
            "phase": new_phase,
            "pinned_versions": pinned_versions,
        }
    else:
        # Hold: compile reasons why
        reasons = []
        for c in eval_result["checks"]:
            if not c["passed"]:
                reasons.append(f"{c['label']}: {c['detail']}")

        event = create_event(
            "gate.part1.held",
            {
                "fire": resolved,
                "reasons": reasons,
                "is_lap": is_lap,
                "lap_no": lap_no,
            },
        )
        project.store.append_event(event)

        new_phase = fire["phase"] if is_lap else PHASE_PROTOTYPE
        return {
            "fire": resolved,
            "verdict": "hold",
            "is_lap": is_lap,
            "lap_no": lap_no,
            "phase": new_phase,
            "reasons": reasons,
        }


def config_gate(
    project: Project,
    fire_name: Optional[str] = None,
    min_stokes: Optional[int] = None,
    blocked_severity: Optional[int] = None,
) -> Dict[str, Any]:
    resolved = resolve_fire_name(project, fire_name)
    fire = get_fire(project, resolved)

    if min_stokes is not None or blocked_severity is not None:
        event = create_event(
            "gate.config_set",
            {
                "fire": resolved,
                "min_stokes": min_stokes,
                "blocked_severity": blocked_severity,
            },
        )
        project.store.append_event(event)
        fire = get_fire(project, resolved)

    return {
        "fire": resolved,
        "min_stokes": fire["gate_config"]["min_stokes"],
        "blocked_severity": fire["gate_config"]["blocked_severity"],
    }


def attest_scope(project: Project, note: str, fire_name: Optional[str] = None) -> Dict[str, Any]:
    check_agent_guardrail("attesting gate scope")
    note = note.strip()
    if not note:
        raise WyldError("note is required for scope attestation", "provide a note attesting that scope is complete")

    resolved = resolve_fire_name(project, fire_name)
    event = create_event("gate.scope_attested", {"fire": resolved, "note": note})
    project.store.append_event(event)
    return {"fire": resolved, "note": note}


def exclude_stoke(project: Project, stoke_id: int, reason: str, fire_name: Optional[str] = None) -> Dict[str, Any]:
    check_agent_guardrail("excluding stoke evidence")
    reason = reason.strip()
    if not reason:
        raise WyldError("reason is required to exclude a stoke", "provide a reason for dropping the stoke's evidence")

    resolved = resolve_fire_name(project, fire_name)
    with project.get_connection() as conn:
        row = conn.execute("SELECT id FROM stokes WHERE id = ?", (stoke_id,)).fetchone()
        if not row:
            raise WyldError(f"stoke #{stoke_id} not found", "check stoke id")

    event = create_event("stoke.excluded", {"stoke_id": stoke_id, "reason": reason, "fire": resolved})
    project.store.append_event(event)
    return {"stoke_id": stoke_id, "reason": reason, "fire": resolved}


def waive_check(project: Project, check_name: str, reason: str, fire_name: Optional[str] = None) -> Dict[str, Any]:
    check_agent_guardrail("waiving a gate check")
    reason = reason.strip()
    if not reason:
        raise WyldError("reason is required to waive a gate check", "provide a reason for the waiver")

    check_name = check_name.lower().strip()
    valid_checks = ("playtest", "core_loop", "toys", "scope", "smoke", "embers")
    if check_name not in valid_checks:
        raise WyldError(
            f"unknown gate check '{check_name}'",
            f"valid checks are: {', '.join(valid_checks)}"
        )

    resolved = resolve_fire_name(project, fire_name)
    event = create_event("gate.check_waived", {"fire": resolved, "check_name": check_name, "reason": reason})
    project.store.append_event(event)
    return {"fire": resolved, "check_name": check_name, "reason": reason}


def set_slice_bundles(project: Project, bundles: List[str], fire_name: Optional[str] = None) -> Dict[str, Any]:
    resolved = resolve_fire_name(project, fire_name)
    clean_bundles = [b.strip() for b in bundles if b.strip()]
    if not clean_bundles:
        raise WyldError("no bundles specified for vertical slice", "provide bundle names, e.g. --bundles 'area 1'")

    event = create_event("gate.slice_set", {"fire": resolved, "bundles": clean_bundles})
    project.store.append_event(event)
    return {"fire": resolved, "bundles": clean_bundles}


def finish_slice(project: Project, note: str, fire_name: Optional[str] = None) -> Dict[str, Any]:
    check_agent_guardrail("attesting vertical slice completion")
    note = note.strip()
    if not note:
        raise WyldError("note is required for slice-done attestation", "provide a pitch-ready attestation note")

    resolved = resolve_fire_name(project, fire_name)
    fire = get_fire(project, resolved)

    if fire["phase"] != PHASE_GATE_PART2:
        raise WyldError(
            f"fire '{resolved}' is in phase '{fire['phase']}', not gate:part2",
            "slice-done is only valid during gate:part2"
        )

    slice_bundles = fire["slice_bundles"]
    if not slice_bundles:
        raise WyldError("no vertical slice designated", "designate slice with 'wyld gate slice set --bundles ...'")

    with project.get_connection() as conn:
        # Check all slice fuel is finished
        placeholders = ",".join("?" for _ in slice_bundles)
        unfinished = conn.execute(
            f"""
            SELECT wf.name, wb.name as bundle_name
            FROM wick_fuel wf
            JOIN wick_bundles wb ON wf.bundle_id = wb.id
            WHERE wb.fire_id = ? AND wb.name IN ({placeholders}) AND wf.state != ?
            """,
            [fire["id"], *slice_bundles, FUEL_FINISHED],
        ).fetchall()

        if unfinished:
            names = ", ".join(f"'{u['name']}' in '{u['bundle_name']}'" for u in unfinished[:3])
            raise WyldError(
                f"vertical slice fuel is not finished ({len(unfinished)} remaining: {names})",
                "finish all slice fuel with 'wyld wick finish'"
            )

        # Check ≥ 1 stoke on the fire
        stokes_cnt = conn.execute(
            "SELECT count(1) as cnt FROM stokes WHERE target_kind = 'fire' AND target_id = ? AND excluded = 0",
            (fire["id"],),
        ).fetchone()["cnt"]

        if stokes_cnt < 1:
            raise WyldError(
                "at least 1 playtest (stoke) on the slice is required",
                "stoke the composition with 'wyld fire stoke <fire> --notes \"...\"'"
            )

    event = create_event("gate.slice_done", {"fire": resolved, "note": note})
    project.store.append_event(event)
    return {"fire": resolved, "phase": PHASE_GATE_PART3, "note": note}


def finish_plan(project: Project, note: str, fire_name: Optional[str] = None) -> Dict[str, Any]:
    check_agent_guardrail("attesting content plan completion")
    note = note.strip()
    if not note:
        raise WyldError("note is required for plan-done attestation", "provide an attestation that the plan covers iteration 1")

    resolved = resolve_fire_name(project, fire_name)
    fire = get_fire(project, resolved)

    if fire["phase"] != PHASE_GATE_PART3:
        raise WyldError(
            f"fire '{resolved}' is in phase '{fire['phase']}', not gate:part3",
            "plan-done is only valid during gate:part3"
        )

    with project.get_connection() as conn:
        # Zero unresolved define-fuels
        unresolved_defines = conn.execute(
            """
            SELECT wf.name, wb.name as bundle_name
            FROM wick_fuel wf
            JOIN wick_bundles wb ON wf.bundle_id = wb.id
            WHERE wb.fire_id = ? AND wb.cut = 0 AND wf.fuel_kind = 'define' AND wf.state != ?
            """,
            (fire["id"], FUEL_FINISHED),
        ).fetchall()

        if unresolved_defines:
            names = ", ".join(f"'{u['name']}' in '{u['bundle_name']}'" for u in unresolved_defines[:3])
            raise WyldError(
                f"unresolved define-fuels remaining ({len(unresolved_defines)}: {names})",
                "define each placeholder bundle and finish with 'wyld wick finish'"
            )

    event = create_event("gate.plan_done", {"fire": resolved, "note": note})
    project.store.append_event(event)
    return {"fire": resolved, "phase": PHASE_PRODUCTION, "note": note}


def list_laps(project: Project, fire_name: Optional[str] = None) -> List[Dict[str, Any]]:
    resolved = resolve_fire_name(project, fire_name)
    fire = get_fire(project, resolved)
    with project.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, kind, lap_no, verdict, reasons_json, created_at
            FROM gate_verdicts
            WHERE fire_id = ? AND kind = 'lap'
            ORDER BY id ASC
            """,
            (fire["id"],),
        ).fetchall()

        result = []
        for r in rows:
            d = dict(r)
            try:
                d["reasons"] = json.loads(d["reasons_json"])
            except Exception:
                d["reasons"] = []
            result.append(d)
        return result
