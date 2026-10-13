"""Tests for Gate waivers, laps, Wick traversal, and ETA."""

import pytest
from wyldfire.core.constants import (
    PHASE_PROTOTYPE,
    PHASE_GATE_PART2,
    PHASE_GATE_PART3,
    PHASE_PRODUCTION,
)
from wyldfire.services import (
    flame_service,
    fire_service,
    gate_service,
    wick_service,
    ember_service,
    template_service,
)


def test_gate_waivers_and_laps(temp_project):
    flame_service.spark_flame(temp_project, "card_core")
    fire_service.start_fire(temp_project, "card_game", flames=["card_core"])
    fire_service.checkout_fire(temp_project, "card_game")

    # Gate status has failures (playtest, core_loop, toys, scope)
    st = gate_service.get_gate_status(temp_project, "card_game")
    assert not st["all_passed"]

    # Waive all checks
    for check_name in ("playtest", "core_loop", "toys", "scope", "smoke", "embers"):
        gate_service.waive_check(temp_project, check_name, reason=f"waiving {check_name} for speedrun test")

    st2 = gate_service.get_gate_status(temp_project, "card_game")
    assert st2["all_passed"]
    for c in st2["checks"]:
        assert c["passed"]
        assert "waived" in c["provenance"]

    # Gate open passes -> gate:part2
    res = gate_service.open_gate(temp_project, "card_game")
    assert res["verdict"] == "pass"
    assert res["phase"] == PHASE_GATE_PART2
    assert not res.get("is_lap")

    # Fast forward through slice & plan
    wick_service.plan_wick(temp_project, "card_game")
    gate_service.set_slice_bundles(temp_project, ["slice_b"], fire_name="card_game")
    wick_service.add_bundle(temp_project, "slice_b", fire_name="card_game")
    wick_service.add_fuel(temp_project, "slice_task", bundle="slice_b", fire_name="card_game")
    wick_service.finish_fuel(temp_project, "slice_task", fire_name="card_game")
    fire_service.stoke_fire(temp_project, "card_game", notes="slice stoke")
    gate_service.finish_slice(temp_project, "slice ready", fire_name="card_game")
    gate_service.finish_plan(temp_project, "plan ready", fire_name="card_game")

    fire_data = fire_service.get_fire(temp_project, "card_game")
    assert fire_data["phase"] == PHASE_PRODUCTION

    # In production, opening gate starts LAP 1
    lap_res = gate_service.open_gate(temp_project, "card_game")
    assert lap_res["is_lap"]
    assert lap_res["lap_no"] == 1
    assert lap_res["verdict"] == "pass"
    assert lap_res["phase"] == PHASE_PRODUCTION

    laps = gate_service.list_laps(temp_project, "card_game")
    assert len(laps) == 1
    assert laps[0]["lap_no"] == 1


def test_wick_templates_cut_and_eta(temp_project):
    flame_service.spark_flame(temp_project, "f1")
    fire_service.start_fire(temp_project, "f_game", flames=["f1"])
    fire_service.checkout_fire(temp_project, "f_game")
    wick_service.plan_wick(temp_project, "f_game")

    # Create template
    template_service.create_template(
        temp_project,
        "dungeon",
        bundles_str="room x2",
        fuels_str="door:sprite, music:audio",
    )

    # Add bundle using template
    wick_service.add_bundle(temp_project, "level 1", template_name="dungeon", fire_name="f_game")

    bundles = wick_service.list_bundles_tree(temp_project, "f_game")
    bundle_names = [b["name"] for b in bundles]
    assert "level 1" in bundle_names
    assert "room 1" in bundle_names
    assert "room 2" in bundle_names

    # Check fuels instantiated in level 1
    l1 = wick_service.get_bundle(temp_project, "level 1", "f_game")
    fuel_names = [f["name"] for f in l1["fuels"]]
    assert "door" in fuel_names
    assert "music" in fuel_names

    # Finish door and log time: 60m
    wick_service.start_fuel(temp_project, "door", "f_game")
    wick_service.log_fuel_time(temp_project, "door", "1h", "f_game")
    wick_service.finish_fuel(temp_project, "door", "f_game")

    # ETA now has data
    eta_res = wick_service.calculate_eta(temp_project, "f_game")
    assert eta_res["status"] == "calculated"
    assert eta_res["total_estimated_hours"] > 0

    # Cut room 2
    cut_res = wick_service.cut_bundle(temp_project, "room 2", reason="time constraints", fire_name="f_game")
    assert cut_res["cut"]

    # Traversal test with wick next
    next_f = wick_service.get_next_fuel(temp_project, "f_game")
    assert next_f is not None
    assert next_f["name"] == "music"
