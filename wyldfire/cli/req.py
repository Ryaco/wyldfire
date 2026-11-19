"""CLI commands for requests (users build 0.2.0).

Signup requests surface here with the mirror pattern: show the request
before the verdict. Admin commands take --remote and work outside any
project directory.
"""

from typing import Optional
import click

from wyldfire.core import remotes
from wyldfire.services import auth_service


def _session_for(remote_name: Optional[str]):
    name, url = remotes.resolve_remote(remote_name)
    token = auth_service.ensure_session(name, url)
    return name, url, token


@click.group()
def req():
    """Review signup requests (admin)."""
    pass


@req.command("list")
@click.option("--remote", default=None, help="Remote to list requests on")
@click.option("--status", "status_filter", default=None, help="Filter by status (open, approved, denied)")
def list_cmd(remote: Optional[str], status_filter: Optional[str]):
    """List signup requests."""
    _name, url, token = _session_for(remote)
    rows = auth_service.list_requests(url, token, status_filter=status_filter)
    if not rows:
        click.echo("No signup requests.")
        return
    for row in rows:
        click.echo(f"  #{row['id'][:8]}  signup  {row['username']} <{row['email']}>"
                   f"  requested {row['requested_at']}  ({row['status']})")


@req.command("show")
@click.argument("req_id")
@click.option("--remote", default=None, help="Remote the request belongs to")
def show_cmd(req_id: str, remote: Optional[str]):
    """Show a signup request before the verdict."""
    _name, url, token = _session_for(remote)
    row = auth_service.show_request(url, token, req_id)
    click.echo(f"  type: {row.get('type', 'signup')} | username: {row.get('username')} | email: {row.get('email')}")
    click.echo(f"  requested: {row.get('requested_at')}  status: {row.get('status')}")
    if row.get("reason"):
        click.echo(f"  reason: {row['reason']}")


@req.command("approve")
@click.argument("req_id")
@click.option("--remote", default=None, help="Remote the request belongs to")
def approve_cmd(req_id: str, remote: Optional[str]):
    """Approve a signup request (they can now log in)."""
    _name, url, token = _session_for(remote)
    res = auth_service.approve_request(url, token, req_id)
    click.echo(f"→ signup approved for {res.get('username', req_id)} (they can now log in; TOTP enrollment at first login if not already enrolled at signup).")


@req.command("deny")
@click.argument("req_id")
@click.option("--remote", default=None, help="Remote the request belongs to")
@click.option("--reason", default=None, help="Reason for the denial (recorded)")
def deny_cmd(req_id: str, remote: Optional[str], reason: Optional[str]):
    """Deny a signup request (pending account and its TOTP secret deleted)."""
    _name, url, token = _session_for(remote)
    res = auth_service.deny_request(url, token, req_id, reason=reason)
    click.echo(f"→ signup denied for {res.get('username', req_id)} (reason recorded; pending account and its TOTP secret deleted).")
