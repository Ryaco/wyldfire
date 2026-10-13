"""Tests for server DB, API handlers, doctor, and client sync."""

from pathlib import Path
import json
import pytest

from wyldfire.core.events import create_event
from wyldfire.server import db as server_db
from wyldfire.services import sync_service, smoke_service


def test_server_db_operations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("wyldfire.server.config.DATA_DIR", tmp_path)
    monkeypatch.setattr("wyldfire.server.config.DB_PATH", tmp_path / "server.db")

    # Project creation
    proj = server_db.get_or_create_project("proj-123", "Cool Game")
    assert proj["project_id"] == "proj-123"
    assert proj["name"] == "Cool Game"

    # Same project call is idempotent
    proj2 = server_db.get_or_create_project("proj-123", "Cool Game")
    assert proj2["project_id"] == "proj-123"

    # Save events
    ev1 = create_event("flame.sparked", {"name": "f1"})
    ev2 = create_event("flame.sparked", {"name": "f2"})

    accepted, skipped = server_db.save_events("proj-123", [ev1.to_dict(), ev2.to_dict()])
    assert accepted == 2
    assert skipped == 0

    # Resend ev1 -> should be skipped
    accepted2, skipped2 = server_db.save_events("proj-123", [ev1.to_dict()])
    assert accepted2 == 0
    assert skipped2 == 1

    # Get events
    events = server_db.get_events("proj-123")
    assert len(events) == 2
    assert events[0]["id"] == ev1.id or events[1]["id"] == ev1.id


def test_doctor_staged_smoke_warning(temp_project):
    smoke_service.stage_smoke(temp_project, "uncommitted bug", on="flame/f1", severity=2)
    doc_res = sync_service.run_doctor(temp_project)
    assert doc_res["issues_count"] >= 1
    assert any(i["category"] == "staged_smoke" for i in doc_res["issues"])
