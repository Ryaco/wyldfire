"""CLI commands for `wyld remote` — the server group (users build 0.2.0).

Remotes are global (not per-project). Auth commands live here: login,
signup, logout. Top-level `wyld login` / `logout` / `signup` from 0.1.2
are replaced (pre-1.0 breaking change, no aliases).
"""

from typing import Optional
import click

from wyldfire.core import credentials as creds
from wyldfire.core import remotes
from wyldfire.core.exceptions import WyldError
from wyldfire.core.totp import new_totp_secret, totp_uri, render_totp_qr
from wyldfire.services import auth_service


def _resolve(name: Optional[str], server: Optional[str] = None):
    return remotes.resolve_remote(name, server)


def _enrollment_walk(username: str):
    """TOTP enrollment walk: QR code + text secret, then a confirming code.

    Returns (secret, code). The server verifies the code before storing
    the secret — the CLI never decides enrollment itself.
    """
    secret = new_totp_secret()
    click.echo("→ scan this QR code with your authenticator app, or enter the secret manually:")
    qr = render_totp_qr(totp_uri(secret, username))
    if qr:
        click.echo(qr)
    else:
        click.echo("  (terminal too narrow for the QR code — use the secret below)")
    click.echo(f"  Secret: {secret}")
    click.echo("→ enter the code from your app to confirm enrollment:")
    code = click.prompt("TOTP code", hide_input=True)
    return secret, code


def _password_twice(prompt_text: str = "Set password") -> str:
    while True:
        first = click.prompt(prompt_text, hide_input=True)
        second = click.prompt("Password (again)", hide_input=True)
        if first == second:
            return first
        click.echo("→ passwords didn't match, try again")


@click.group(invoke_without_command=True)
@click.pass_context
def remote(ctx: click.Context):
    """Manage sync servers (remotes) and log in to them."""
    if ctx.invoked_subcommand is None:
        data = remotes.load_remotes()
        if not data["remotes"]:
            click.echo("No remotes registered. Add one with 'wyld remote add <name> <url>'.")
            return
        stored = creds.load_remote_auth()
        for name in sorted(data["remotes"]):
            url = data["remotes"][name]["url"]
            default_mark = " (default)" if data.get("default") == name else ""
            entry = stored.get(name)
            if entry and auth_service.session_is_valid(entry):
                login_state = f"logged in as {entry.get('username', '?')} ({entry.get('role', '?')})"
            elif entry:
                login_state = "session expired"
            else:
                login_state = "not logged in"
            click.echo(f"  {name}  {url}{default_mark}  {login_state}")


@remote.command("add")
@click.argument("name")
@click.argument("url")
def add_cmd(name: str, url: str):
    """Register a server under a name."""
    res = remotes.add_remote(name, url)
    click.echo(f"→ remote \"{res['name']}\" added ({res['url']}).")


@remote.command("list")
def list_cmd():
    """List registered remotes."""
    data = remotes.load_remotes()
    if not data["remotes"]:
        click.echo("No remotes registered. Add one with 'wyld remote add <name> <url>'.")
        return
    stored = creds.load_remote_auth()
    for name in sorted(data["remotes"]):
        url = data["remotes"][name]["url"]
        default_mark = " (default)" if data.get("default") == name else ""
        entry = stored.get(name)
        if entry and auth_service.session_is_valid(entry):
            login_state = f"logged in as {entry.get('username', '?')} ({entry.get('role', '?')})"
        elif entry:
            login_state = "session expired"
        else:
            login_state = "not logged in"
        click.echo(f"  {name}  {url}{default_mark}  {login_state}")


@remote.command("show")
@click.argument("name")
def show_cmd(name: str):
    """Show a remote: URL, login state, projects using it."""
    data = remotes.load_remotes()
    if name not in data["remotes"]:
        raise WyldError(f"remote '{name}' not found", "list remotes with 'wyld remote'")
    url = data["remotes"][name]["url"]
    click.echo(f"  name: {name} | url: {url}")
    entry = creds.get_remote_auth(name)
    if entry and auth_service.session_is_valid(entry):
        click.echo(f"  login: {entry.get('username', '?')} ({entry.get('role', '?')})"
                   f" (session valid until {entry.get('session_expires_at', '?')})")
    elif entry:
        click.echo("  login: session expired (log in again)")
    else:
        click.echo("  login: not logged in")
    from wyldfire.core.config import load_registry, ProjectConfig
    from pathlib import Path

    using = []
    for project_path in load_registry():
        wyld_dir = Path(project_path) / ".wyld"
        if not wyld_dir.exists():
            continue
        cfg = ProjectConfig(wyld_dir)
        if cfg.get("remote") == name:
            using.append(cfg.get("name") or project_path)
    if using:
        click.echo(f"  projects using this remote: {', '.join(using)}")


