"""CLI commands for testers."""

import click

from wyldfire.core.project import get_current_project
from wyldfire.cli.formatters import output_json, format_table
from wyldfire.services import tester_service


@click.group()
def tester():
    """Testers: named playtesters and their quirks."""
    pass


@tester.command("note")
@click.argument("name")
@click.option("--note", required=True, help="Free-form notes on tester's quirks / background")
def note_cmd(name: str, note: str):
    """Store or update notes for a playtester."""
    project = get_current_project()
    res = tester_service.note_tester(project, name, note)
    click.echo(f"→ tester note recorded for '{res['name']}': \"{res['note']}\"")


@tester.command("list")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def list_cmd(as_json: bool):
    """List registered testers and their notes."""
    project = get_current_project()
    items = tester_service.list_testers(project)
    if as_json:
        output_json(items)
        return

    if not items:
        click.echo("No testers recorded.")
        return

    headers = ["Name", "Note"]
    rows = [[t["name"], t["note"]] for t in items]
    click.echo(format_table(headers, rows))
