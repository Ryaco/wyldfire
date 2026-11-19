"""CLI commands for sync and health doctor.

Login lives under `wyld remote` now; the top-level `wyld login` /
`logout` / `signup` from 0.1.2 were removed (pre-1.0 breaking change).
"""

from typing import Optional
import click

from wyldfire.core.project import get_current_project
from wyldfire.cli.formatters import output_json
from wyldfire.services import sync_service


@click.command("clone")
@click.option("--remote", default=None, help="Remote to clone from")
@click.option("--server", default=None, help="Remote sync server URL (ad-hoc, unregistered)")
@click.option("--project", "project_id", required=True, help="Remote project ID (UUID)")
@click.argument("directory", required=False, default=None, type=click.Path())
def clone_cmd(remote: Optional[str], server: Optional[str], project_id: str, directory: Optional[str]):
    """Clone an existing remote project by ID onto this machine."""
    from pathlib import Path
    target_dir = Path(directory).resolve() if directory else Path.cwd().resolve()
    res = sync_service.clone_project(target_dir, project_id=project_id, remote=remote, server_url=server)
    click.echo(f"→ joined project {res['project_name']} as {res.get('username', '?')} ({res.get('role', 'member')}) via remote \"{res.get('remote') or res['server_url']}\" — full event history pulled.")
    click.echo(f"  pulled {res['sync']['pulled_events']} events from {res['server_url']}")


@click.command("link")
@click.option("--remote", default=None, help="Remote to link to")
@click.option("--server", default=None, help="Server URL (ad-hoc, unregistered)")
def link_cmd(remote: Optional[str], server: Optional[str]):
    """Register this project with a remote server (the handshake). Does not move events; run 'wyld sync' to exchange events."""
    project = get_current_project()
    res = sync_service.link_project(project, remote=remote, server_url=server)
    created = " (created it)" if res.get("created") else ""
    click.echo(f"→ linked to remote \"{res.get('remote') or res['server_url']}\" ({res['server_url']}) as {res.get('username', '?')} ({res.get('role', 'member')}) — server project \"{res['project_name']}\"{created}.")


@click.command("sync")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
@click.option("--remote", default=None, help="Remote to sync with")
def sync_cmd(as_json: bool, remote: Optional[str]):
    """Exchange events with remote server (the conversation: push local, pull remote, apply). Run 'wyld link' first to register."""
    project = get_current_project()
    res = sync_service.sync_project(project, remote=remote)
    if as_json:
        output_json(res)
        return

    click.echo(f"→ synced as {res.get('username', '?')} ({res.get('role', 'member')}) via remote \"{res.get('remote') or res['server_url']}\" ({res['server_url']})")
    click.echo(f"  Pushed: {res['pushed_events']} local events ({res['server_accepted']} accepted, {res['server_skipped']} already on server)")
    click.echo(f"  Pulled: {res['pulled_events']} remote events applied")
    if res.get("rejected"):
        click.echo("  Rejected:")
        for r in res["rejected"]:
            click.echo(f"    - rejected: event \"{r.get('type')}\" refused — {r.get('reason', '')}")
    if res.get("conflicts"):
        click.echo("  Conflicts:")
        for c in res["conflicts"]:
            click.echo(f"    - {c}")


@click.command("doctor")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def doctor_cmd(as_json: bool):
    """Diagnose health, orphaned work, uncommitted staged smoke, or conflicts."""
    project = get_current_project()
    res = sync_service.run_doctor(project)
    if as_json:
        output_json(res)
        return

    if res["issues_count"] == 0:
        click.echo("✓ Everything looks healthy! No doctor issues found.")
        return

    click.echo(f"Doctor found {res['issues_count']} item(s) needing attention:\n")
    for issue in res["issues"]:
        color = "yellow" if issue["severity"] == "warning" else "red"
        click.echo(click.style(f"[{issue['severity'].upper()}] {issue['message']}", fg=color))
        click.echo(f"  Fix: {issue['fix']}\n")
