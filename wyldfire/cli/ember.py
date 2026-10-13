"""CLI commands for embers (parked ideas)."""

from typing import Optional
import click

from wyldfire.core.project import get_current_project
from wyldfire.cli.formatters import output_json, format_table
from wyldfire.services import ember_service


@click.group()
def ember():
    """Parked ideas: bank creative scope during prototype."""
    pass


@ember.command("bank")
@click.argument("title")
@click.option("--note", default="", help="Context note on why/where this struck")
@click.option("--kind", default="content", help="Kind: content or mechanic (defaults to content)")
def bank_cmd(title: str, note: str, kind: str):
    """Bank an idea to prevent scope creep."""
    project = get_current_project()
    res = ember_service.bank_ember(project, title, note=note, kind=kind)
    click.echo(f"→ ember #{res['id']} banked ({res['kind']})")


@ember.command("list")
@click.option("--kind", default=None, help="Filter by kind (content, mechanic)")
@click.option("--state", default=None, help="Filter by state (banked, kindled, dismissed)")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def list_cmd(kind: Optional[str], state: Optional[str], as_json: bool):
    """List parked embers."""
    project = get_current_project()
    items = ember_service.list_embers(project, kind=kind, state=state)
    if as_json:
        output_json(items)
        return

    if not items:
        click.echo("No embers banked.")
        return

    headers = ["ID", "Kind", "State", "Title", "Note"]
    rows = []
    for e in items:
        rows.append([e["id"], e["kind"], e["state"], e["title"], e["note"] or ""])
    click.echo(format_table(headers, rows))


@ember.command("show")
@click.argument("ember_id", type=int)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def show_cmd(ember_id: int, as_json: bool):
    """Show details of a banked ember."""
    project = get_current_project()
    data = ember_service.get_ember(project, ember_id)
    if as_json:
        output_json(data)
        return

    click.echo(f"Ember #{data['id']}: {data['title']}")
    click.echo(f"Kind: {data['kind']}  |  State: {data['state']}")
    if data["note"]:
        click.echo(f"Note: {data['note']}")
    if data["state_note"]:
        click.echo(f"Resolution Note: {data['state_note']}")


@ember.command("kindle")
@click.argument("ember_id", type=int)
@click.option("--note", required=True, help="How this ember will be kindled into production scope")
def kindle_cmd(ember_id: int, note: str):
    """Kindle a banked ember into active scope or prototype."""
    project = get_current_project()
    res = ember_service.kindle_ember(project, ember_id, note)
    click.echo(f"→ ember #{res['id']} kindled ({res['kind']})")


@ember.command("dismiss")
@click.argument("ember_id", type=int)
@click.option("--note", required=True, help="Why this ember was dismissed")
def dismiss_cmd(ember_id: int, note: str):
    """Dismiss a banked ember."""
    project = get_current_project()
    res = ember_service.dismiss_ember(project, ember_id, note)
    click.echo(f"→ ember #{res['id']} dismissed")


@ember.command("set-kind")
@click.argument("ember_id", type=int)
@click.option("--kind", required=True, help="New kind: content or mechanic")
@click.option("--note", required=True, help="Why reclassified")
def set_kind_cmd(ember_id: int, kind: str, note: str):
    """Reclassify ember kind as understanding evolves."""
    project = get_current_project()
    res = ember_service.set_ember_kind(project, ember_id, kind, note)
    click.echo(f"→ ember #{res['id']} reclassified as {res['kind']}")
