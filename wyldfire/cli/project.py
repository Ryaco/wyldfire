"""CLI commands for project membership (users build 0.2.0).

The membership list lives with the project, gated by project admins; the
creator is automatic Owner. Run inside a project directory.
"""

from typing import Optional
import click

from wyldfire.core import remotes
from wyldfire.core.project import get_current_project
from wyldfire.services import auth_service
from wyldfire.services.sync_service import _project_remote


@click.group()
def project():
    """Project membership (run inside a project)."""
    pass


@project.command("add-member")
@click.argument("username")
@click.option("--role", default="member", help="Role: member or admin (owner is the creator)")
@click.option("--remote", default=None, help="Remote the project lives on")
def add_member_cmd(username: str, role: str, remote: Optional[str]):
    """Add a member to this project (project admin only)."""
    proj = get_current_project()
    name, url = _project_remote(proj, remote)
    token = auth_service.ensure_session(name, url)
    res = auth_service._api(url, "POST", f"/api/v1/projects/{proj.project_id}/members",
                            token=token, body={"username": username.strip(), "role": role})
    click.echo(f"→ {res.get('username')} added to project {proj.name} as {res.get('role')}.")


@project.command("members")
@click.option("--remote", default=None, help="Remote the project lives on")
def members_cmd(remote: Optional[str]):
    """List this project's members."""
    proj = get_current_project()
    name, url = _project_remote(proj, remote)
    token = auth_service.ensure_session(name, url)
    res = auth_service._api(url, "GET", f"/api/v1/projects/{proj.project_id}/members", token=token)
    members = res.get("members", [])
    if not members:
        click.echo("No members.")
        return
    for m in members:
        click.echo(f"  {m['username']} <{m['email']}>  {m['role']}")
