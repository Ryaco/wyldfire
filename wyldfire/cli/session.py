"""CLI commands for session management (users build 0.2.0)."""

from typing import Optional
import click

from wyldfire.core import remotes
from wyldfire.services import auth_service


def _session_for(remote_name: Optional[str]):
    name, url = remotes.resolve_remote(remote_name)
    token = auth_service.ensure_session(name, url)
    return name, url, token


@click.group()
def session():
    """List and revoke sessions."""
    pass


@session.command("list")
@click.option("--remote", default=None, help="Remote to list sessions on")
@click.option("--all", "all_sessions", is_flag=True, help="Admin: list every user's sessions")
def list_cmd(remote: Optional[str], all_sessions: bool):
    """List sessions (your own, or all with --all as admin)."""
    _name, url, token = _session_for(remote)
    rows = auth_service.list_sessions(url, token, all_sessions=all_sessions)
    if not rows:
        click.echo("No sessions.")
        return
    for row in rows:
        self_mark = " (this session)" if row.get("self") else ""
        click.echo(f"  {row['id'][:8]}  {row['username']}  valid until {row['expires_at']}"
                   f" (last used {row.get('last_used_at') or 'never'}){self_mark}")


@session.command("revoke")
@click.argument("session_id")
@click.option("--remote", default=None, help="Remote the session belongs to")
def revoke_cmd(session_id: str, remote: Optional[str]):
    """Revoke a session by id (that machine is logged out)."""
    _name, url, token = _session_for(remote)
    auth_service.revoke_session(url, token, session_id)
    click.echo("→ session revoked (that machine is logged out).")


@session.command("revoke-all")
@click.option("--remote", default=None, help="Remote to revoke sessions on")
@click.option("--all", "all_sessions", is_flag=True, help="Admin: revoke every user's sessions and held tokens")
def revoke_all_cmd(remote: Optional[str], all_sessions: bool):
    """Revoke all sessions (and held tokens)."""
    _name, url, token = _session_for(remote)
    res = auth_service.revoke_all_sessions(url, token, all_sessions=all_sessions)
    if all_sessions:
        click.echo("→ all sessions and held tokens revoked (every machine logged out — log in again everywhere).")
    else:
        click.echo(f"→ {res.get('sessions_revoked', 0)} session(s) and {res.get('user_tokens_revoked', 0)} held token(s) revoked.")
