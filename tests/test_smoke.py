"""Tests for smoke issue tracker and learning database."""

import pytest
from wyldfire.core.constants import (
    SMOKE_STAGED,
    SMOKE_OPEN,
    SMOKE_IDENTIFIED,
    SMOKE_CLEARED,
)
from wyldfire.core.exceptions import WyldError
from wyldfire.services import smoke_service, flame_service


def test_smoke_lifecycle(temp_project):
    flame_service.spark_flame(temp_project, "wildfire")
    sm = smoke_service.log_smoke(temp_project, "wind too chaotic", on="flame/wildfire", severity=2, tags="balance")
    assert sm["status"] == SMOKE_OPEN

    # Identify
    id_res = smoke_service.identify_smoke(temp_project, sm["id"], note="spread rate scales with map size")
    assert id_res["status"] == SMOKE_IDENTIFIED

    # Clear
    cl_res = smoke_service.clear_smoke(temp_project, sm["id"], note="scale spread with player count")
    assert cl_res["status"] == SMOKE_CLEARED

    # Tag
    tag_res = smoke_service.tag_smoke(temp_project, sm["id"], tags="balance,spread-rate")
    assert "spread-rate" in tag_res["tags"]

    # History in show
    full = smoke_service.get_smoke(temp_project, sm["id"])
    assert len(full["transitions"]) == 3


def test_smoke_search_and_widening(temp_project):
    flame_service.spark_flame(temp_project, "wildfire")
    sm = smoke_service.log_smoke(temp_project, "wind chaos", on="flame/wildfire", severity=2, tags="balance,pacing")
    smoke_service.identify_smoke(temp_project, sm["id"], note="fixed interval die")
    smoke_service.clear_smoke(temp_project, sm["id"], note="wind every 2 turns")

    # Search local project
    res, widened = smoke_service.search_smoke(temp_project, tags="balance", status="cleared")
    assert len(res) == 1
    assert not widened
    assert res[0]["fix"] == "wind every 2 turns"

    # Search non-matching tag -> widens
    empty_res, widened_empty = smoke_service.search_smoke(temp_project, tags="nonexistent-tag", status="cleared")
    assert len(empty_res) == 0
    assert widened_empty