@remote.command("set-url")
@click.argument("name")
@click.argument("url")
def set_url_cmd(name: str, url: str):
    """Point a remote at a new URL (stored session cleared — log in again)."""
    res = remotes.set_remote_url(name, url)
    creds.clear_remote_auth(name)
    click.echo(f"→ remote \"{res['name']}\" now points at {res['url']} (stored session cleared — log in again).")


@remote.command("rename")
@click.argument("old")
@click.argument("new")
def rename_cmd(old: str, new: str):
    """Rename a remote (project configs using it are rewritten)."""
    res = remotes.rename_remote(old, new)
    updated = res["updated_projects"]
    if updated:
        click.echo(f"→ remote renamed {old} → {new} ({len(updated)} project config(s) updated: {', '.join(updated)}).")
    else:
        click.echo(f"→ remote renamed {old} → {new}.")


@remote.command("remove")
@click.argument("name")
def remove_cmd(name: str):
    """Remove a remote (stored session and held token deleted)."""
    res = remotes.remove_remote(name)
    creds.clear_remote_auth(name)
    click.echo(f"→ remote \"{res['name']}\" removed (stored session and held token deleted).")


@remote.command("set-default")
@click.argument("name")
def set_default_cmd(name: str):
    """Set the default remote."""
    res = remotes.set_default_remote(name)
    click.echo(f"→ \"{res['name']}\" is now the default remote.")


@remote.command("login")
@click.argument("name", required=False)
@click.option("--admin", "as_admin", is_flag=True, help="Log in as the Wyld admin (master token + TOTP)")
@click.option("--user", "username", default=None, help="Username for a user login")
@click.option("--force", is_flag=True, help="Replace the current session even if still valid")
def login_cmd(name: Optional[str], as_admin: bool, username: Optional[str], force: bool):
    """Log in to a remote (issues a 90-day session; the token is held for silent renewal)."""
    remote_name, url = _resolve(name)
    if not remote_name:
        raise WyldError("cannot log in to an ad-hoc --server URL", "register it first with 'wyld remote add'")
    entry = creds.get_remote_auth(remote_name)
    if entry and auth_service.session_is_valid(entry) and not force:
        click.echo(f"→ already logged in as {entry.get('username', '?')} "
                   f"(session valid until {entry.get('session_expires_at', '?')})")
        return
    if as_admin:
        _login_admin(remote_name, url)
    else:
        _login_user(remote_name, url, username)


def _login_admin(remote_name: str, url: str):
    # Migration: reuse the stored 0.1.2 shared token as the master token.
    master_token = creds.get_legacy_token_for_url(url)
    if master_token:
        click.echo(f"→ using the stored master token for remote \"{remote_name}\" (from the 0.1.2 credentials).")
    else:
        master_token = click.prompt("Master token", hide_input=True)
    try:
        probe = auth_service.admin_login_request(url, master_token)
    except WyldError as e:
        # Users exist and no code was sent yet: prompt for the code.
        if "TOTP code required" in str(e):
            code = click.prompt("TOTP code", hide_input=True)
            result = auth_service.admin_login_request(url, master_token, totp_code=code)
            _finish_admin_login(remote_name, url, master_token, result)
            return
        raise
    if probe.get("status") == "bootstrap_required":
        click.echo("→ master token accepted. No users exist yet — setting up the admin account.")
        username = click.prompt("Set admin username").strip()
        password = _password_twice()
        secret, code = _enrollment_walk(username)
        result = auth_service.admin_login_request(
            url, master_token, username=username, password=password,
            totp_secret=secret, totp_code=code,
        )
        click.echo("→ TOTP enrolled and confirmed.")
        click.echo(f"→ admin user \"{username}\" created.")
        _finish_admin_login(remote_name, url, master_token, result)
        return
    # Probe returned something unexpected; treat it as a login result.
    _finish_admin_login(remote_name, url, master_token, probe)


def _finish_admin_login(remote_name: str, url: str, master_token: str, result: dict):
    user = result.get("user", {})
    auth_service.store_session(remote_name, result, master_token, "master")
    role = user.get("role", "admin")
    click.echo(f"→ logged in to remote \"{remote_name}\" as {user.get('username', 'admin')} ({role}, session valid 90 days, sliding).")
    click.echo(f"→ master token held for remote \"{remote_name}\" (renews sessions silently).")


