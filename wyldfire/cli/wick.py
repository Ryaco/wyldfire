"""CLI commands for wick (content burn-down)."""

from typing import Optional, Tuple
import click

from wyldfire.core.project import get_current_project
from wyldfire.cli.formatters import output_json, format_table
from wyldfire.services import wick_service


@click.group()
def wick():
    """Wick: the ordered depth-first content burn-down."""
    pass


@wick.command("plan")
@click.option("--fire", "fire_name", default=None, help="Target fire")
def plan_cmd(fire_name: Optional[str]):
    """Initialize the wick for a fire."""
    project = get_current_project()
    res = wick_service.plan_wick(project, fire_name)
    click.echo(f"→ {res['message']}")


@wick.group("bundle")
def bundle_group():
    """Bundle scope units."""
    pass


@bundle_group.command("add")
@click.argument("name")
@click.option("--under", default=None, help="Parent bundle name")
@click.option("--meta", "-m", "meta_pairs", multiple=True, help="Metadata key=value")
@click.option("--template", "-t", "template_name", default=None, help="Instantiate from template")
@click.option("--fire", "fire_name", default=None, help="Target fire")
def bundle_add_cmd(
    name: str,
    under: Optional[str],
    meta_pairs: Tuple[str, ...],
    template_name: Optional[str],
    fire_name: Optional[str],
):
    """Add a new bundle to the wick."""
    project = get_current_project()
    metadata = {}
    for pair in meta_pairs:
        if "=" in pair:
            k, v = pair.split("=", 1)
            metadata[k.strip()] = v.strip()

    res = wick_service.add_bundle(
        project,
        name=name,
        parent=under,
        metadata=metadata,
        template_name=template_name,
        fire_name=fire_name,
    )
    under_str = f" under '{under}'" if under else ""
    click.echo(f"→ bundle '{res['name']}' added{under_str}")
    if res.get("instantiated_subbundles"):
        click.echo(f"  instantiated sub-bundles: {', '.join(res['instantiated_subbundles'])}")
    if res.get("instantiated_fuels"):
        click.echo(f"  instantiated fuels: {', '.join(res['instantiated_fuels'])}")


@bundle_group.command("define")
@click.argument("name")
@click.option("--meta", "-m", "meta_pairs", multiple=True, help="Metadata key=value")
@click.option("--fire", "fire_name", default=None, help="Target fire")
def bundle_define_cmd(name: str, meta_pairs: Tuple[str, ...], fire_name: Optional[str]):
    """Fill metadata during a define-fuel."""
    project = get_current_project()
    metadata = {}
    for pair in meta_pairs:
        if "=" in pair:
            k, v = pair.split("=", 1)
            metadata[k.strip()] = v.strip()

    res = wick_service.define_bundle_metadata(project, name, metadata, fire_name=fire_name)
    click.echo(f"→ bundle '{res['name']}' defined with metadata: {res['metadata']}")


@bundle_group.command("list")
@click.option("--fire", "fire_name", default=None, help="Target fire")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def bundle_list_cmd(fire_name: Optional[str], as_json: bool):
    """List bundles in tree / depth-first order."""
    project = get_current_project()
    bundles = wick_service.list_bundles_tree(project, fire_name)
    if as_json:
        output_json(bundles)
        return

    if not bundles:
        click.echo("No bundles in the wick yet.")
        return

    headers = ["Bundle", "Cut", "Fuel (Done/Total)", "Metadata"]
    rows = []
    for b in bundles:
        indent = "  " * b.get("depth", 0)
        cut_mark = "[CUT]" if b["cut"] else ""
        meta_str = " ".join(f"{k}={v}" for k, v in b.get("metadata", {}).items())
        fuel_str = f"{b.get('finished_count', 0)}/{b.get('fuel_count', 0)}"
        rows.append([f"{indent}{b['name']}", cut_mark, fuel_str, meta_str])
    click.echo(format_table(headers, rows))


