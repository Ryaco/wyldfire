"""CLI commands for flames."""

from pathlib import Path
from typing import Optional, Tuple
import click

from wyldfire.core.project import get_current_project
from wyldfire.core.exceptions import WyldError
from wyldfire.cli.formatters import output_json, format_table
from wyldfire.services import flame_service


@click.group()
def flame():
    """Prototypes: mechanical proofs of concept."""
    pass


@flame.command("spark")
@click.argument("name")
@click.option("--desc", default=None, help="Description of the prototype mechanic")
@click.option("--desc-file", type=click.Path(exists=True, path_type=Path), default=None, help="Read description from file")
@click.option("--materials", default=None, help="Materials directory to track and hash")
@click.option("--fork", "fork_source", default=None, help="Fork an existing flame (copies state/materials)")
def spark(name: str, desc: Optional[str], desc_file: Optional[Path], materials: Optional[str], fork_source: Optional[str]):
    """Create a new flame (or fork an existing one)."""
    project = get_current_project()
    if fork_source:
        res = flame_service.fork_flame(
            project,
            name,
            source=fork_source,
            desc=desc,
            materials=materials,
        )
        click.echo(f"→ flame '{res['name']}' sparked (v1, forked from {res['forked_from']})")
    else:
        res = flame_service.spark_flame(
            project,
            name,
            desc=desc,
            desc_file=desc_file,
            materials=materials,
        )
        click.echo(f"→ flame '{res['name']}' sparked (v1)")


@flame.command("list")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def list_cmd(as_json: bool):
    """List flames sorted by most recent stoke."""
    project = get_current_project()
    flames = flame_service.list_flames(project)
    if as_json:
        output_json(flames)
        return

    if not flames:
        click.echo("No flames sparked yet. Run 'wyld flame spark <name>' to start prototyping.")
        return

    headers = ["Name", "State", "Versions", "Stokes", "Last Stoke"]
    rows = []
    for f in flames:
        rows.append([
            f["name"],
            f["state"],
            f["version_count"],
            f["stoke_count"],
            f["last_stoke_at"] or "never",
        ])
    click.echo(format_table(headers, rows))


@flame.command("show")
@click.argument("name")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def show_cmd(name: str, as_json: bool):
    """Show details, versions, and stokes for a flame."""
    project = get_current_project()
    data = flame_service.get_flame(project, name)
    if as_json:
        output_json(data)
        return

    click.echo(f"Flame: {data['name']}")
    click.echo(f"State: {data['state']}")
    if data["description"]:
        click.echo(f"Description: {data['description']}")
    if data.get("forked_from"):
        click.echo(f"Forked from: {data['forked_from']}")

    if data.get("materials_path"):
        mat_path = data["materials_path"]
        last_v = data.get("materials_last_version_n", len(data.get("versions", [])))
        if data.get("materials_drifted"):
            click.echo(f"Materials: {mat_path} → DRIFTED since v{last_v}")
        else:
            click.echo(f"Materials: {mat_path} → v{last_v} ✓")

    click.echo("\nVersions:")
    if data["versions"]:
        for v in data["versions"]:
            click.echo(f"  v{v['n']}: {v['notes']} ({v['created_at'][:10]})")
    else:
        click.echo("  none")

    click.echo("\nStokes:")
    if data["stokes"]:
        for s in data["stokes"]:
            ex = " [EXCLUDED]" if s.get("excluded") else ""
            ver_str = f"v{s['version_n']}" if s.get("version_n") else ""
            metrics_str = " ".join(f"{k}={v}" for k, v in s.get("metrics", {}).items())
            notes_str = f'"{s["notes"]}"' if s.get("notes") else ""
            click.echo(f"  #{s['id']} {ver_str} by {s['tester']}: {metrics_str} {notes_str}{ex}")
    else:
        click.echo("  none")


