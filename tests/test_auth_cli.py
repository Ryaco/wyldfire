"""End-to-end CLI auth test (users build 0.2.0).

Spins up the real FastAPI server on localhost (uvicorn, in-process) and
drives the real CLI through it: remote add, admin bootstrap login,
signup, approval, user login, agent token mint, project link and sync.

The CLI generates TOTP secrets during enrollment; the test pins the
secret to a known value so it can feed valid codes through stdin.
"""

import threading
import time
from pathlib import Path

import pyotp
import pytest
import uvicorn
from click.testing import CliRunner

from wyldfire.cli.main import cli
from wyldfire.server import db as server_db

MASTER = "test-master-token-that-is-long-enough"
ADMIN_PASSWORD = "correct horse battery staple"
USER_PASSWORD = "another correct horse staple"
KNOWN_SECRET = "JBSWY3DPEHPK3PXPKRSCX3DMJBSWY3D"  # pinned TOTP secret for the CLI enrollment walks


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("server-data")
    import os
    os.environ["WYLD_SERVER_TOKEN"] = MASTER
    import wyldfire.server.config as s_config

    s_config.DATA_DIR = tmp
    s_config.DB_PATH = tmp / "server.db"
    from wyldfire.server.app import create_app

    app = create_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started, "uvicorn did not start"
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
def cli_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, live_server: str):
    monkeypatch.setattr(
        "wyldfire.core.config.get_global_wyld_dir", lambda: tmp_path / ".global_wyld"
    )
    monkeypatch.setattr(
        "wyldfire.core.config.get_credentials_path",
        lambda: tmp_path / ".global_config" / "credentials",
    )
    # Pin the CLI's TOTP secret so the test can compute valid codes.
    monkeypatch.setattr("wyldfire.cli.remote.new_totp_secret", lambda: KNOWN_SECRET)
    monkeypatch.chdir(tmp_path)
    return live_server


def _code():
    return pyotp.TOTP(KNOWN_SECRET).now()


def test_full_auth_flow_e2e(cli_env, runner):
    url = cli_env

    r = runner.invoke(cli, ["remote", "add", "main", url])
    assert r.exit_code == 0, r.output

    # Admin bootstrap login: master token, username, password x2, TOTP code.
    r = runner.invoke(
        cli, ["remote", "login", "main", "--admin"],
        input=f"{MASTER}\nGameGrue\n{ADMIN_PASSWORD}\n{ADMIN_PASSWORD}\n{_code()}\n",
    )
    assert r.exit_code == 0, r.output
    assert 'logged in to remote "main" as GameGrue (admin' in r.output
    assert "admin user \"GameGrue\" created" in r.output

    # Signup with MFA at signup time.
    r = runner.invoke(
        cli, ["remote", "signup", "main"],
        input=f"ryan\nrj.cupar@gmail.com\n{USER_PASSWORD}\n{USER_PASSWORD}\ny\n{_code()}\n",
    )
    assert r.exit_code == 0, r.output
    assert "pending admin approval" in r.output

    # Admin approves the request.
    req_id = server_db.list_signup_requests(status="open")[0]["id"]
    r = runner.invoke(cli, ["req", "approve", req_id, "--remote", "main"])
    assert r.exit_code == 0, r.output
    assert "signup approved for ryan" in r.output

    # The admin logs out (different machine in real life — same config
    # file here, so the stored session must be cleared before the user
    # can log in).
    r = runner.invoke(cli, ["remote", "logout", "main"])
    assert r.exit_code == 0, r.output
    assert "logged out of remote" in r.output

    # User login with the enrolled TOTP code.
    r = runner.invoke(
        cli, ["remote", "login", "main"],
        input=f"ryan\n{USER_PASSWORD}\n{_code()}\n",
    )
    assert r.exit_code == 0, r.output
    assert 'logged in to remote "main" as ryan (member' in r.output

    # Agent token mint (server-registered, shown once).
    r = runner.invoke(cli, ["token", "mint", "--name", "alder"])
    assert r.exit_code == 0, r.output
    assert "wyld_at_" in r.output

    # Project link + sync round trip.
    r = runner.invoke(cli, ["init", "ember_tdl"])
    assert r.exit_code == 0, r.output
    import os

    os.chdir("ember_tdl")
    r = runner.invoke(cli, ["link", "--remote", "main"])
    assert r.exit_code == 0, r.output
    assert 'linked to remote "main"' in r.output
    assert "as ryan (member)" in r.output

    r = runner.invoke(cli, ["flame", "spark", "warden", "--desc", "yellow hero"])
    assert r.exit_code == 0, r.output
    r = runner.invoke(cli, ["sync"])
    assert r.exit_code == 0, r.output
    assert 'synced as ryan (member) via remote "main"' in r.output
    assert "Pushed: 1 local events (1 accepted" in r.output

    # The server actually holds the event, stamped with the user identity.
    from wyldfire.core.project import Project

    proj = Project(Path.cwd())
    events = server_db.get_events(proj.project_id)
    assert len(events) == 1
    assert events[0]["actor"] == "ryan"
    assert events[0]["actor_email"] == "rj.cupar@gmail.com"

    # Status shows the login identity.
    r = runner.invoke(cli, ["status"])
    assert r.exit_code == 0, r.output
    assert 'logged in as ryan (member) via remote "main"' in r.output


def test_remote_login_wrong_password(cli_env, runner):
    url = cli_env
    runner.invoke(cli, ["remote", "add", "main", url])
    runner.invoke(
        cli, ["remote", "login", "main", "--admin"],
        input=f"{MASTER}\nGameGrue\n{ADMIN_PASSWORD}\n{ADMIN_PASSWORD}\n{_code()}\n",
    )
    # User login for a nonexistent account: generic error, no leak.
    # --force: the admin session from above is still stored.
    r = runner.invoke(
        cli, ["remote", "login", "main", "--force"],
        input=f"nobody\nwrong-password\n\n",
    )
    assert r.exit_code != 0
    assert "incorrect username or password" in r.output
