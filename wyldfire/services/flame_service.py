"""Flame service: prototype lifecycle operations."""

from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import shutil

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
from wyldfire.core.materials import (
    get_effective_ignore_patterns,
    spec_from_patterns,
    load_wyldignore,
    hash_ignore_patterns,
    compute_materials_hash,
)


def spark_flame(
    project: Project,
    name: str,
    desc: Optional[str] = None,
    desc_file: Optional[Path] = None,
    materials: Optional[str] = None,
    forked_from: Optional[str] = None,
) -> Dict[str, Any]:
    name = name.strip()
    if not name:
        raise WyldError("flame name cannot be empty", "provide a flame name, e.g. wyld flame spark 'wildfire'")

    final_desc = resolve_text_or_file(desc, desc_file, "desc", required=False, default="")

    with project.get_connection() as conn:
        existing = conn.execute("SELECT id FROM flames WHERE name = ?", (name,)).fetchone()
        if existing:
            raise WyldError(f"flame '{name}' already exists", "use another name or 'wyld flame show <name>'")

    payload: Dict[str, Any] = {"name": name, "description": final_desc}
    if forked_from:
        payload["forked_from"] = forked_from

    if materials:
        mat_path = Path(materials)
        if not mat_path.is_absolute():
            mat_path = project.root_dir / mat_path
        if not mat_path.exists() or not mat_path.is_dir():
            raise WyldError(
                f"materials path '{materials}' does not exist or is not a directory",
                "create the directory first or check for typos",
            )
        patterns = get_effective_ignore_patterns(project.root_dir)
        spec = spec_from_patterns(patterns)
        payload["materials_path"] = materials
        payload["materials_hash"] = compute_materials_hash(mat_path, spec)
        payload["materials_ignore_hash"] = hash_ignore_patterns(patterns)
        payload["ignore_patterns"] = patterns

    event = create_event("flame.sparked", payload)
    project.store.append_event(event)
    return {
        "name": name,
        "description": final_desc,
        "state": FLAME_SPARKED,
        "version": 1,
        "materials_path": materials or "",
        "forked_from": forked_from or "",
    }


def list_flames(project: Project) -> List[Dict[str, Any]]:
    with project.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT f.id, f.name, f.description, f.state, f.materials_path, f.forked_from, f.created_at,
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
            """
            SELECT n, notes, materials_path, materials_hash, materials_ignore_hash, ignore_patterns_json, created_at
            FROM flame_versions WHERE flame_id = ? ORDER BY n ASC
            """,
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
            s_dict["metrics"] = {
                m["metric_name"]: m["value_num"] if m["value_num"] is not None else m["value_text"]
                for m in m_rows
            }
            stokes.append(s_dict)
        flame["stokes"] = stokes

        # Staged smoke count
        staged_count = conn.execute(
            "SELECT count(1) as cnt FROM smoke WHERE status = ? AND context_kind = 'flame' AND context_ref = ?",
            (SMOKE_STAGED, name),
        ).fetchone()["cnt"]
        flame["staged_smoke_count"] = staged_count

        # Compute materials drift status
        flame["materials_drifted"] = False
        flame["materials_last_version_n"] = len(flame["versions"])
        if flame.get("materials_path"):
            mat_path = Path(flame["materials_path"])
            if not mat_path.is_absolute():
                mat_path = project.root_dir / mat_path
            if mat_path.exists() and flame["versions"]:
                latest_v = flame["versions"][-1]
                flame["materials_last_version_n"] = latest_v["n"]
                if latest_v.get("materials_hash"):
                    patterns = json.loads(latest_v.get("ignore_patterns_json") or "[]")
                    spec = spec_from_patterns(patterns) if patterns else load_wyldignore(project.root_dir)
                    try:
                        cur_hash = compute_materials_hash(mat_path, spec)
                        flame["materials_drifted"] = (cur_hash != latest_v["materials_hash"])
                    except Exception:
                        pass

        return flame


