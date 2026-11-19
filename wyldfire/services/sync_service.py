"""Sync and doctor service: offline-first synchronization, collision resolution, and health doctor."""

from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import urllib.request
import urllib.error

from wyldfire.core.project import Project
from wyldfire.core import remotes
from wyldfire.core.events import Event
from wyldfire.core.exceptions import WyldError
from wyldfire.core.constants import SMOKE_STAGED
from wyldfire.services import auth_service


def _project_remote(project: Project, remote_opt: Optional[str] = None):
    """Resolve (remote_name, url) for a project.

    --remote wins; else the project's stored remote name; else the legacy
    server_url, which needs a re-link to adopt a name (sessions are keyed
    by remote name, so a bare URL cannot authenticate).
    """
    if remote_opt:
        return remotes.resolve_remote(remote_opt)
    stored_name = project.config.get("remote")
    if stored_name:
        return remotes.resolve_remote(stored_name)
    stored_url = project.config.get("server_url")
    if stored_url:
        raise WyldError(
            "project links to a server by URL, not by remote name",
            "re-link once with 'wyld link --remote <name>' to adopt the remote name",
        )
    raise WyldError("project is not linked to a server", "run 'wyld link --remote <name>' first")


def link_project(project: Project, remote: Optional[str] = None, server_url: Optional[str] = None) -> Dict[str, Any]:
    remote_name, target_server = remotes.resolve_remote(remote, server_url)
    token = auth_service.ensure_session(remote_name, target_server)
    identity = auth_service.get_stored_auth(remote_name) or {}

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
            if remote_name:
                project.config.set("remote", remote_name)
            project.config.set("server_url", target_server)
            server_proj = data.get("project", {})
            if server_proj.get("name"):
                project.config.set("name", server_proj["name"])
            return {
                "remote": remote_name,
                "server_url": target_server,
                "project_name": project.name,
                "project_id": project.project_id,
                "status": "linked",
                "created": data.get("created", False),
                "username": identity.get("username", ""),
                "role": identity.get("role", "member"),
                "server_response": data,
            }
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8")).get("detail", e.reason)
        except Exception:
            detail = e.reason
        raise WyldError(f"failed to link with server at {target_server}: {detail}", "check membership and login")
    except Exception as e:
        raise WyldError(f"failed to link with server at {target_server}: {e}", "check network and token")


def clone_project(
    target_dir: Path,
    project_id: str,
    remote: Optional[str] = None,
    server_url: Optional[str] = None,
) -> Dict[str, Any]:
    target_dir = target_dir.resolve()
    wyld_dir = target_dir / ".wyld"
    if wyld_dir.exists():
        raise WyldError(
            f"project already initialized at {target_dir}",
            "choose a different directory or remove existing .wyld/ to re-clone",
        )

    remote_name, target_server = remotes.resolve_remote(remote, server_url)
    token = auth_service.ensure_session(remote_name, target_server)
    identity = auth_service.get_stored_auth(remote_name) or {}

    # Create directories
    target_dir.mkdir(parents=True, exist_ok=True)
    events_dir = wyld_dir / "events"
    snapshots_dir = wyld_dir / "snapshots"
    migrations_dir = wyld_dir / "migrations"

    events_dir.mkdir(parents=True, exist_ok=True)
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    migrations_dir.mkdir(parents=True, exist_ok=True)

    # Initialize config
    from wyldfire.core.config import ProjectConfig, register_project
    config = ProjectConfig(wyld_dir)
    config.set("project_id", project_id)
    if remote_name:
        config.set("remote", remote_name)
    config.set("server_url", target_server)
    config.set("mode", "offline-first")
    config.set("name", target_dir.name)

    # Gitignore .wyld/
    gitignore_path = target_dir / ".gitignore"
    entry = "\n# Wyldfire process & decision layer\n.wyld/\n"
    if gitignore_path.exists():
        content = gitignore_path.read_text(encoding="utf-8")
        if ".wyld/" not in content and ".wyld" not in content:
            gitignore_path.write_text(content.rstrip() + entry, encoding="utf-8")
    else:
        gitignore_path.write_text(entry.lstrip(), encoding="utf-8")

    project = Project(target_dir)

    # Link with server to confirm pairing and fetch project metadata
    link_res = link_project(project, remote=remote_name, server_url=target_server)

    # Pull history from server
    sync_res = sync_project(project)

    # Replay all pulled events to build projection
    project.store.replay_all()

    # Register in global registry
    register_project(target_dir, project.name)

    return {
        "project": project,
        "project_id": project_id,
        "project_name": project.name,
        "remote": remote_name,
        "server_url": target_server,
        "username": identity.get("username", ""),
        "role": identity.get("role", "member"),
        "target_dir": target_dir,
        "link": link_res,
        "sync": sync_res,
    }


def sync_project(project: Project, remote: Optional[str] = None) -> Dict[str, Any]:
    remote_name, server_url = _project_remote(project, remote)
    token = auth_service.ensure_session(remote_name, server_url)
    identity = auth_service.get_stored_auth(remote_name) or {}
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
    rejected: List[Dict[str, Any]] = []
    try:
        with urllib.request.urlopen(push_req, timeout=15.0) as resp:
            push_res = json.loads(resp.read().decode("utf-8"))
            pushed_accepted = push_res.get("accepted", 0)
            pushed_skipped = push_res.get("skipped", 0)
            rejected = push_res.get("rejected", [])
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8")).get("detail", e.reason)
        except Exception:
            detail = e.reason
        raise WyldError(f"failed to push events to {server_url}: {detail}", "check membership and login")
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
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8")).get("detail", e.reason)
        except Exception:
            detail = e.reason
        raise WyldError(f"failed to pull events from {server_url}: {detail}", "check membership and login")
    except Exception as e:
        raise WyldError(f"failed to pull events from {server_url}: {e}", "check server connection")

    return {
        "remote": remote_name,
        "server_url": server_url,
        "username": identity.get("username", ""),
        "role": identity.get("role", "member"),
        "pushed_events": len(local_events),
        "server_accepted": pushed_accepted,
        "server_skipped": pushed_skipped,
        "rejected": rejected,
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
