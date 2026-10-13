"""CLI commands for templates (reusable bundle & fuel structures)."""

from typing import Optional
import click

from wyldfire.core.project import get_current_project
from wyldfire.cli.formatters import output_json, format_table
from wyldfire.services import template_service


@click.group()
def template():
    """Templates: reusable bundle structures."""
    pass


@template.command("new")
@click.argument("name")
@click.option("--bundles", default="", help="Sub-bundles template, e.g. 'X x3, Y x4'")
@click.option("--fuels", default="", help="Typed fuels, e.g. 'A:sprite, B:audio'")
def new_cmd(name: str, bundles: str, fuels: str):
    """Create a new reusable template."""
    project = get_current_project()
    res = template_service.create_template(project, name, bundles_str=bundles, fuels_str=fuels)
    click.echo(f"→ template '{res['name']}' created")


@template.command("list")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def list_cmd(as_json: bool):
    """List templates."""
    project = get_current_project()
    items = template_service.list_templates(project)
    if as_json:
        output_json(items)
        return

    if not items:
        click.echo("No templates defined.")
        return

    headers = ["Name", "Bundles", "Fuels"]
    rows = []
    for t in items:
        d = t.get("definition", {})
        b_str = ", ".join(f"{b['name']} x{b.get('count', 1)}" for b in d.get("bundles", []))
        f_str = ", ".join(f"{f['name']}:{f.get('type', 'task')}" for f in d.get("fuels", []))
        rows.append([t["name"], b_str, f_str])
    click.echo(format_table(headers, rows))


@template.command("show")
@click.argument("name")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def show_cmd(name: str, as_json: bool):
    """Show details of a template."""
    project = get_current_project()
    t = template_service.get_template(project, name)
    if as_json:
        output_json(t)
        return

    d = t.get("definition", {})
    click.echo(f"Template: {t['name']}")
    click.echo("Bundles:")
    for b in d.get("bundles", []):
        click.echo(f"  - {b['name']} x{b.get('count', 1)}")
    click.echo("Fuels:")
    for f in d.get("fuels", []):
        click.echo(f"  - {f['name']} ({f.get('type', 'task')})")


@template.command("delete")
@click.argument("name")
def delete_cmd(name: str):
    """Delete a template."""
    project = get_current_project()
    res = template_service.delete_template(project, name)
    click.echo(f"→ template '{res['name']}' deleted")