@bundle_group.command("show")
@click.argument("name")
@click.option("--fire", "fire_name", default=None, help="Target fire")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def bundle_show_cmd(name: str, fire_name: Optional[str], as_json: bool):
    """Show details of a bundle."""
    project = get_current_project()
    b = wick_service.get_bundle(project, name, fire_name)
    if as_json:
        output_json(b)
        return

    click.echo(f"Bundle: {b['name']}")
    if b["cut"]:
        click.echo(f"Status: CUT (reason: {b['cut_reason']})")
    if b["metadata"]:
        click.echo("Metadata: " + ", ".join(f"{k}={v}" for k, v in b["metadata"].items()))
    if b["children"]:
        click.echo("Sub-bundles: " + ", ".join(b["children"]))
    click.echo("\nFuels:")
    if b["fuels"]:
        for f in b["fuels"]:
            f_type = f" [{f['type_tag']}]" if f["type_tag"] else ""
            t_str = f" ({f['time_min']}m)" if f["time_min"] else ""
            click.echo(f"  - {f['name']}: {f['state']}{f_type}{t_str}")
    else:
        click.echo("  none")


@wick.group("fuel")
def fuel_group():
    """Fuel content units."""
    pass


@fuel_group.command("add")
@click.argument("name")
@click.option("--to", "bundle", required=True, help="Target bundle name")
@click.option("--type", "-t", "type_tag", default="", help="Fuel type tag (e.g. sprite, audio)")
@click.option("--note", default="", help="Optional note")
@click.option("--fire", "fire_name", default=None, help="Target fire")
def fuel_add_cmd(name: str, bundle: str, type_tag: str, note: str, fire_name: Optional[str]):
    """Add atomic content fuel to a bundle."""
    project = get_current_project()
    res = wick_service.add_fuel(
        project,
        name=name,
        bundle=bundle,
        fuel_kind="task",
        type_tag=type_tag,
        note=note,
        fire_name=fire_name,
    )
    t_str = f" [{res['type_tag']}]" if res["type_tag"] else ""
    click.echo(f"→ fuel '{res['name']}'{t_str} added to bundle '{res['bundle']}'")


@fuel_group.command("define")
@click.argument("bundle")
@click.option("--note", default="", help="What needs to be designed")
@click.option("--fire", "fire_name", default=None, help="Target fire")
def fuel_define_cmd(bundle: str, note: str, fire_name: Optional[str]):
    """Add a define-fuel placeholder for deferred design."""
    project = get_current_project()
    res = wick_service.define_fuel_placeholder(project, bundle=bundle, note=note, fire_name=fire_name)
    click.echo(f"→ define fuel '{res['name']}' added to bundle '{res['bundle']}'")


@wick.command("start")
@click.argument("fuel_name")
@click.option("--fire", "fire_name", default=None, help="Target fire")
def start_cmd(fuel_name: str, fire_name: Optional[str]):
    """Start burning a fuel unit (state: creating)."""
    project = get_current_project()
    res = wick_service.start_fuel(project, fuel_name, fire_name=fire_name)
    click.echo(f"→ fuel '{res['fuel']}' is now creating")


@wick.command("finish")
@click.argument("fuel_name")
@click.option("--note", default=None, help="Optional finishing note")
@click.option("--fire", "fire_name", default=None, help="Target fire")
def finish_cmd(fuel_name: str, note: Optional[str], fire_name: Optional[str]):
    """Finish a fuel unit (state: finished); advances the burn."""
    project = get_current_project()
    res = wick_service.finish_fuel(project, fuel_name, note=note, fire_name=fire_name)
    click.echo(f"→ fuel '{res['fuel']}' finished")


@wick.command("log")
@click.argument("fuel_name")
@click.option("--time", "time_str", required=True, help="Time spent (e.g. 2h30m, 90m, 1.5h)")
@click.option("--fire", "fire_name", default=None, help="Target fire")
def log_cmd(fuel_name: str, time_str: str, fire_name: Optional[str]):
    """Log work time spent on a fuel unit."""
    project = get_current_project()
    res = wick_service.log_fuel_time(project, fuel_name, time_str, fire_name=fire_name)
    click.echo(f"→ logged {res['logged_minutes']}m on '{res['fuel']}' (total: {res['total_time']})")