def version_flame(
    project: Project,
    name: str,
    notes: Optional[str] = None,
    notes_file: Optional[Path] = None,
    materials: Optional[str] = None,
) -> Dict[str, Any]:
    final_notes = resolve_text_or_file(notes, notes_file, "notes", required=True)

    flame = get_flame(project, name)
    current_versions = flame["versions"]
    next_n = len(current_versions) + 1

    effective_mat = materials if materials is not None else flame.get("materials_path", "")

    payload: Dict[str, Any] = {"name": name, "notes": final_notes}
    if effective_mat:
        mat_path = Path(effective_mat)
        if not mat_path.is_absolute():
            mat_path = project.root_dir / mat_path
        if not mat_path.exists() or not mat_path.is_dir():
            raise WyldError(
                f"materials path '{effective_mat}' does not exist or is not a directory",
                "create the directory first or check for typos",
            )
        patterns = get_effective_ignore_patterns(project.root_dir)
        spec = spec_from_patterns(patterns)
        payload["materials_path"] = effective_mat
        payload["materials_hash"] = compute_materials_hash(mat_path, spec)
        payload["materials_ignore_hash"] = hash_ignore_patterns(patterns)
        payload["ignore_patterns"] = patterns

    event = create_event("flame.versioned", payload)
    project.store.append_event(event)

    new_state = FLAME_BURNING if next_n >= 2 and flame["state"] == FLAME_SPARKED else flame["state"]
    return {
        "name": name,
        "version": next_n,
        "notes": final_notes,
        "state": new_state,
        "materials_path": effective_mat,
    }


def stoke_flame(
    project: Project,
    name: str,
    tester: str = "dev",
    notes: Optional[str] = None,
    notes_file: Optional[Path] = None,
    metrics: Optional[Dict[str, str]] = None,
    for_version: Optional[int] = None,
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
            "provide --notes '...', --metric name=val, or stage smoke first with 'wyld smoke stage'",
        )

    # Version resolution & drift check
    if for_version is not None:
        # Bypasses drift check entirely per user decision
        valid_versions = [v["n"] for v in flame["versions"]]
        if for_version not in valid_versions:
            raise WyldError(
                f"flame '{name}' has no version {for_version}",
                f"available versions: {', '.join(str(v) for v in valid_versions)}",
            )
        resolved_version = for_version
    else:
        # Check drift on head materials
        if flame.get("materials_path") and flame["versions"]:
            mat_path = Path(flame["materials_path"])
            if not mat_path.is_absolute():
                mat_path = project.root_dir / mat_path
            latest_v = flame["versions"][-1]
            last_n = latest_v["n"]
            if mat_path.exists() and latest_v.get("materials_hash"):
                patterns = json.loads(latest_v.get("ignore_patterns_json") or "[]")
                spec = spec_from_patterns(patterns) if patterns else load_wyldignore(project.root_dir)
                cur_hash = compute_materials_hash(mat_path, spec)
                if cur_hash != latest_v["materials_hash"]:
                    raise WyldError(
                        f"blocked: '{name}' materials changed since v{last_n}.",
                        f"Did you forget to record the new version, or was this playtest of v{last_n}?\n"
                        f"  wyld flame version {name} --notes \"...\"   # record v{last_n + 1}, then stoke\n"
                        f"  wyld flame stoke {name} --for v{last_n} ...      # no — tested v{last_n} as recorded",
                    )
        resolved_version = len(flame["versions"]) if flame["versions"] else 1

    payload: Dict[str, Any] = {
        "target_kind": "flame",
        "target_name": name,
        "flame_version": resolved_version,
        "tester": tester,
        "notes": final_notes,
        "metrics": metrics,
        "staged_smoke_ids": staged_ids,
    }
    if for_version is not None:
        payload["pinned_version_n"] = for_version

    event = create_event("stoke.logged", payload)
    project.store.append_event(event)

    result = {
        "target_kind": "flame",
        "target_name": name,
        "tester": tester,
        "version": resolved_version,
        "notes": final_notes,
        "metrics": metrics,
        "committed_smoke_ids": staged_ids,
    }
    if for_version is not None:
        result["pinned_version_n"] = for_version
    return result


def get_flame_materials(project: Project, name: str) -> List[Dict[str, Any]]:
    """Reverse lookup: find recorded versions matching current materials."""
    flame = get_flame(project, name)
    mat_path_str = flame.get("materials_path")
    if not mat_path_str:
        raise WyldError(
            f"flame '{name}' has no materials path configured",
            f"configure with 'wyld flame version {name} --materials <dir>'",
        )

    mat_path = Path(mat_path_str)
    if not mat_path.is_absolute():
        mat_path = project.root_dir / mat_path
    if not mat_path.exists():
        raise WyldError(
            f"materials directory '{mat_path_str}' does not exist",
            "create the directory or check for typos",
        )

    matches = []
    for v in flame["versions"]:
        rec_hash = v.get("materials_hash")
        if not rec_hash:
            continue
        patterns = json.loads(v.get("ignore_patterns_json") or "[]")
        spec = spec_from_patterns(patterns) if patterns else load_wyldignore(project.root_dir)
        try:
            h = compute_materials_hash(mat_path, spec)
            if h == rec_hash:
                matches.append(v)
        except Exception:
            pass
    return matches


