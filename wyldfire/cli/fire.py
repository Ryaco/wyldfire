"""CLI commands for fires (collections of flames, independent streams)."""

from pathlib import Path
from typing import Optional, Tuple
import click

from wyldfire.core.project import get_current_project
from wyldfire.cli.formatters import output_json, format_table
from wyldfire.services import fire_service


@click.group()
def fire():
    """Fires: named collections of flames; phases live here."""
    pass


@fire.command("start")
@click.argument("name")
@click.option("--flames", required=True, help="Comma-separated member flames")
@click.option("--desc", default="", help="Fire description")
def start_cmd(name: str, flames: str, desc: str):
    """Start a new fire from member flames."""
    project = get_current_project()
    flame_list = [f.strip() for f in flames.split(",") if f.strip()]
    res = fire_service.start_fire(project, name, flames=flame_list, desc=desc)
    click.echo(f"→ fire '{res['name']}' started in phase {res['phase']}")


@fire.command("list")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def list_cmd(as_json: bool):
    """List fires with their phases (like git branch)."""
    project = get_current_project()
    fires = fire_service.list_fires(project)
    if as_json:
        output_json(fires)
        return

    if not fires:
        click.echo("No fires started yet. Run 'wyld fire start <name> --flames ...' to begin.")
        return

    headers = ["Current", "Name", "Phase", "Flames", "Description"]
    rows = []
    for f in fires:
        cur_star = "*" if f.get("is_current") else " "
        rows.append([cur_star, f["name"], f["phase"], f["flame_count"], f["description"] or ""])
    click.echo(format_table(headers, rows))


@fire.command("checkout")
@click.argument("name")
def checkout_cmd(name: str):
    """Switch active focus to a fire (single-stream focus)."""
    project = get_current_project()
    res = fire_service.checkout_fire(project, name)
    click.echo(f"→ checked out fire '{res['name']}' (phase: {res['phase']})")


@fire.command("show")
@click.argument("name", required=False)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def show_cmd(name: Optional[str], as_json: bool):
    """Show details, member flames, loop, toys, and wick summary for a fire."""
    project = get_current_project()
    target = fire_service.resolve_fire_name(project, name)
    data = fire_service.get_fire(project, target)
    if as_json:
        output_json(data)
        return

    cur_label = " (checked out)" if data.get("is_current") else ""
    click.echo(f"Fire: {data['name']}{cur_label}")
    click.echo(f"Phase: {data['phase']}")
    if data["description"]:
        click.echo(f"Description: {data['description']}")
    if data["core_loop"]:
        click.echo(f"Core Loop: {data['core_loop']}")
    if data["toys"]:
        click.echo(f"Toys: {', '.join(data['toys'])}")
    if data["slice_bundles"]:
        click.echo(f"Vertical Slice: {', '.join(data['slice_bundles'])}")

    click.echo("\nMember Flames:")
    for fl in data["flames"]:
        pin_str = f" [pinned v{fl['pinned_version']}]" if fl.get("pinned_version") else f" [current v{fl['current_version']}]"
        click.echo(f"  - {fl['name']} ({fl['state']}){pin_str}")

    click.echo("\nStokes:")
    if data["stokes"]:
        for s in data["stokes"]:
            metrics_str = " ".join(f"{k}={v}" for k, v in s.get("metrics", {}).items())
            notes_str = f'"{s["notes"]}"' if s.get("notes") else ""
            click.echo(f"  #{s['id']} by {s['tester']}: {metrics_str} {notes_str}")
    else:
        click.echo("  none")

    w = data.get("wick_summary", {})
    click.echo(f"\nWick Summary: {w.get('finished_fuel', 0)}/{w.get('total_fuel', 0)} fuel finished ({w.get('cut_bundles', 0)} cut bundles)")


