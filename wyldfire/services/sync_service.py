"""Sync and doctor service: offline-first synchronization, collision resolution, and health doctor."""

from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import urllib.request
import urllib.error

from wyldfire.core.project import Project
from wyldfire.core.config import (
    load_credentials,
    save_credential,
    remove_credential,
)
from wyldfire.core.events import Event
from wyldfire.core.exceptions import WyldError
from wyldfire.core.constants import SMOKE_STAGED


def login_server(server_url: str, token: str) -> None:
    server_url = server_url.rstrip("/")
    if not server_url.startswith("http://") and not server_url.startswith("https://"):
        raise WyldError(f"invalid server URL '{server_url}'", "must start with http:// or https://")
    if not token.strip():
        raise WyldError("API token cannot be empty", "provide a valid API token")
    save_credential(server_url, token.strip())


def logout_server(server_url: Optional[str] = None) -> None:
    remove_credential(server_url)


def link_project(project: Project, server_url: Optional[str] = None) -> Dict[str, Any]:
    target_server = server_url or project.config.get("server_url")
    if not target_server:
        raise WyldError("no server URL provided", "run 'wyld link --server <url>' or configure server_url")
    target_server = target_server.rstrip("/")

    creds = load_credentials()
    token = creds.get(target_server)
    if not token:
        raise WyldError(
            f"not logged in to {target_server}",
            f"run 'wyld login --server {target_server}' first"
        )

    # Call POST /api/v1/projects to pair / create
    url = f"{target_server}/api/v1/projects"
    payload = json.dumps({"name": project.name, "project_id": project.project_id}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            project.config.set("server_url", target_server)
            return {
                "server_url": target_server,
                "project_name": project.name,
                "project_id": project.project_id,
                "status": "linked",
                "server_response": data,
            }
    except Exception as e:
        raise WyldError(f"failed to link with server at {target_server}: {e}", "check network and token")


def sync_project(project: Project) -> Dict[str, Any]:
    server_url = project.config.get("server_url")
    if not server_url:
        raise WyldError("project is not linked to a server", "run 'wyld link --server <url>' first")

    creds = load_credentials()
    token = creds.get(server_url.rstrip("/"))
    if not token:
        raise WyldError(
            f"not logged in to {server_url}",
            f"run 'wyld login --server {server_url}' first"
        )

    server_url = server_url.rstrip("/")

    # 1. Read all local events
    local_event_files = project.store.list_event_files()
    local_events = [project.store.read_event_from_file(p) for p in local_event_files]

    # 2. Push local events to server
    push_payload = json.dumps({
        "project_id": project.project_id,
        "events": [e.to_dict() for e in local_events],
    }).encode("utf-8")

    push_req = urllib.request.Request(
        f"{server_url}/api/v1/events",
        data=push_payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )

    pushed_accepted = 0
    pushed_skipped = 0
    try:
        with urllib.request.urlopen(push_req, timeout=15.0) as resp:
            push_res = json.loads(resp.read().decode("utf-8"))
            pushed_accepted = push_res.get("accepted", 0)
            pushed_skipped = push_res.get("skipped", 0)
    except Exception as e:
        raise WyldError(f"failed to push events to {server_url}: {e}", "check server connection")

    # 3. Pull events from server
    last_synced_ts = project.config.get("last_synced_ts", "")
    pull_url = f"{server_url}/api/v1/events?project_id={project.project_id}"
    if last_synced_ts:
        pull_url += f"&since={last_synced_ts}"

    pull_req = urllib.request.Request(
        pull_url,
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )

    pulled_count = 0
    conflicts_resolved: List[str] = []
    try:
        with urllib.request.urlopen(pull_req, timeout=15.0) as resp:
            pull_res = json.loads(resp.read().decode("utf-8"))
            remote_events = pull_res.get("events", [])
            for rev_dict in remote_events:
                rev = Event.from_dict(rev_dict)
                # Check if event is known
                if not project.engine.is_applied(rev.id):
                    # Write event file locally
                    project.store.append_event(rev)
                    pulled_count += 1
            if remote_events:
                latest_remote_ts = remote_events[-1].get("ts")
                if latest_remote_ts:
                    project.config.set("last_synced_ts", latest_remote_ts)
    except Exception as e:
        raise WyldError(f"failed to pull events from {server_url}: {e}", "check server connection")

    return {
        "server_url": server_url,
        "pushed_events": len(local_events),
        "server_accepted": pushed_accepted,
        "server_skipped": pushed_skipped,
        "pulled_events": pulled_count,
        "conflicts": conflicts_resolved,
    }


def run_doctor(project: Project) -> Dict[str, Any]:
    issues: List[Dict[str, Any]] = []

    with project.get_connection() as conn:
        # 1. Uncommitted staged smoke
        staged_rows = conn.execute(
            "SELECT id, title, context_kind, context_ref, created_at FROM smoke WHERE status = ?",
            (SMOKE_STAGED,),
        ).fetchall()
        for r in staged_rows:
            issues.append({
                "severity": "warning",
                "category": "staged_smoke",
                "message": f"staged smoke #{r['id']} ('{r['title']}') on {r['context_kind']}/{r['context_ref']} has not been committed by a stoke",
                "fix": f"run a stoke on {r['context_ref']} or unstage with 'wyld smoke unstage {r['id']}'",
            })

        # 2. Duplicate flame names
        dup_flames = conn.execute(
            "SELECT name, count(1) as cnt FROM flames GROUP BY name HAVING count(1) > 1"
        ).fetchall()
        for d in dup_flames:
            issues.append({
                "severity": "problem",
                "category": "duplicate_flame",
                "message": f"duplicate flame name '{d['name']}' ({d['cnt']} occurrences from concurrent sparks)",
                "fix": "rename one of the flames",
            })

        # 3. Orphaned fuel (fuel whose parent bundle was cut or missing)
        orphaned_fuels = conn.execute(
            """
            SELECT wf.name as fuel_name, wb.name as bundle_name
            FROM wick_fuel wf
            LEFT JOIN wick_bundles wb ON wf.bundle_id = wb.id
            WHERE wb.id IS NULL
            """
        ).fetchall()
        for o in orphaned_fuels:
            issues.append({
                "severity": "problem",
                "category": "orphaned_fuel",
                "message": f"fuel '{o['fuel_name']}' is orphaned",
                "fix": "re-home this fuel under an active bundle",
            })

    return {
        "project_name": project.name,
        "issues_count": len(issues),
        "issues": issues,
    }
