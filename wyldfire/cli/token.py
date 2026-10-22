"""CLI commands for agent token management."""

import uuid
import json
import os
from pathlib import Path
from typing import Optional
import click

from wyldfire.core import config


def _load_tokens() -> dict:
    creds_path = config.get_credentials_path()
    if not creds_path.exists():
        return {}
    try:
        data = json.loads(creds_path.read_text(encoding="utf-8"))
        return data.get("agent_tokens", {})
    except Exception:
        return {}


def _save_tokens(tokens: dict) -> None:
    creds_path = config.get_credentials_path()
    creds_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(creds_path.parent, 0o700)
    except OSError:
        pass
    existing = {}
    if creds_path.exists():
        try:
            existing = json.loads(creds_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    existing["agent_tokens"] = tokens
    creds_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    try:
        os.chmod(creds_path, 0o600)
    except OSError:
        pass


@click.group()
def token():
    """Manage agent tokens (capped at member scope)."""
    pass


@token.command("mint")
@click.option("--name", required=True, help="Name for this agent token (e.g. alder)")
def mint_cmd(name: str):
    """Mint a new agent token bound to your identity."""
    clean_name = name.strip()
    if not clean_name:
        raise click.BadParameter("agent token name cannot be empty")
    tokens = _load_tokens()
    if clean_name in tokens:
        raise click.ClickException(f"agent token '{clean_name}' already exists — revoke it first")
    new_token = str(uuid.uuid4())
    tokens[clean_name] = {"token": new_token, "name": clean_name}
    _save_tokens(tokens)
    click.echo(f"→ agent token '{clean_name}' minted")
    click.echo(f"  Token: {new_token}")
    click.echo("  Scope: member (agents never inherit admin)")
    click.echo(f"  Usage: set WYLD_AGENT=1 and WYLD_ACTOR={clean_name} when using this token")


@token.command("list")
def list_cmd():
    """List all minted agent tokens."""
    tokens = _load_tokens()
    if not tokens:
        click.echo("No agent tokens minted. Run 'wyld token mint --name <name>'")
        return
    click.echo("Agent Tokens:")
    for name, info in tokens.items():
        tok = info.get("token", "")
        masked = tok[:8] + "..." if len(tok) >= 8 else "(empty)"
        click.echo(f"  {name}: {masked}")


@token.command("revoke")
@click.argument("name")
def revoke_cmd(name: str):
    """Revoke an agent token by name."""
    clean_name = name.strip()
    tokens = _load_tokens()
    if clean_name not in tokens:
        raise click.ClickException(f"agent token '{clean_name}' not found")
    del tokens[clean_name]
    _save_tokens(tokens)
    click.echo(f"→ agent token '{clean_name}' revoked")