@flame.command("version")
@click.argument("name")
@click.option("--notes", default=None, help="What changed in this iteration")
@click.option("--notes-file", type=click.Path(exists=True, path_type=Path), default=None, help="Read notes from file")
@click.option("--materials", default=None, help="Materials directory (overrides flame's current path)")
def version_cmd(name: str, notes: Optional[str], notes_file: Optional[Path], materials: Optional[str]):
    """Record a new iteration of a flame."""
    project = get_current_project()
    res = flame_service.version_flame(project, name, notes=notes, notes_file=notes_file, materials=materials)
    click.echo(f"→ flame '{res['name']}' is now v{res['version']} ({res['state']})")


@flame.command("stoke")
@click.argument("name")
@click.option("--tester", default="dev", help="Tester name (defaults to dev)")
@click.option("--notes", default=None, help="Session notes")
@click.option("--notes-file", type=click.Path(exists=True, path_type=Path), default=None, help="Read notes from file")
@click.option("--metric", "-m", "metric_pairs", multiple=True, help="Metric value e.g. enjoyment=8")
@click.option("--for", "for_version_str", default=None, help="Record against specific version, bypassing drift (e.g. v5 or 5)")
def stoke_cmd(
    name: str,
    tester: str,
    notes: Optional[str],
    notes_file: Optional[Path],
    metric_pairs: Tuple[str, ...],
    for_version_str: Optional[str],
):
    """Playtest a flame."""
    project = get_current_project()
    metrics = {}
    for pair in metric_pairs:
        if "=" in pair:
            k, v = pair.split("=", 1)
            metrics[k.strip()] = v.strip()

    for_version: Optional[int] = None
    if for_version_str:
        clean = for_version_str.strip().lstrip("vV")
        try:
            for_version = int(clean)
        except ValueError:
            raise click.BadParameter(f"invalid version pin '{for_version_str}'; use e.g. v5 or 5")

    res = flame_service.stoke_flame(
        project,
        name=name,
        tester=tester,
        notes=notes,
        notes_file=notes_file,
        metrics=metrics,
        for_version=for_version,
    )
    pin_str = f" [pinned v{res['pinned_version_n']}]" if res.get("pinned_version_n") else ""
    click.echo(f"→ stoke logged for flame '{name}' (v{res['version']}{pin_str}) by {res['tester']}")
    if res.get("committed_smoke_ids"):
        c_list = ", ".join(f"#{sid}" for sid in res["committed_smoke_ids"])
        click.echo(f"  committed staged smoke: {c_list}")


@flame.command("rename")
@click.argument("old_name")
@click.argument("new_name")
def rename_cmd(old_name: str, new_name: str):
    """Rename a flame (metadata event; version history carries over)."""
    project = get_current_project()
    res = flame_service.rename_flame(project, old_name, new_name)
    click.echo(f"→ renamed flame '{res['old_name']}' to '{res['new_name']}'")


@flame.command("materials")
@click.argument("name")
def materials_cmd(name: str):
    """Reverse lookup: which recorded version matches current materials?"""
    project = get_current_project()
    matches = flame_service.get_flame_materials(project, name)
    if matches:
        click.echo(f"Materials for flame '{name}' match {len(matches)} recorded version(s):")
        for m in matches:
            click.echo(f"  v{m['n']} ({m['created_at'][:10]}): {m['notes']}")
    else:
        click.echo(f"Materials for flame '{name}' do not match any recorded version.")
        click.echo(f"Record a new version with 'wyld flame version {name} --notes \"...\"'")


@flame.command("crown")
@click.argument("name")
@click.option("--note", required=True, help="Why this flame was chosen")
def crown_cmd(name: str, note: str):
    """Mark flame as chosen (terminal state)."""
    project = get_current_project()
    res = flame_service.crown_flame(project, name, note)
    click.echo(f"→ flame '{res['name']}' crowned")


@flame.command("douse")
@click.argument("name")
@click.option("--note", required=True, help="Why this flame was killed/doused")
def douse_cmd(name: str, note: str):
    """Mark flame as killed, kept as lesson (terminal state)."""
    project = get_current_project()
    res = flame_service.douse_flame(project, name, note)
    click.echo(f"→ flame '{res['name']}' doused")
