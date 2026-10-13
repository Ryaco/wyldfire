"""CLI commands for smoke (issues & learning database)."""

from typing import Optional
import click

from wyldfire.core.project import get_current_project
from wyldfire.cli.formatters import output_json, format_table
from wyldfire.services import smoke_service


@click.group()
def smoke():
    """Issues: decoupled bug and question tracking."""
    pass


@smoke.command("log")
@click.argument("title")
@click.option("--on", required=True, help="Context: flame/<n>, fire/<n>, gate, or production")
@click.option("--severity", "-s", type=click.IntRange(1, 3), default=2, help="Severity 1 (nit), 2 (problem), 3 (critical)")
@click.option("--tags", default="", help="Comma-separated tags")
def log_cmd(title: str, on: str, severity: int, tags: str):
    """Log an open issue directly."""
    project = get_current_project()
    res = smoke_service.log_smoke(project, title, on=on, severity=severity, tags=tags)
    click.echo(f"→ smoke #{res['id']} open (severity {res['severity']}) on {res['context']}")


@smoke.command("stage")
@click.argument("title")
@click.option("--on", required=True, help="Context: flame/<n> or fire/<n>")
@click.option("--severity", "-s", type=click.IntRange(1, 3), default=2, help="Severity 1 (nit), 2 (problem), 3 (critical)")
@click.option("--tags", default="", help="Comma-separated tags")
def stage_cmd(title: str, on: str, severity: int, tags: str):
    """Stage an issue found during a playtest (committed by next stoke)."""
    project = get_current_project()
    res = smoke_service.stage_smoke(project, title, on=on, severity=severity, tags=tags)
    click.echo(f"→ smoke #{res['id']} staged (pre-open) on {res['context']}")


@smoke.command("staged")
@click.option("--on", default=None, help="Filter by context")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def staged_cmd(on: Optional[str], as_json: bool):
    """List staged smoke awaiting a stoke commit."""
    project = get_current_project()
    items = smoke_service.list_smoke(project, on=on, status="staged")
    if as_json:
        output_json(items)
        return

    if not items:
        click.echo("No smoke staged.")
        return

    headers = ["ID", "Context", "Severity", "Title", "Tags"]
    rows = []
    for s in items:
        ctx = f"{s['context_kind']}/{s['context_ref']}" if s['context_ref'] else s['context_kind']
        rows.append([s["id"], ctx, s["severity"], s["title"], s["tags"]])
    click.echo(format_table(headers, rows))


@smoke.command("unstage")
@click.argument("smoke_id", type=int)
def unstage_cmd(smoke_id: int):
    """Discard staged smoke."""
    project = get_current_project()
    dropped = smoke_service.unstage_smoke(project, smoke_id)
    click.echo(f"→ discarded staged smoke #{dropped['id']} ('{dropped['title']}')")


@smoke.command("identify")
@click.argument("smoke_id", type=int)
@click.option("--note", required=True, help="Diagnosis note")
def identify_cmd(smoke_id: int, note: str):
    """Diagnose smoke (status: identified)."""
    project = get_current_project()
    res = smoke_service.identify_smoke(project, smoke_id, note)
    click.echo(f"→ smoke #{res['id']} identified")


@smoke.command("clear")
@click.argument("smoke_id", type=int)
@click.option("--note", required=True, help="Fix / resolution note")
def clear_cmd(smoke_id: int, note: str):
    """Clear smoke with fix resolution (status: cleared)."""
    project = get_current_project()
    res = smoke_service.clear_smoke(project, smoke_id, note)
    click.echo(f"→ smoke #{res['id']} cleared")


@smoke.command("tag")
@click.argument("smoke_id", type=int)
@click.option("--tags", required=True, help="Comma-separated tags")
def tag_cmd(smoke_id: int, tags: str):
    """Update tags on smoke."""
    project = get_current_project()
    res = smoke_service.tag_smoke(project, smoke_id, tags)
    click.echo(f"→ smoke #{res['id']} tags updated: {res['tags']}")


@smoke.command("list")
@click.option("--on", default=None, help="Filter by context")
@click.option("--status", default=None, help="Filter by status (staged, open, identified, cleared)")
@click.option("--severity", "-s", type=int, default=None, help="Filter by severity")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def list_cmd(on: Optional[str], status: Optional[str], severity: Optional[int], as_json: bool):
    """List issues with filters."""
    project = get_current_project()
    items = smoke_service.list_smoke(project, on=on, status=status, severity=severity)
    if as_json:
        output_json(items)
        return

    if not items:
        click.echo("No smoke found.")
        return

    headers = ["ID", "Status", "Sev", "Context", "Title", "Tags"]
    rows = []
    for s in items:
        ctx = f"{s['context_kind']}/{s['context_ref']}" if s['context_ref'] else s['context_kind']
        rows.append([s["id"], s["status"], s["severity"], ctx, s["title"], s["tags"]])
    click.echo(format_table(headers, rows))


@smoke.command("show")
@click.argument("smoke_id", type=int)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def show_cmd(smoke_id: int, as_json: bool):
    """Show detailed history and transitions of an issue."""
    project = get_current_project()
    data = smoke_service.get_smoke(project, smoke_id)
    if as_json:
        output_json(data)
        return

    ctx = f"{data['context_kind']}/{data['context_ref']}" if data['context_ref'] else data['context_kind']
    click.echo(f"Smoke #{data['id']}: {data['title']}")
    click.echo(f"Context: {ctx}  |  Severity: {data['severity']}  |  Status: {data['status']}")
    if data["tags"]:
        click.echo(f"Tags: {data['tags']}")

    click.echo("\nTransitions:")
    for t in data["transitions"]:
        click.echo(f"  → {t['to_status']}: {t['note']} ({t['created_at'][:19]})")


@smoke.command("search")
@click.option("--tags", required=True, help="Comma-separated tags to search")
@click.option("--status", default="cleared", help="Status filter (defaults to cleared)")
@click.option("--all", "all_projects", is_flag=True, help="Search across all local projects")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def search_cmd(tags: str, status: Optional[str], all_projects: bool, as_json: bool):
    """Search cleared smoke in current project and widen across local projects."""
    project = get_current_project()
    results, widened = smoke_service.search_smoke(
        project,
        tags=tags,
        status=status,
        all_projects=all_projects,
    )

    if as_json:
        output_json(results)
        return

    if widened:
        click.echo("nothing in this project — widening to all local projects…\n")

    if not results:
        click.echo(f"No smoke found with tags '{tags}'.")
        return

    for item in results:
        p_label = f"[{item.get('project_name', '')}] " if "project_name" in item else ""
        click.echo(f"{p_label}Smoke #{item['id']}: {item['title']} (tags: {item['tags']})")
        if item.get("diagnosis"):
            click.echo(f"  Diagnosis: {item['diagnosis']}")
        if item.get("fix"):
            click.echo(f"  Fix:       {item['fix']}")
        click.echo("")
