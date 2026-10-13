"""Tests for flame prototype lifecycle."""

import pytest
from wyldfire.core.constants import (
    FLAME_SPARKED,
    FLAME_BURNING,
    FLAME_TESTED,
    FLAME_CROWNED,
    FLAME_DOUSED,
)
from wyldfire.core.exceptions import WyldError
from wyldfire.services import flame_service, smoke_service


def test_flame_spark_and_version(temp_project):
    res = flame_service.spark_flame(temp_project, "wildfire", desc="contain fire")
    assert res["name"] == "wildfire"
    assert res["state"] == FLAME_SPARKED

    flame = flame_service.get_flame(temp_project, "wildfire")
    assert flame["state"] == FLAME_SPARKED
    assert len(flame["versions"]) == 1
    assert flame["versions"][0]["notes"] == "Initial spark"

    # Versioning
    v2 = flame_service.version_flame(temp_project, "wildfire", notes="wind die every 2 turns")
    assert v2["version"] == 2
    assert v2["state"] == FLAME_BURNING


def test_flame_stoke_and_commits_staged_smoke(temp_project):
    flame_service.spark_flame(temp_project, "wildfire")
    
    # Stage smoke on this flame
    sm = smoke_service.stage_smoke(temp_project, "wind die unfair", on="flame/wildfire", severity=2)
    assert sm["status"] == "staged"

    # Stoke the flame
    st_res = flame_service.stoke_flame(
        temp_project,
        name="wildfire",
        tester="Jo",
        notes="sings now",
        metrics={"enjoyment": "8"},
    )
    assert st_res["tester"] == "Jo"
    assert sm["id"] in st_res["committed_smoke_ids"]

    # Check flame state is now tested
    flame = flame_service.get_flame(temp_project, "wildfire")
    assert flame["state"] == FLAME_TESTED

    # Check staged smoke is now open
    sm_after = smoke_service.get_smoke(temp_project, sm["id"])
    assert sm_after["status"] == "open"


def test_flame_crown_and_douse(temp_project):
    flame_service.spark_flame(temp_project, "f1")
    flame_service.spark_flame(temp_project, "f2")

    c = flame_service.crown_flame(temp_project, "f1", note="chosen for vertical slice")
    assert c["state"] == FLAME_CROWNED

    d = flame_service.douse_flame(temp_project, "f2", note="too complex for solo dev")
    assert d["state"] == FLAME_DOUSED
