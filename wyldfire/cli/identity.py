"""CLI commands for identity management."""

import click
from wyldfire.core.project import get_current_project


@click.group()
def identity():
    """Manage local author identity (stamped on events)."""
    pass


@identity.command("set")
@click.option("--username", required=True, help="Your Wyldfire username")
@click.option("--email", required=True, help="Your email address")
def set_cmd(username: str, email: str):
    """Set local identity for event attribution."""
    project = get_current_project()
    project.config.set("username", username.strip())
    project.config.set("email", email.strip())
    click.echo(f"→ identity set: {username.strip()} <{email.strip()}>")


@identity.command("show")
def show_cmd():
    """Show current identity (the logged-in account when logged in)."""
    project = get_current_project()
    # The logged-in account is the server record, not just local config.
    remote_name = project.config.get("remote")
    if remote_name:
        from wyldfire.core import remotes as _remotes
        from wyldfire.services import auth_service as _auth
        try:
            _name, _url = _remotes.resolve_remote(remote_name)
            entry = _auth.get_stored_auth(_name)
            if entry and _auth.session_is_valid(entry):
                click.echo(f"Username: {entry.get('username', '')}")
                click.echo(f"Email:    {entry.get('email', '') or '(not set)'}")
                click.echo(f"Role:     {entry.get('role', 'member')} (via remote \"{_name}\")")
                return
        except Exception:
            pass
    username = project.config.get("username", "")
    email = project.config.get("email", "")
    if not username and not email:
        click.echo("No identity set. Run 'wyld identity set --username <u> --email <e>'")
        return
    click.echo(f"Username: {username or '(not set)'}")
    click.echo(f"Email:    {email or '(not set)'}")
