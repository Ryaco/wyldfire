"""CLI commands for gate (the three-part qualification process & laps)."""

from typing import Optional
import click

from wyldfire.core.project import get_current_project
from wyldfire.cli.formatters import output_json
from wyldfire.services import gate_service, fire_service


@click.group()
def gate():
    """Gate: the three-part qualification into and through production."""
    pass


@gate.command("status")
@click.option("--fire", "fire_name", default=None, help="Target fire")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def status_cmd(fire_name: Optional[str], as_json: bool):
    """Show status and provenance of each gate check."""
    project = get_current_project()
    res = gate_service.get_gate_status(project, fire_name)
    if as_json:
        output_json(res)
        return

    click.echo(f"Gate checks for fire '{res['fire']}' (phase: {res['phase']}):")
    for c in res["checks"]:
        mark = click.style("✓", fg="green") if c["passed"] else click.style("✗", fg="red")
        prov = f" [{c['provenance']}]" if c.get("provenance") != "default" else ""
        click.echo(f"  {mark} {c['label']}: {c['detail']}{prov}")

    if res["all_passed"]:
        click.echo("\nAll checks passing. Run 'wyld gate open' to proceed.")
    else:
        click.echo("\nThe gate holds. Resolve the failing checks above or waive with a reason.")


@gate.command("open")
@click.option("--fire", "fire_name", default=None, help="Target fire")
def open_cmd(fire_name: Optional[str]):
    """Attempt Part 1 verdict (or starts a lap on a passed fire)."""
    project = get_current_project()
    target = fire_service.resolve_fire_name(project, fire_name)
    res = gate_service.open_gate(project, target)

    if res["verdict"] == "pass":
        lap_str = f" (Lap {res['lap_no']})" if res.get("is_lap") else ""
        click.echo(f"→ Production point reached{lap_str}! Phase: {res['phase']}")
        if res.get("pinned_versions"):
            pins = ", ".join(f"{k} pinned at v{v}" for k, v in res["pinned_versions"].items())
            click.echo(f"  {pins}")
    else:
        lap_str = f" on lap {res['lap_no']}" if res.get("is_lap") else ""
        click.echo(f"→ The gate holds{lap_str}. Phase: {res['phase']}")
        click.echo("  Reasons:")
        for r in res.get("reasons", []):
            click.echo(f"  - {r}")


@gate.command("config")
@click.option("--fire", "fire_name", default=None, help="Target fire")
@click.option("--min-stokes", type=int, default=None, help="Minimum non-empty stokes required")
@click.option("--blocked-severity", type=int, default=None, help="Severity threshold that blocks gate")
def config_cmd(fire_name: Optional[str], min_stokes: Optional[int], blocked_severity: Optional[int]):
    """Show or update gate configuration thresholds."""
    project = get_current_project()
    res = gate_service.config_gate(
        project,
        fire_name=fire_name,
        min_stokes=min_stokes,
        blocked_severity=blocked_severity,
    )
    click.echo(f"Gate config for '{res['fire']}': min_stokes={res['min_stokes']}, blocked_severity={res['blocked_severity']}")


@gate.command("attest-scope")
@click.option("--note", required=True, help="Developer attestation that composition covers the game")
@click.option("--fire", "fire_name", default=None, help="Target fire")
def attest_scope_cmd(note: str, fire_name: Optional[str]):
    """Attest that the fire composition covers the whole game scope."""
    project = get_current_project()
    res = gate_service.attest_scope(project, note, fire_name=fire_name)
    click.echo(f"→ scope attested for fire '{res['fire']}': \"{res['note']}\"")


@gate.command("exclude-stoke")
@click.argument("stoke_id", type=int)
@click.option("--reason", required=True, help="Reason for excluding stoke from gate evidence")
@click.option("--fire", "fire_name", default=None, help="Target fire")
def exclude_stoke_cmd(stoke_id: int, reason: str, fire_name: Optional[str]):
    """Exclude a stoke from gate evidence calculation with recorded reason."""
    project = get_current_project()
    res = gate_service.exclude_stoke(project, stoke_id, reason, fire_name=fire_name)
    click.echo(f"→ excluded stoke #{res['stoke_id']} from gate evidence for '{res['fire']}'")


@gate.command("waive")
@click.argument("check_name")
@click.option("--reason", required=True, help="Reason for waiving this check")
@click.option("--fire", "fire_name", default=None, help="Target fire")
def waive_cmd(check_name: str, reason: str, fire_name: Optional[str]):
    """Waive a failing gate check with a recorded reason."""
    project = get_current_project()
    res = gate_service.waive_check(project, check_name, reason, fire_name=fire_name)
    click.echo(f"→ check '{res['check_name']}' waived for fire '{res['fire']}' (reason: {res['reason']})")


@gate.group("slice")
def slice_group():
    """Vertical slice management (Gate Part 2)."""
    pass


@slice_group.command("set")
@click.option("--bundles", required=True, help="Comma-separated bundle names comprising the slice")
@click.option("--fire", "fire_name", default=None, help="Target fire")
def slice_set_cmd(bundles: str, fire_name: Optional[str]):
    """Designate head bundles of the wick as vertical slice."""
    project = get_current_project()
    b_list = [b.strip() for b in bundles.split(",") if b.strip()]
    res = gate_service.set_slice_bundles(project, b_list, fire_name=fire_name)
    click.echo(f"→ vertical slice designated for fire '{res['fire']}': {', '.join(res['bundles'])}")


@gate.command("slice-done")
@click.option("--note", required=True, help="Pitch-ready attestation note")
@click.option("--fire", "fire_name", default=None, help="Target fire")
def slice_done_cmd(note: str, fire_name: Optional[str]):
    """Part 2 exit: slice built, stoked, and attested."""
    project = get_current_project()
    res = gate_service.finish_slice(project, note, fire_name=fire_name)
    click.echo(f"→ vertical slice complete for fire '{res['fire']}'. Phase: {res['phase']}")


@gate.command("plan-done")
@click.option("--note", required=True, help="Attestation note that plan covers iteration 1")
@click.option("--fire", "fire_name", default=None, help="Target fire")
def plan_done_cmd(note: str, fire_name: Optional[str]):
    """Part 3 exit: content plan verified, advancing to production."""
    project = get_current_project()
    res = gate_service.finish_plan(project, note, fire_name=fire_name)
    click.echo(f"→ content plan complete for fire '{res['fire']}'. Phase: {res['phase']}")


@gate.command("laps")
@click.option("--fire", "fire_name", default=None, help="Target fire")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def laps_cmd(fire_name: Optional[str], as_json: bool):
    """Show lap history (numbered re-gates)."""
    project = get_current_project()
    laps = gate_service.list_laps(project, fire_name)
    if as_json:
        output_json(laps)
        return

    if not laps:
        click.echo("No laps run for this fire yet.")
        return

    click.echo("Lap History:")
    for l in laps:
        reasons_str = f" (Reasons: {', '.join(l['reasons'])})" if l["reasons"] else ""
        click.echo(f"  Lap {l['lap_no']}: {l['verdict']} on {l['created_at'][:19]}{reasons_str}")
