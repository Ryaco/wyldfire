"""CLI integration tests using Click runner."""

from click.testing import CliRunner
from wyldfire.cli.main import cli


def test_cli_basic_workflow(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    global_wyld = tmp_path / ".global_wyld"
    global_config = tmp_path / ".global_config"
    monkeypatch.setattr("wyldfire.core.config.get_global_wyld_dir", lambda: global_wyld)
    monkeypatch.setattr("wyldfire.core.config.get_credentials_path", lambda: global_config / "credentials")

    runner = CliRunner()

    # wyld init
    r = runner.invoke(cli, ["init", "cli-game"])
    assert r.exit_code == 0
    assert "Initialized Wyldfire project" in r.output

    monkeypatch.chdir(tmp_path / "cli-game")

    # wyld status
    r = runner.invoke(cli, ["status"])
    assert r.exit_code == 0
    assert "Project: cli-game" in r.output

    # wyld flame spark
    r = runner.invoke(cli, ["flame", "spark", "jump", "--desc", "jumping mechanic"])
    assert r.exit_code == 0
    assert "sparked (v1)" in r.output

    # wyld flame list
    r = runner.invoke(cli, ["flame", "list"])
    assert r.exit_code == 0
    assert "jump" in r.output

    # wyld flame version
    r = runner.invoke(cli, ["flame", "version", "jump", "--notes", "variable jump height"])
    assert r.exit_code == 0
    assert "v2" in r.output

    # wyld metric define
    r = runner.invoke(cli, ["metric", "define", "fun", "--prompt", "How fun 1-10?", "--type", "number"])
    assert r.exit_code == 0
    assert "fun" in r.output

    # wyld flame stoke
    r = runner.invoke(cli, ["flame", "stoke", "jump", "--tester", "Alice", "--metric", "fun=9", "--notes", "felt great"])
    assert r.exit_code == 0
    assert "stoke logged" in r.output

    # wyld smoke stage and stoke commit
    r = runner.invoke(cli, ["smoke", "stage", "jump buffering bug", "--on", "flame/jump", "--severity", "2"])
    assert r.exit_code == 0
    assert "staged" in r.output

    r = runner.invoke(cli, ["flame", "stoke", "jump", "--tester", "Bob", "--notes", "found the buffer bug"])
    assert r.exit_code == 0
    assert "committed staged smoke" in r.output

    # wyld ember bank
    r = runner.invoke(cli, ["ember", "bank", "ice world", "--note", "slippery physics"])
    assert r.exit_code == 0
    assert "banked" in r.output

    # wyld template new
    r = runner.invoke(cli, ["template", "new", "level", "--bundles", "room x3", "--fuels", "tile:sprite, theme:audio"])
    assert r.exit_code == 0
    assert "template 'level' created" in r.output

    # wyld template list --json
    r = runner.invoke(cli, ["template", "list", "--json"])
    assert r.exit_code == 0
    assert '"name": "level"' in r.output

    # wyld fire start and checkout
    r = runner.invoke(cli, ["fire", "start", "platformer", "--flames", "jump", "--desc", "core platformer"])
    assert r.exit_code == 0
    assert "platformer" in r.output

    r = runner.invoke(cli, ["fire", "checkout", "platformer"])
    assert r.exit_code == 0
    assert "checked out fire 'platformer'" in r.output

    # wyld fire set-loop and add-toy
    r = runner.invoke(cli, ["fire", "set-loop", "run -> jump -> collect -> flag"])
    assert r.exit_code == 0

    r = runner.invoke(cli, ["fire", "add-toy", "precision wall jump"])
    assert r.exit_code == 0

    # wyld gate attest-scope and status
    r = runner.invoke(cli, ["gate", "attest-scope", "--note", "platformer scope is complete"])
    assert r.exit_code == 0

    r = runner.invoke(cli, ["gate", "status"])
    assert r.exit_code == 0

    # wyld gate config
    r = runner.invoke(cli, ["gate", "config", "--min-stokes", "2"])
    assert r.exit_code == 0

    # wyld gate waive ember check
    r = runner.invoke(cli, ["gate", "waive", "embers", "--reason", "ice world is for sequel"])
    assert r.exit_code == 0

    # clear smoke #1
    r = runner.invoke(cli, ["smoke", "clear", "1", "--note", "fixed buffer window"])
    assert r.exit_code == 0

    # wyld gate open
    r = runner.invoke(cli, ["gate", "open"])
    assert r.exit_code == 0
    assert "Production point reached" in r.output

    # wyld wick plan and bundle add
    r = runner.invoke(cli, ["wick", "plan"])
    assert r.exit_code == 0

    r = runner.invoke(cli, ["gate", "slice", "set", "--bundles", "world 1"])
    assert r.exit_code == 0

    r = runner.invoke(cli, ["wick", "bundle", "add", "world 1", "--meta", "theme=grassland"])
    assert r.exit_code == 0

    r = runner.invoke(cli, ["wick", "fuel", "add", "player sprite", "--to", "world 1", "--type", "sprite"])
    assert r.exit_code == 0

    r = runner.invoke(cli, ["wick", "start", "player sprite"])
    assert r.exit_code == 0

    r = runner.invoke(cli, ["wick", "log", "player sprite", "--time", "1h30m"])
    assert r.exit_code == 0

    r = runner.invoke(cli, ["wick", "finish", "player sprite"])
    assert r.exit_code == 0

    r = runner.invoke(cli, ["wick", "eta"])
    assert r.exit_code == 0

    # wyld snapshot
    r = runner.invoke(cli, ["snapshot"])
    assert r.exit_code == 0
    assert "snapshot created" in r.output

    # wyld login and logout
    r = runner.invoke(cli, ["login", "--server", "https://wyld.example.com", "--token", "test-token"])
    assert r.exit_code == 0
    assert "credentials stored" in r.output

    r = runner.invoke(cli, ["logout"])
    assert r.exit_code == 0

    # wyld doctor
    r = runner.invoke(cli, ["doctor"])
    assert r.exit_code == 0
