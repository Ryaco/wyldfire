"""CLI commands for metrics (developer-defined measurements)."""

import click

from wyldfire.core.project import get_current_project
from wyldfire.cli.formatters import output_json, format_table
from wyldfire.services import metric_service


@click.group()
def metric():
    """Metrics: developer-defined measurements asked across stokes."""
    pass


@metric.command("define")
@click.argument("name")
@click.option("--prompt", required=True, help="Question to ask, e.g. 'How much did you enjoy it? (1-10)'")
@click.option("--type", "metric_type", default="text", help="Type: text or number (defaults to text)")
def define_cmd(name: str, prompt: str, metric_type: str):
    """Define a question to ask of every tester."""
    project = get_current_project()
    res = metric_service.define_metric(project, name, prompt=prompt, metric_type=metric_type)
    click.echo(f"→ metric '{res['name']}' ({res['type']}) defined: \"{res['prompt']}\"")


@metric.command("list")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def list_cmd(as_json: bool):
    """List defined metrics and their prompts."""
    project = get_current_project()
    items = metric_service.list_metrics(project)
    if as_json:
        output_json(items)
        return

    if not items:
        click.echo("No metrics defined.")
        return

    headers = ["Name", "Type", "Prompt"]
    rows = [[m["name"], m["type"], m["prompt"]] for m in items]
    click.echo(format_table(headers, rows))


@metric.command("show")
@click.argument("name")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def show_cmd(name: str, as_json: bool):
    """Show metric definition and values across stokes."""
    project = get_current_project()
    data = metric_service.get_metric(project, name)
    if as_json:
        output_json(data)
        return

    click.echo(f"Metric: {data['name']} ({data['type']})")
    click.echo(f"Prompt: \"{data['prompt']}\"")
    if data["type"] == "number" and data.get("count", 0) > 0:
        click.echo(f"Summary: {data['count']} values | Mean: {data['mean']} | Min: {data['min']} | Max: {data['max']}")

    click.echo("\nRecorded Values:")
    if data["values"]:
        for v in data["values"]:
            val_disp = v["value_num"] if v["value_num"] is not None else v["value_text"]
            tgt = f"{v['target_kind']} '{v['target_name']}'"
            click.echo(f"  {val_disp} on {tgt} by {v['tester']} ({v['created_at'][:10]})")
    else:
        click.echo("  none")


@metric.command("remove")
@click.argument("name")
def remove_cmd(name: str):
    """Remove a metric definition (recorded values are kept)."""
    project = get_current_project()
    res = metric_service.remove_metric(project, name)
    click.echo(f"→ metric '{res['name']}' removed")