@fire.command("add-flames")
@click.argument("name")
@click.option("--flames", required=True, help="Comma-separated flames to add")
def add_flames_cmd(name: str, flames: str):
    """Add member flames to a fire."""
    project = get_current_project()
    fl_list = [f.strip() for f in flames.split(",") if f.strip()]
    res = fire_service.add_flames_to_fire(project, name, fl_list)
    click.echo(f"→ added flames to '{name}': {', '.join(res['added_flames'])}")


@fire.command("remove-flames")
@click.argument("name")
@click.option("--flames", required=True, help="Comma-separated flames to remove")
def remove_flames_cmd(name: str, flames: str):
    """Remove member flames from a fire."""
    project = get_current_project()
    fl_list = [f.strip() for f in flames.split(",") if f.strip()]
    res = fire_service.remove_flames_from_fire(project, name, fl_list)
    click.echo(f"→ removed flames from '{name}': {', '.join(res['removed_flames'])}")


@fire.command("set-loop")
@click.argument("loop")
@click.option("--fire", "fire_name", default=None, help="Target fire")
def set_loop_cmd(loop: str, fire_name: Optional[str]):
    """Declare the core repeated cycle (shows stoke history first)."""
    project = get_current_project()
    target = fire_service.resolve_fire_name(project, fire_name)

    # Mirror: surface stoke history before recording
    fire_data = fire_service.get_fire(project, target)
    if fire_data["stokes"]:
        click.echo(f"Stoke history for fire '{target}':")
        for s in fire_data["stokes"]:
            m_str = " ".join(f"{k}={v}" for k, v in s.get("metrics", {}).items())
            click.echo(f"  by {s['tester']}: {m_str} \"{s.get('notes', '')}\"")
        click.echo("")

    res = fire_service.set_core_loop(project, target, loop)
    click.echo(f"→ core loop recorded for fire '{target}': \"{res['core_loop']}\"")


@fire.command("add-toy")
@click.argument("toy")
@click.option("--fire", "fire_name", default=None, help="Target fire")
def add_toy_cmd(toy: str, fire_name: Optional[str]):
    """Declare a playful system (win/lose aside)."""
    project = get_current_project()
    target = fire_service.resolve_fire_name(project, fire_name)
    res = fire_service.add_toy(project, target, toy)
    click.echo(f"→ toy declared for fire '{target}': \"{res['toy']}\"")


@fire.command("stoke")
@click.argument("name")
@click.option("--tester", default="dev", help="Tester name (defaults to dev)")
@click.option("--notes", default=None, help="Session notes")
@click.option("--notes-file", type=click.Path(exists=True, path_type=Path), default=None, help="Read notes from file")
@click.option("--metric", "-m", "metric_pairs", multiple=True, help="Metric value e.g. enjoyment=8")
def stoke_cmd(
    name: str,
    tester: str,
    notes: Optional[str],
    notes_file: Optional[Path],
    metric_pairs: Tuple[str, ...],
):
    """Playtest the composition of a fire."""
    project = get_current_project()
    metrics = {}
    for pair in metric_pairs:
        if "=" in pair:
            k, v = pair.split("=", 1)
            metrics[k.strip()] = v.strip()

    res = fire_service.stoke_fire(
        project,
        name=name,
        tester=tester,
        notes=notes,
        notes_file=notes_file,
        metrics=metrics,
    )
    click.echo(f"→ composition stoke logged for fire '{name}' by {res['tester']}")
    if res.get("committed_smoke_ids"):
        c_list = ", ".join(f"#{sid}" for sid in res["committed_smoke_ids"])
        click.echo(f"  committed staged smoke: {c_list}")


@fire.command("ship")
@click.option("--fire", "fire_name", default=None, help="Target fire (defaults to checked out)")
def ship_cmd(fire_name: Optional[str]):
    """Final gate out of production: ship the fire!"""
    project = get_current_project()
    target = fire_service.resolve_fire_name(project, fire_name)
    res = fire_service.ship_fire(project, target)
    click.echo(f"→ fire '{res['name']}' is now shipped! Congratulations.")
