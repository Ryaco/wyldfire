"""Tests for fire thesis declaration and gate Part 1 thesis check."""

import pytest
from wyldfire.core.constants import PHASE_PROTOTYPE, PHASE_GATE_PART2
from wyldfire.core.exceptions import WyldError
from wyldfire.services import flame_service, fire_service, gate_service
from wyldfire.cli.main import cli


def _setup_fire(project):
    flame_service.spark_flame(project, "core_flame")
    fire_service.start_fire(project, "my_game", flames=["core_flame"])
    fire_service.checkout_fire(project, "my_game")


def test_set_thesis_basic(temp_project):
    _setup_fire(temp_project)
    res = fire_service.set_thesis(
        temp_project,
        origin="a solid card battler mechanic looking for a full game",
        statement="This game argues that deck manipulation is more satisfying than luck reduction.",
    )
    assert res["fire"] == "my_game"
    assert "card battler" in res["origin"]
    assert "deck manipulation" in res["statement"]

    data = fire_service.get_fire(temp_project, "my_game")
    assert data["thesis_origin"] == res["origin"]
    assert data["thesis_statement"] == res["statement"]


def test_set_thesis_file(temp_project):
    _setup_fire(temp_project)
    stmt_file = temp_project.root_dir / "thesis.md"
    stmt_file.write_text("Long form argument for why this mechanic matters.")

    res = fire_service.set_thesis(
        temp_project,
        origin="narrative-first",
        statement_file=stmt_file,
    )
    assert res["origin"] == "narrative-first"
    assert "Long form argument" in res["statement"]


def test_thesis_required_at_gate_part1(temp_project):
    _setup_fire(temp_project)

    # Waive everything except thesis
    for check_name in ("playtest", "core_loop", "toys", "scope", "smoke", "embers"):
        gate_service.waive_check(temp_project, check_name, reason="speedrun")

    status = gate_service.get_gate_status(temp_project, "my_game")
    thesis_check = next(c for c in status["checks"] if c["name"] == "thesis")
    assert not thesis_check["passed"]
    assert not status["all_passed"]


def test_thesis_check_passes_when_declared(temp_project):
    _setup_fire(temp_project)
    fire_service.set_thesis(temp_project, origin="mechanics-first")

    status = gate_service.get_gate_status(temp_project, "my_game")
    thesis_check = next(c for c in status["checks"] if c["name"] == "thesis")
    assert thesis_check["passed"]


def test_thesis_check_waiveable(temp_project):
    _setup_fire(temp_project)
    gate_service.waive_check(temp_project, "thesis", reason="skipping for speedrun")

    status = gate_service.get_gate_status(temp_project, "my_game")
    thesis_check = next(c for c in status["checks"] if c["name"] == "thesis")
    assert thesis_check["passed"]
    assert "waived" in thesis_check["provenance"]


def test_thesis_locked_after_gate_part1(temp_project):
    _setup_fire(temp_project)
    fire_service.set_thesis(temp_project, origin="mechanics-first", statement="It argues fun > complexity.")

    # Waive all other checks
    for check_name in ("playtest", "core_loop", "toys", "scope", "smoke", "embers"):
        gate_service.waive_check(temp_project, check_name, reason="speedrun")

    res = gate_service.open_gate(temp_project, "my_game")
    assert res["verdict"] == "pass"

    data = fire_service.get_fire(temp_project, "my_game")
    assert data.get("thesis_locked_at") is not None


def test_thesis_cli_view(temp_project, runner, monkeypatch):
    monkeypatch.chdir(temp_project.root_dir)
    _setup_fire(temp_project)
    runner.invoke(cli, ["fire", "set-thesis", "--origin", "retro arcade", "--statement", "simple loops are best"])

    result = runner.invoke(cli, ["fire", "thesis"])
    assert result.exit_code == 0
    assert "retro arcade" in result.output
    assert "simple loops are best" in result.output

    # JSON view
    json_result = runner.invoke(cli, ["fire", "thesis", "--json"])
    assert json_result.exit_code == 0
    assert '"thesis_origin": "retro arcade"' in json_result.output
