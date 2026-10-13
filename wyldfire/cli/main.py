"""Root CLI entrypoint for Wyldfire."""

from pathlib import Path
import shutil
import sys
from typing import Optional
import click

from wyldfire.core.exceptions import WyldError
from wyldfire.core.project import init_project, get_current_project
from wyldfire.core.time_utils import timestamp_for_filename
from wyldfire.cli.formatters import output_json, format_table, print_error
from wyldfire.services import status_service

# Subcommand groups
from wyldfire.cli.flame import flame
from wyldfire.cli.smoke import smoke
from wyldfire.cli.ember import ember
from wyldfire.cli.fire import fire
from wyldfire.cli.gate import gate
from wyldfire.cli.wick import wick
from wyldfire.cli.template import template
from wyldfire.cli.tester import tester
from wyldfire.cli.metric import metric
from wyldfire.cli.sync import login_cmd, logout_cmd, link_cmd, sync_cmd, doctor_cmd


class WyldGroup(click.Group):
    """Click group that formats WyldError cleanly without Python tracebacks."""

    def __call__(self, *args, **kwargs):
        try:
            return super().__call__(*args, **kwargs)
        except WyldError as e:
            print_error(str(e))
            sys.exit(e.exit_code)
        except click.ClickException as e:
            # Let click handle its own exceptions
            e.show()
            sys.exit(e.exit_code)
        except Exception as e:
            # Unexpected system error
            if sys.flags.debug or "PYTEST_CURRENT_TEST" in sys.modules:
                raise
            print_error(f"Error: unexpected error: {e}")
            sys.exit(1)


@click.group(cls=WyldGroup)
@click.version_option(package_name="wyldfire")
def cli():
    """Wyldfire: opinionated FSM for solo indie game developers."""
    pass


@cli.command("init")
@click.argument("name", required=False)
@click.option("--server", default=None, help="Remote sync server URL")
def init_cmd(name: Optional[str], server: Optional[str]):
    """Initialize a new Wyldfire project in the current directory."""
    cwd = Path.cwd()
    if name and cwd.name != name and not (cwd / ".wyld").exists():
        target_dir = cwd / name
        target_dir.mkdir(parents=True, exist_ok=True)
    else:
        target_dir = cwd
    project = init_project(target_dir, name=name, server_url=server)
    click.echo(f"Initialized Wyldfire project '{project.name}' in {target_dir}")


@cli.command("status")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def status_cmd(as_json: bool):
    """Dashboard: fires, current phase, wick position, and open smoke."""
    project = get_current_project()
    data = status_service.get_project_status(project)
    if as_json:
        output_json(data)
        return

    click.echo(f"Project: {data['project_name']}")
    if data["checked_out_fire"]:
        click.echo(f"Focus fire: {data['checked_out_fire']}")
    else:
        click.echo("Focus fire: none (use 'wyld fire checkout <name>')")

    click.echo("\nFires:")
    if data["fires"]:
        f_headers = ["Current", "Name", "Phase", "Flames"]
        f_rows = []
        for f in data["fires"]:
            c_star = "*" if f["is_current"] else " "
            f_rows.append([c_star, f["name"], f["phase"], f["flame_count"]])
        click.echo(format_table(f_headers, f_rows))
    else:
        click.echo("  none started yet")

    click.echo("\nWick Position:")
    if data["wick_next"]:
        nx = data["wick_next"]
        f_type = f" [{nx['type_tag']}]" if nx.get("type_tag") else ""
        click.echo(f"  → '{nx['name']}'{f_type} in bundle '{nx['bundle_name']}' ({nx['state']})")
    else:
        click.echo("  none")

    click.echo("\nIssues:")
    sm = data["open_smoke"]
    click.echo(f"  Critical (sev 3): {sm.get(3, 0)}  |  Problem (sev 2): {sm.get(2, 0)}  |  Polish (sev 1): {sm.get(1, 0)}")
    if data.get("staged_smoke_count", 0) > 0:
        click.echo(f"  Staged: {data['staged_smoke_count']} awaiting stoke commit")
    click.echo(f"Banked Embers: {data['banked_embers_count']}")


@cli.command("snapshot")
def snapshot_cmd():
    """Create a point-in-time projection snapshot."""
    project = get_current_project()
    # Replay all events first
    project.store.replay_all()
    project.snapshots_dir.mkdir(parents=True, exist_ok=True)
    snap_name = f"snapshot-{timestamp_for_filename()}.db"
    dest = project.snapshots_dir / snap_name
    shutil.copy2(project.db_path, dest)
    click.echo(f"→ snapshot created at .wyld/snapshots/{snap_name}")


# Register subcommand groups
cli.add_command(flame)
cli.add_command(smoke)
cli.add_command(ember)
cli.add_command(fire)
cli.add_command(gate)
cli.add_command(wick)
cli.add_command(template)
cli.add_command(tester)
cli.add_command(metric)

# Register sync commands
cli.add_command(login_cmd)
cli.add_command(logout_cmd)
cli.add_command(link_cmd)
cli.add_command(sync_cmd)
cli.add_command(doctor_cmd)


if __name__ == "__main__":
    cli()
