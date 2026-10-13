"""End-to-end test following Section 12 walkthrough from BUILD_SPEC.md."""

from pathlib import Path
from wyldfire.core.constants import (
    PHASE_PROTOTYPE,
    PHASE_GATE_PART2,
    PHASE_GATE_PART3,
    PHASE_PRODUCTION,
    PHASE_SHIPPED,
)
from wyldfire.services import (
    flame_service,
    metric_service,
    ember_service,
    fire_service,
    gate_service,
    wick_service,
    status_service,
)


def test_complete_walkthrough(temp_project):
    # $ wyld flame spark "wildfire" --desc "cut firebreaks, starve the fire"
    flame_service.spark_flame(temp_project, "wildfire", desc="cut firebreaks, starve the fire")

    # $ wyld metric define enjoyment --prompt "How much did you enjoy it? (1-10)" --type number
    metric_service.define_metric(
        temp_project,
        "enjoyment",
        prompt="How much did you enjoy it? (1-10)",
        metric_type="number",
    )

    # $ wyld flame stoke wildfire --tester Jo --metric enjoyment=6 --notes "wind chaos"
    flame_service.stoke_flame(
        temp_project,
        "wildfire",
        tester="Jo",
        metrics={"enjoyment": "6"},
        notes="wind chaos",
    )

    # $ wyld flame version wildfire --notes "wind every 2 turns"
    flame_service.version_flame(temp_project, "wildfire", notes="wind every 2 turns")

    # $ wyld flame stoke wildfire --tester Jo --metric enjoyment=8 --notes "sings now"
    flame_service.stoke_flame(
        temp_project,
        "wildfire",
        tester="Jo",
        metrics={"enjoyment": "8"},
        notes="sings now",
    )

    # $ wyld ember bank "ashen city theme" --note "rain-slick streets vs fire glow"
    emb = ember_service.bank_ember(
        temp_project,
        title="ashen city theme",
        note="rain-slick streets vs fire glow",
    )

    # $ wyld fire start "game" --flames wildfire --desc "the full game"
    fire_service.start_fire(temp_project, "game", flames=["wildfire"], desc="the full game")

    # $ wyld fire checkout game
    fire_service.checkout_fire(temp_project, "game")

    # $ wyld fire stoke game --tester Jo --metric enjoyment=8 --notes "composition works"
    fire_service.stoke_fire(
        temp_project,
        "game",
        tester="Jo",
        metrics={"enjoyment": "8"},
        notes="composition works",
    )

    # $ wyld fire set-loop "spot fire → cut firebreaks → starve it → score"
    fire_service.set_core_loop(temp_project, "game", "spot fire → cut firebreaks → starve it → score")

    # $ wyld fire add-toy "cutting firebreaks"
    fire_service.add_toy(temp_project, "game", "cutting firebreaks")

    # $ wyld gate attest-scope --note "one mechanic, one game"
    gate_service.attest_scope(temp_project, "one mechanic, one game", fire_name="game")

    # Gate check status: check failing ember
    status_before_kindle = gate_service.get_gate_status(temp_project, "game")
    ember_check = next(c for c in status_before_kindle["checks"] if c["name"] == "embers")
    assert not ember_check["passed"]

    # $ wyld ember kindle 1 --note "becomes area 1 theme"
    ember_service.kindle_ember(temp_project, emb["id"], note="becomes area 1 theme")

    # $ wyld gate open                      # → Production point reached. Phase: gate:part2
    gate_res = gate_service.open_gate(temp_project, "game")
    assert gate_res["verdict"] == "pass"
    assert gate_res["phase"] == PHASE_GATE_PART2

    # $ wyld wick plan
    wick_service.plan_wick(temp_project, "game")

    # $ wyld gate slice set --bundles "area 1"
    gate_service.set_slice_bundles(temp_project, ["area 1"], fire_name="game")

    # $ wyld wick bundle add "area 1" --meta theme="ashen city"
    wick_service.add_bundle(temp_project, "area 1", metadata={"theme": "ashen city"}, fire_name="game")

    # $ wyld wick fuel add "firefighter sprite" --to "area 1" --type sprite
    wick_service.add_fuel(temp_project, "firefighter sprite", bundle="area 1", type_tag="sprite", fire_name="game")

    # $ wyld wick start "firefighter sprite" && wyld wick log "firefighter sprite" --time 3h
    wick_service.start_fuel(temp_project, "firefighter sprite", fire_name="game")
    wick_service.log_fuel_time(temp_project, "firefighter sprite", "3h", fire_name="game")

    # $ wyld wick finish "firefighter sprite"
    wick_service.finish_fuel(temp_project, "firefighter sprite", fire_name="game")

    # $ wyld fire stoke game --tester Jo --metric enjoyment=9 --notes "slice sings"
    fire_service.stoke_fire(
        temp_project,
        "game",
        tester="Jo",
        metrics={"enjoyment": "9"},
        notes="slice sings",
    )

    # $ wyld gate slice-done --note "pitch-ready"     # → gate:part3
    slice_done_res = gate_service.finish_slice(temp_project, "pitch-ready", fire_name="game")
    assert slice_done_res["phase"] == PHASE_GATE_PART3

    # $ wyld wick bundle add "area 2" && wyld wick fuel define "area 2" --note "bridge"
    wick_service.add_bundle(temp_project, "area 2", fire_name="game")
    wick_service.define_fuel_placeholder(temp_project, bundle="area 2", note="bridge", fire_name="game")

    # $ wyld wick bundle add "area 3" --meta theme="flooded dam"
    wick_service.add_bundle(temp_project, "area 3", metadata={"theme": "flooded dam"}, fire_name="game")

    # Plan done should fail while define fuel on area 2 is unresolved
    import pytest
    from wyldfire.core.exceptions import WyldError
    with pytest.raises(WyldError):
        gate_service.finish_plan(temp_project, "trying to finish early", fire_name="game")

    # Resolve area 2 define fuel
    wick_service.define_bundle_metadata(temp_project, "area 2", {"theme": "canyon pass"}, fire_name="game")
    wick_service.finish_fuel(temp_project, "define: area 2", fire_name="game")

    # $ wyld gate plan-done --note "iteration 1 covers areas 1-3"  # → production
    plan_done_res = gate_service.finish_plan(temp_project, "iteration 1 covers areas 1-3", fire_name="game")
    assert plan_done_res["phase"] == PHASE_PRODUCTION

    # Add remaining fuels and finish them so the wick is complete
    wick_service.add_fuel(temp_project, "dam sprite", bundle="area 3", type_tag="sprite", fire_name="game")
    wick_service.start_fuel(temp_project, "dam sprite", fire_name="game")
    wick_service.log_fuel_time(temp_project, "dam sprite", "2h", fire_name="game")
    wick_service.finish_fuel(temp_project, "dam sprite", fire_name="game")

    # Production stoke
    fire_service.stoke_fire(temp_project, "game", tester="BetaTester", notes="release candidate looks clean")

    # $ wyld fire ship                      # → shipped
    ship_res = fire_service.ship_fire(temp_project, "game")
    assert ship_res["phase"] == PHASE_SHIPPED