@wick.command("next")
@click.option("--fire", "fire_name", default=None, help="Target fire")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def next_cmd(fire_name: Optional[str], as_json: bool):
    """Show the current burn position in depth-first traversal."""
    project = get_current_project()
    res = wick_service.get_next_fuel(project, fire_name)
    if as_json:
        output_json(res)
        return

    if not res:
        click.echo("Wick complete! No remaining fuel to burn.")
        return

    t_str = f" [{res['type_tag']}]" if res.get("type_tag") else ""
    click.echo(f"Next fuel: '{res['name']}'{t_str} in bundle '{res['bundle_name']}' (state: {res['state']})")
    if res.get("prompt_define"):
        click.echo("  → This is a define-fuel placeholder! Bundle needs design.")
        click.echo(f"    Define metadata with: wyld wick bundle define \"{res['bundle_name']}\" --meta ...")
        click.echo(f"    Add sub-bundles/fuel, then finish with: wyld wick finish \"{res['name']}\"")


@wick.command("list")
@click.option("--fire", "fire_name", default=None, help="Target fire")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def list_cmd(fire_name: Optional[str], as_json: bool):
    """List full wick traversal with bundles and fuels."""
    project = get_current_project()
    data = wick_service.list_wick_full(project, fire_name)
    if as_json:
        output_json(data)
        return

    if not data:
        click.echo("Wick is empty.")
        return

    for b in data:
        indent = "  " * b.get("depth", 0)
        cut_label = " [CUT]" if b["cut"] else ""
        click.echo(f"{indent}Bundle: {b['name']}{cut_label}")
        for f in b.get("fuels", []):
            f_type = f" [{f['type_tag']}]" if f.get("type_tag") else ""
            t_str = f" ({f['time_min']}m)" if f.get("time_min") else ""
            click.echo(f"{indent}  • {f['name']}: {f['state']}{f_type}{t_str}")


@wick.command("cut")
@click.argument("bundle_name")
@click.option("--reason", required=True, help="Reason why this bundle was cut")
@click.option("--fire", "fire_name", default=None, help="Target fire")
def cut_cmd(bundle_name: str, reason: str, fire_name: Optional[str]):
    """Cut a bundle from the wick (recorded scope reduction)."""
    project = get_current_project()
    res = wick_service.cut_bundle(project, bundle_name, reason, fire_name=fire_name)
    click.echo(f"→ bundle '{res['bundle']}' cut (reason: {res['reason']})")


@wick.command("scope-change")
@click.option("--reason", required=True, help="Reason for scope addition")
@click.option("--fire", "fire_name", default=None, help="Target fire")
def scope_change_cmd(reason: str, fire_name: Optional[str]):
    """Record an explicit content scope change with logged reason and ETA check."""
    project = get_current_project()
    eta_before = wick_service.calculate_eta(project, fire_name)
    res = wick_service.scope_change(project, reason, fire_name=fire_name)
    click.echo(f"→ scope change recorded for fire '{res['fire']}': \"{res['reason']}\"")
    if eta_before.get("status") == "calculated":
        click.echo(f"  current projected finish: {eta_before['projected_finish']} ({eta_before['total_estimated_hours']}h remaining)")


@wick.command("eta")
@click.option("--fire", "fire_name", default=None, help="Target fire")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def eta_cmd(fire_name: Optional[str], as_json: bool):
    """Project finish date from pace and remaining fuel."""
    project = get_current_project()
    res = wick_service.calculate_eta(project, fire_name)
    if as_json:
        output_json(res)
        return

    if res["status"] != "calculated":
        click.echo(res.get("message", "not enough data yet"))
        return

    click.echo(f"Wick ETA for fire '{res['fire']}':")
    for b in res["breakdown"]:
        click.echo(
            f"  → {b['type'].ljust(10)}: {b['finished_count']} finished (avg {b['avg_hours']}h) × {b['remaining_count']} remaining = {b['estimated_hours']}h"
        )
    if res.get("undefined_bundles_count", 0) > 0:
        click.echo(f"  → undefined : {res['undefined_bundles_count']} undefined bundles ≈ {res['undefined_bundles_hours']}h")
    click.echo(f"\nTotal estimated: {res['total_estimated_hours']}h")
    click.echo(f"Projected finish: {res['projected_finish']}")
