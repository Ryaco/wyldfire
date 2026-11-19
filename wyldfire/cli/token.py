"""CLI commands for agent token management (users build 0.2.0).

Minting registers the token server-side (hash stored); the server
validates it on every call. Agent tokens are capped at member scope —
agents never inherit admin — and judgment actions stay refused for them
server-side.
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
def token():
    """Manage agent tokens (capped at member scope)."""
    pass


@token.command("mint")
@click.option("--name", required=True, help="Name for this agent token (e.g. alder)")
@click.option("--remote", default=None, help="Remote to mint the token on")
def mint_cmd(name: str, remote: Optional[str]):
    """Mint a new agent token bound to your identity (shown once)."""
    clean_name = name.strip()
    if not clean_name:
        raise click.BadParameter("agent token name cannot be empty")
    _name, _url, session = _session_for(remote)
    res = auth_service.mint_agent_token(_url, session, clean_name)
    click.echo(f"→ agent token minted for {clean_name} (member scope — agents never inherit admin).")
    click.echo("→ token (shown once — store it securely, it won't be shown again):")
    click.echo(f"  {res['token']}")
    click.echo(f"  Usage: set WYLD_AGENT=1 and WYLD_ACTOR={clean_name} when using this token")


@token.command("list")
@click.option("--remote", default=None, help="Remote to list tokens on")
def list_cmd(remote: Optional[str]):
    """List your agent tokens (with last-used, so stale ones can be pruned)."""
    _name, _url, session = _session_for(remote)
    tokens = auth_service.list_agent_tokens(_url, session)
    if not tokens:
        click.echo("No agent tokens minted. Run 'wyld token mint --name <name>'")
        return
    click.echo("Agent Tokens:")
    for info in tokens:
        last = info.get("last_used") or "never used"
        created = info.get("created", "")
        click.echo(f"  {info['name']}  member  last used {last}  (created {created})")


@token.command("revoke")
@click.argument("name")
@click.option("--remote", default=None, help="Remote to revoke the token on")
def revoke_cmd(name: str, remote: Optional[str]):
    """Revoke an agent token by name."""
    clean_name = name.strip()
    _name, _url, session = _session_for(remote)
    auth_service.revoke_agent_token(_url, session, clean_name)
    click.echo(f"→ agent token {clean_name} revoked (sessions made with it are revoked too).")