def fork_flame(
    project: Project,
    name: str,
    source: str,
    desc: Optional[str] = None,
    materials: Optional[str] = None,
) -> Dict[str, Any]:
    """Fork a flame into a new flame starting from source's current state."""
    name = name.strip()
    source = source.strip()
    if not name or not source:
        raise WyldError("flame names cannot be empty", "provide both flame name and --fork <source>")
    if name == source:
        raise WyldError("cannot fork a flame onto itself", "choose a distinct name for the new flame")

    source_flame = get_flame(project, source)
    if source_flame["state"] in (FLAME_DOUSED, FLAME_CROWNED):
        raise WyldError(
            f"cannot fork from a {source_flame['state']} flame",
            "forking is only valid for active flames (sparked, burning, tested)",
        )

    with project.get_connection() as conn:
        existing = conn.execute("SELECT id FROM flames WHERE name = ?", (name,)).fetchone()
        if existing:
            raise WyldError(f"flame '{name}' already exists", "choose a different name")

    source_version_n = len(source_flame["versions"])
    forked_from = f"{source}@v{source_version_n}"

    source_materials = source_flame.get("materials_path", "")
    dest_materials = materials or (f"materials/{name}" if source_materials else "")

    if source_materials:
        src_path = Path(source_materials)
        if not src_path.is_absolute():
            src_path = project.root_dir / src_path

        dest_path = Path(dest_materials)
        if not dest_path.is_absolute():
            dest_path = project.root_dir / dest_path

        if src_path.resolve() == dest_path.resolve():
            raise WyldError(
                "fork destination cannot be the source materials directory",
                "specify a different destination directory with --materials",
            )

        if dest_path.exists() and any(dest_path.iterdir()):
            raise WyldError(
                f"destination directory '{dest_materials}' exists and is non-empty — will not clobber",
                "choose an empty or non-existent destination directory",
            )

        if src_path.exists() and src_path.is_dir():
            dest_path.mkdir(parents=True, exist_ok=True)
            for item in src_path.iterdir():
                if item.is_dir():
                    shutil.copytree(item, dest_path / item.name, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, dest_path / item.name)

    final_desc = desc if desc is not None else source_flame.get("description", "")

    payload: Dict[str, Any] = {
        "name": name,
        "description": final_desc,
        "forked_from": forked_from,
    }
    if dest_materials:
        payload["materials_path"] = dest_materials
        dest_path = Path(dest_materials)
        if not dest_path.is_absolute():
            dest_path = project.root_dir / dest_path
        if dest_path.exists() and dest_path.is_dir():
            patterns = get_effective_ignore_patterns(project.root_dir)
            spec = spec_from_patterns(patterns)
            payload["materials_hash"] = compute_materials_hash(dest_path, spec)
            payload["materials_ignore_hash"] = hash_ignore_patterns(patterns)
            payload["ignore_patterns"] = patterns

    event = create_event("flame.sparked", payload)
    project.store.append_event(event)

    return {
        "name": name,
        "description": final_desc,
        "state": FLAME_SPARKED,
        "version": 1,
        "forked_from": forked_from,
        "materials_path": dest_materials,
    }


def rename_flame(project: Project, old_name: str, new_name: str) -> Dict[str, Any]:
    """Rename a flame. Metadata event; version history carries over."""
    old_name = old_name.strip()
    new_name = new_name.strip()
    if not old_name or not new_name:
        raise WyldError("flame names cannot be empty", "provide both old and new flame names")
    if old_name == new_name:
        raise WyldError("old and new names are the same", "provide a new, different name")

    get_flame(project, old_name)  # Validates existence

    with project.get_connection() as conn:
        existing = conn.execute("SELECT id FROM flames WHERE name = ?", (new_name,)).fetchone()
        if existing:
            raise WyldError(f"flame '{new_name}' already exists", "choose a different name")

    event = create_event("flame.renamed", {"old_name": old_name, "new_name": new_name})
    project.store.append_event(event)
    return {"old_name": old_name, "new_name": new_name}


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
