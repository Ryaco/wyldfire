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
from wyldfire.cli.identity import identity
from wyldfire.cli.token import token
from wyldfire.cli.remote import remote
from wyldfire.cli.session import session
from wyldfire.cli.req import req
from wyldfire.cli.project import project as project_group
from wyldfire.cli.sync import link_cmd, sync_cmd, doctor_cmd, clone_cmd


class WyldGroup(click.Group):
    """Click group that formats WyldError cleanly without Python tracebacks."""

    def invoke(self, ctx):
        try:
            return super().invoke(ctx)
        except WyldError as e:
            print_error(str(e))
            ctx.exit(e.exit_code)

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
@click.option("--username", default=None, help="Author username for identity")
@click.option("--email", default=None, help="Author email for identity")
def init_cmd(name: Optional[str], server: Optional[str], username: Optional[str], email: Optional[str]):
    """Initialize a new Wyldfire project in the current directory."""
    cwd = Path.cwd()
    if name and cwd.name != name and not (cwd / ".wyld").exists():
        target_dir = cwd / name
        target_dir.mkdir(parents=True, exist_ok=True)
    else:
        target_dir = cwd

    if (target_dir / ".wyld").exists():
        if server:
            from wyldfire.core.project import Project
            project = Project(target_dir)
            project.config.set("server_url", server.rstrip("/"))
            click.echo(f"Updated server URL for project '{project.name}' to {server.rstrip('/')}")
            return
        else:
            raise WyldError(
                f"project already initialized at {target_dir}",
                "cd to the directory and run 'wyld status', or use 'wyld init --server <url>' to set server URL",
            )

    project = init_project(target_dir, name=name, server_url=server)
    if username:
        project.config.set("username", username.strip())
    if email:
        project.config.set("email", email.strip())
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
    # Login identity for this project's remote (if any).
    try:
        from wyldfire.core import remotes as _remotes
        from wyldfire.services import auth_service as _auth
        _remote_name = project.config.get("remote")
        if _remote_name:
            _name, _url = _remotes.resolve_remote(_remote_name)
            _entry = _auth.get_stored_auth(_name)
            if _entry and _auth.session_is_valid(_entry):
                click.echo(f"→ logged in as {_entry.get('username', '?')} ({_entry.get('role', '?')}) via remote \"{_name}\" ({_url})")
            else:
                click.echo("→ not logged in")
    except Exception:
        pass
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

    if data.get("drifted_flames"):
        click.echo("\nDrifted Flames:")
        for df in data["drifted_flames"]:
            click.echo(f"  ✗ '{df['name']}' materials changed since v{df['last_version_n']} ({df['materials_path']})")


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
cli.add_command(identity)
cli.add_command(token)
cli.add_command(remote)
cli.add_command(session)
cli.add_command(req)
cli.add_command(project_group)

# Register sync commands
cli.add_command(clone_cmd)
cli.add_command(link_cmd)
cli.add_command(sync_cmd)
cli.add_command(doctor_cmd)


if __name__ == "__main__":
    cli()
