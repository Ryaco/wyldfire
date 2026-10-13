"""Tests for ember parked ideas."""

import pytest
from wyldfire.core.constants import EMBER_BANKED, EMBER_KINDLED, EMBER_DISMISSED
from wyldfire.services import ember_service


def test_ember_lifecycle(temp_project):
    emb = ember_service.bank_ember(
        temp_project,
        title="ashen city theme",
        note="rain-slick streets vs fire glow",
        kind="content",
    )
    assert emb["state"] == EMBER_BANKED
    assert emb["kind"] == "content"

    # Kindle
    k_res = ember_service.kindle_ember(temp_project, emb["id"], note="becomes area 1 theme")
    assert k_res["state"] == EMBER_KINDLED

    # Bank another and dismiss
    emb2 = ember_service.bank_ember(temp_project, "unrelated mechanic", kind="mechanic")
    d_res = ember_service.dismiss_ember(temp_project, emb2["id"], note="cut for scope")
    assert d_res["state"] == EMBER_DISMISSED
