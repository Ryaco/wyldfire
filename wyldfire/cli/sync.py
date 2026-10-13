"""CLI commands for sync and health doctor."""

from typing import Optional
import click

from wyldfire.core.project import get_current_project
from wyldfire.cli.formatters import output_json
from wyldfire.services import sync_service


@click.command("login")
@click.option("--server", required=True, help="Server URL, e.g. https://wyld.example.com")
@click.option("--token", default=None, help="API token (will prompt if omitted)")
def login_cmd(server: str, token: Optional[str]):
    """Store credentials for a remote Wyldfire sync server."""
    if not token:
        token = click.prompt("API Token", hide_input=True)
    sync_service.login_server(server, token)
    click.echo(f"→ credentials stored for {server}")


@click.command("logout")
@click.option("--server", default=None, help="Server URL (clears all if omitted)")
def logout_cmd(server: Optional[str]):
    """Forget stored sync credentials."""
    sync_service.logout_server(server)
    click.echo(f"→ logged out{' from ' + server if server else ''}")


@click.command("link")
@click.option("--server", default=None, help="Server URL")
def link_cmd(server: Optional[str]):
    """Pair project with a server-side project."""
    project = get_current_project()
    res = sync_service.link_project(project, server_url=server)
    click.echo(f"→ paired project '{res['project_name']}' with {res['server_url']}")


@click.command("sync")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def sync_cmd(as_json: bool):
    """Sync events with remote server (push local, pull remote, apply)."""
    project = get_current_project()
    res = sync_service.sync_project(project)
    if as_json:
        output_json(res)
        return

    click.echo(f"Sync Report ({res['server_url']}):")
    click.echo(f"  Pushed: {res['pushed_events']} local events ({res['server_accepted']} accepted, {res['server_skipped']} already on server)")
    click.echo(f"  Pulled: {res['pulled_events']} remote events applied")
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
