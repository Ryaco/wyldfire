"""Tests for identity and agent token CLI commands and event attribution."""

import os
import pytest
from click.testing import CliRunner
from wyldfire.cli.main import cli
from wyldfire.core.events import create_event, Event


def test_identity_set_and_show(temp_project, runner, monkeypatch):
    monkeypatch.chdir(temp_project.root_dir)
    result = runner.invoke(cli, ["identity", "set", "--username", "ryan", "--email", "ryan@example.com"])
    assert result.exit_code == 0, result.output
    assert "identity set" in result.output

    result2 = runner.invoke(cli, ["identity", "show"])
    assert result2.exit_code == 0, result2.output
    assert "ryan" in result2.output
    assert "ryan@example.com" in result2.output


def test_token_mint_list_revoke(temp_project, runner, monkeypatch):
    monkeypatch.chdir(temp_project.root_dir)

    result = runner.invoke(cli, ["token", "mint", "--name", "alder"])
    assert result.exit_code == 0, result.output
    assert "minted" in result.output

    result2 = runner.invoke(cli, ["token", "list"])
    assert result2.exit_code == 0, result2.output
    assert "alder" in result2.output

    result3 = runner.invoke(cli, ["token", "revoke", "alder"])
    assert result3.exit_code == 0, result3.output
    assert "revoked" in result3.output

    result4 = runner.invoke(cli, ["token", "list"])
    assert "alder" not in result4.output


def test_token_mint_duplicate_fails(temp_project, runner, monkeypatch):
    monkeypatch.chdir(temp_project.root_dir)
    runner.invoke(cli, ["token", "mint", "--name", "alder"])
    result = runner.invoke(cli, ["token", "mint", "--name", "alder"])
    assert result.exit_code != 0
    assert "already exists" in result.output


def test_event_stamps_identity(temp_project, monkeypatch):
    monkeypatch.chdir(temp_project.root_dir)
    temp_project.config.set("username", "ryan")
    temp_project.config.set("email", "ryan@example.com")

    # Clear environment overrides
    monkeypatch.delenv("WYLD_ACTOR", raising=False)
    monkeypatch.delenv("WYLD_USER", raising=False)
    monkeypatch.delenv("WYLD_AGENT", raising=False)
    monkeypatch.delenv("WYLD_EMAIL", raising=False)

    ev = create_event("test.event", {"hello": "world"})
    assert ev.actor == "ryan"
    assert ev.actor_email == "ryan@example.com"
    assert ev.on_behalf_of == ""


def test_agent_attribution(temp_project, monkeypatch):
    monkeypatch.chdir(temp_project.root_dir)
    temp_project.config.set("username", "GameGrue")

    monkeypatch.setenv("WYLD_AGENT", "1")
    monkeypatch.setenv("WYLD_ACTOR", "Alder")

    ev = create_event("test.event", {"hello": "agent"})
    assert ev.actor == "Alder"
    assert ev.on_behalf_of == "GameGrue"