def _login_user(remote_name: str, url: str, username: Optional[str]):
    if not username:
        username = click.prompt("Username").strip()
    password = click.prompt("Password", hide_input=True)
    code = click.prompt("TOTP code (leave blank if not enrolled yet)", hide_input=True, default="", show_default=False)
    code = code.strip() or None
    try:
        result = auth_service.login_user_request(url, username, password, totp_code=code)
    except WyldError as e:
        if "TOTP code required" in str(e):
            code = click.prompt("TOTP code", hide_input=True)
            result = auth_service.login_user_request(url, username, password, totp_code=code)
        elif "both the secret and a code" in str(e):
            secret, code2 = _enrollment_walk(username)
            result = auth_service.login_user_request(
                url, username, password, totp_code=code2, totp_secret=secret)
            click.echo("→ TOTP enrolled and confirmed.")
        else:
            raise
    if result.get("status") == "totp_enrollment_required":
        click.echo("→ no TOTP enrolled yet — setting it up now (no session until a code verifies).")
        secret, code2 = _enrollment_walk(username)
        result = auth_service.login_user_request(
            url, username, password, totp_code=code2, totp_secret=secret)
        click.echo("→ TOTP enrolled and confirmed.")
    user = result.get("user", {})
    auth_service.store_session(remote_name, result, result["user_token"], "user")
    click.echo(f"→ logged in to remote \"{remote_name}\" as {user.get('username', username)} ({user.get('role', 'member')}, session valid 90 days, sliding).")
    click.echo(f"→ user token held for remote \"{remote_name}\" (renews sessions silently).")


@remote.command("signup")
@click.argument("name", required=False)
def signup_cmd(name: Optional[str]):
    """Request an account on a remote (admin approval required — never instant access)."""
    remote_name, url = _resolve(name)
    if not remote_name:
        raise WyldError("cannot sign up on an ad-hoc --server URL", "register it first with 'wyld remote add'")
    username = click.prompt("Username").strip()
    email = click.prompt("Email").strip()
    password = _password_twice()
    secret = None
    code = None
    if click.confirm("Set up MFA now? (optional — otherwise at first login)", default=True):
        click.echo("→ set up MFA now (optional — otherwise at first login). Scan this QR code or enter the secret manually:")
        secret, code = _enrollment_walk(username)
        click.echo("→ TOTP enrolled (stored with your pending request; it takes effect when the admin approves).")
    result = auth_service.signup_request(url, username, email, password, totp_secret=secret, totp_code=code)
    click.echo(f"→ signup request sent for {username} on remote \"{remote_name}\" (pending admin approval).")
    click.echo("→ you can log in once the admin approves — no access until then.")


@remote.command("logout")
@click.argument("name", required=False)
def logout_cmd(name: Optional[str]):
    """Log out of a remote (session and held token revoked on the server, removed locally)."""
    remote_name, url = _resolve(name)
    if not remote_name:
        raise WyldError("cannot log out of an ad-hoc --server URL", "register it first with 'wyld remote add'")
    entry = creds.get_remote_auth(remote_name)
    if not entry:
        click.echo(f"→ not logged in to remote \"{remote_name}\".")
        return
    try:
        auth_service.logout_request(url, entry["session_token"], entry.get("held_token"))
    except WyldError:
        click.echo("→ logged out locally; server unreachable, so the session and token remain valid until revoked — re-run logout when online to revoke them.")
        creds.clear_remote_auth(remote_name)
        return
    creds.clear_remote_auth(remote_name)
    click.echo(f"→ logged out of remote \"{remote_name}\" (session and held token revoked on the server, removed locally).")


@remote.command("rotate-master")
@click.argument("name", required=False)
def rotate_master_cmd(name: Optional[str]):
    """Rotate the master token (hard cutover: the old token dies immediately; user tokens survive)."""
    remote_name, url = _resolve(name)
    if not remote_name:
        raise WyldError("cannot rotate on an ad-hoc --server URL", "register it first with 'wyld remote add'")
    current = click.prompt("Current master token", hide_input=True)
    new = _password_twice("New master token")
    auth_service.rotate_master_request(url, current, new)
    creds.clear_remote_auth(remote_name)
    click.echo(f"→ master token rotated for remote \"{remote_name}\" (old token dead immediately; user tokens survive).")
    click.echo("→ log in again with the new master token.")
