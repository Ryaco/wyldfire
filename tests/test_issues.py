"""Tests verifying fixes for issues 1-6 in docs/ISSUES.md."""

from pathlib import Path
import json
import os
import stat
import urllib.request
import io
import pytest
from click.testing import CliRunner

from wyldfire.cli.main import cli
from wyldfire.core.config import save_credential, get_credentials_path, load_credentials
from wyldfire.core.events import create_event
from wyldfire.core.exceptions import WyldError
from wyldfire.core.project import Project, init_project
from wyldfire.services import flame_service, smoke_service, sync_service, gate_service, fire_service
from wyldfire.server.app import create_app


# -------------------------------------------------------------------------
# Issue 3: Hardcoded fallback server token removed; fail fast at startup
# -------------------------------------------------------------------------

def test_server_token_fail_fast_at_startup(monkeypatch):
    """create_app() must raise RuntimeError if WYLD_SERVER_TOKEN is unset."""
    import wyldfire.server.config as s_config
    assert not hasattr(s_config, "SERVER_TOKEN"), "SERVER_TOKEN must be removed from server.config"

    monkeypatch.delenv("WYLD_SERVER_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="WYLD_SERVER_TOKEN"):
        create_app()

    monkeypatch.setenv("WYLD_SERVER_TOKEN", "super-secret-token")
    mock_app = type("MockFastAPI", (), {
        "get": lambda self, *a, **k: (lambda f: f),
        "post": lambda self, *a, **k: (lambda f: f),
    })()
    monkeypatch.setattr("wyldfire.server.app.FastAPI", lambda **kw: mock_app)
    # Ensure Depends/Header are callable no-ops so route definitions work
    monkeypatch.setattr("wyldfire.server.app.Depends", lambda f: None)
    monkeypatch.setattr("wyldfire.server.app.Header", lambda default=None: default)
    app = create_app()
    assert app is not None


# -------------------------------------------------------------------------
# Issue 4: Credentials file permissions (0700 dir, 0600 file)
# -------------------------------------------------------------------------

def test_credentials_file_permissions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """~/.config/wyldfire must be 0700 and credentials file must be 0600."""
    cfg_dir = tmp_path / ".config" / "wyldfire"
    cred_file = cfg_dir / "credentials"
    monkeypatch.setattr("wyldfire.core.config.get_credentials_path", lambda: cred_file)

    save_credential("https://sync.example.com", "token-xyz")

    assert cred_file.exists()
    dir_mode = stat.S_IMODE(cfg_dir.stat().st_mode)
    file_mode = stat.S_IMODE(cred_file.stat().st_mode)

    assert dir_mode == 0o700, f"Expected dir mode 0700, got {oct(dir_mode)}"
    assert file_mode == 0o600, f"Expected file mode 0600, got {oct(file_mode)}"


# -------------------------------------------------------------------------
# Issue 5: wyld link UX fallback and wyld init --server update
# -------------------------------------------------------------------------

def test_link_uses_single_credential_fallback(temp_project: Project, monkeypatch: pytest.MonkeyPatch):
    """When project has no server_url, link uses single stored credential."""
    save_credential("https://single.example.com", "token-123")

    class FakeResponse:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self):
            return json.dumps({
                "status": "ok",
                "project": {"project_id": temp_project.project_id, "name": temp_project.name}
            }).encode("utf-8")

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=10.0: FakeResponse())

    res = sync_service.link_project(temp_project)
    assert res["server_url"] == "https://single.example.com"
    assert temp_project.config.get("server_url") == "https://single.example.com"


def test_init_server_updates_existing_project(temp_project: Project, runner: CliRunner):
    """wyld init --server <url> in an existing project updates server_url."""
    res = runner.invoke(cli, ["init", "--server", "https://new-server.example.com"])
    assert res.exit_code == 0
    assert "Updated server URL" in res.output
    assert temp_project.config.get("server_url") == "https://new-server.example.com"


# -------------------------------------------------------------------------
# Issue 2: WYLD_AGENT=1 guardrail refuses judgment
# -------------------------------------------------------------------------

def test_agent_guardrail_refuses_judgment(temp_project: Project, monkeypatch: pytest.MonkeyPatch):
    """WYLD_AGENT=1 prevents attestation, waiver, exclusion, and agent scoring."""
    flame_service.spark_flame(temp_project, "f1", desc="prototype")
    fire_service.start_fire(temp_project, "my-fire", ["f1"])

    monkeypatch.setenv("WYLD_AGENT", "1")

    # Attest scope refused
    with pytest.raises(WyldError, match="agent execution refused"):
        gate_service.attest_scope(temp_project, "dev attests scope is full", fire_name="my-fire")

    # Waive check refused
    with pytest.raises(WyldError, match="agent execution refused"):
        gate_service.waive_check(temp_project, "smoke", "waived by agent", fire_name="my-fire")

    # Exclude stoke refused
    with pytest.raises(WyldError, match="agent execution refused"):
        gate_service.exclude_stoke(temp_project, 1, "bad tester", fire_name="my-fire")

    # Finish slice refused
    with pytest.raises(WyldError, match="agent execution refused"):
        gate_service.finish_slice(temp_project, "slice done note", fire_name="my-fire")

    # Finish plan refused
    with pytest.raises(WyldError, match="agent execution refused"):
        gate_service.finish_plan(temp_project, "plan done note", fire_name="my-fire")

    # Flame crown refused
    with pytest.raises(WyldError, match="agent execution refused"):
        flame_service.crown_flame(temp_project, "f1", "crown note")

    # Agent self-scoring refused
    with pytest.raises(WyldError, match="agent execution refused"):
        flame_service.stoke_flame(temp_project, "f1", tester="dev", metrics={"fun": "9"})

    # But transcription (bookkeeping) is permitted!
    smoke_res = smoke_service.log_smoke(temp_project, "bug found by agent", on="flame/f1")
    assert smoke_res["status"] == "open"

    staged_res = smoke_service.stage_smoke(temp_project, "staged bug by agent", on="flame/f1")
    assert staged_res["id"] is not None

    # Transcribing external playtest is permitted
    stoke_res = flame_service.stoke_flame(
        temp_project, "f1", tester="Playtester Bob", metrics={"fun": "8"}, notes="Bob liked it"
    )
    assert stoke_res["tester"] == "Playtester Bob"


# -------------------------------------------------------------------------
# Issue 6: -file variants for long text flags
# -------------------------------------------------------------------------

def test_file_variants_for_long_text_flags(temp_project: Project, tmp_path: Path, runner: CliRunner):
    """Every long-text flag has a mutually exclusive -file variant."""
    desc_file = tmp_path / "desc.txt"
    desc_file.write_text("Detailed mechanic description from file\nwith multiple lines.", encoding="utf-8")

    # 1. flame spark --desc-file
    r = runner.invoke(cli, ["flame", "spark", "f_file", "--desc-file", str(desc_file)])
    assert r.exit_code == 0
    f_data = flame_service.get_flame(temp_project, "f_file")
    assert "Detailed mechanic description from file" in f_data["description"]

    # Mutual exclusion error if both --desc and --desc-file passed
    r = runner.invoke(cli, ["flame", "spark", "f_both", "--desc", "inline", "--desc-file", str(desc_file)])
    assert r.exit_code != 0
    assert "cannot pass both --desc and --desc-file" in r.output

    # 2. flame version --notes-file
    notes_file = tmp_path / "notes.txt"
    notes_file.write_text("Iteration 2 notes from file", encoding="utf-8")
    r = runner.invoke(cli, ["flame", "version", "f_file", "--notes-file", str(notes_file)])
    assert r.exit_code == 0
    assert "is now v2" in r.output

    r = runner.invoke(cli, ["flame", "version", "f_file", "--notes", "inline", "--notes-file", str(notes_file)])
    assert r.exit_code != 0
    assert "cannot pass both --notes and --notes-file" in r.output

    # 3. ember bank --desc-file
    ember_file = tmp_path / "ember.txt"
    ember_file.write_text("Banked creative idea details", encoding="utf-8")
    r = runner.invoke(cli, ["ember", "bank", "Wild Idea", "--desc-file", str(ember_file)])
    assert r.exit_code == 0
    assert "banked" in r.output

    r = runner.invoke(cli, ["ember", "bank", "Wild Idea 2", "--desc", "inline", "--desc-file", str(ember_file)])
    assert r.exit_code != 0
    assert "cannot pass both --desc and --desc-file" in r.output

    # 4. smoke log --notes-file and stage --notes-file
    smoke_file = tmp_path / "smoke_details.txt"
    smoke_file.write_text("Stack trace and diagnosis steps", encoding="utf-8")

    r = runner.invoke(cli, ["smoke", "log", "Crash Bug", "--on", "flame/f_file", "--notes-file", str(smoke_file)])
    assert r.exit_code == 0
    assert "smoke #1 open" in r.output

    r = runner.invoke(cli, ["smoke", "log", "Crash Bug 2", "--on", "flame/f_file", "--notes", "inline", "--notes-file", str(smoke_file)])
    assert r.exit_code != 0
    assert "cannot pass both --notes and --notes-file" in r.output

    r = runner.invoke(cli, ["smoke", "stage", "Staged Bug", "--on", "flame/f_file", "--notes-file", str(smoke_file)])
    assert r.exit_code == 0

    # 5. smoke identify --notes-file and clear --notes-file
    diag_file = tmp_path / "diag.txt"
    diag_file.write_text("Diagnosis note from file", encoding="utf-8")
    r = runner.invoke(cli, ["smoke", "identify", "1", "--notes-file", str(diag_file)])
    assert r.exit_code == 0
    assert "identified" in r.output

    fix_file = tmp_path / "fix.txt"
    fix_file.write_text("Fix resolution from file", encoding="utf-8")
    r = runner.invoke(cli, ["smoke", "clear", "1", "--notes-file", str(fix_file)])
    assert r.exit_code == 0
    assert "cleared" in r.output

    # 6. stoke --notes-file mutual exclusion
    r = runner.invoke(cli, ["flame", "stoke", "f_file", "--notes", "inline", "--notes-file", str(notes_file)])
    assert r.exit_code != 0
    assert "cannot pass both --notes and --notes-file" in r.output


# -------------------------------------------------------------------------
# Issue 1: wyld clone to join an existing remote project
# -------------------------------------------------------------------------

def test_wyld_clone_workflow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runner: CliRunner):
    """wyld clone connects to server, links project ID, and pulls full event log."""
    server_url = "https://sync.example.com"
    save_credential(server_url, "test-token")

    # Fake server that holds an existing project with events
    ev1 = create_event("flame.sparked", {"name": "remote-flame", "description": "from remote"})
    ev2 = create_event("flame.versioned", {"name": "remote-flame", "notes": "iter 2"})

    class MockServerHandler:
        def __init__(self, req):
            self.req = req
            self.url = req.full_url
            self.method = req.get_method()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            if "/api/v1/projects" in self.url and self.method == "POST":
                return json.dumps({
                    "status": "ok",
                    "project": {
                        "project_id": "proj-remote-uuid",
                        "name": "Super Remote Game",
                    }
                }).encode("utf-8")
            elif "/api/v1/events" in self.url and self.method == "POST":
                return json.dumps({"status": "ok", "accepted": 0, "skipped": 0}).encode("utf-8")
            elif "/api/v1/events" in self.url and self.method == "GET":
                return json.dumps({
                    "status": "ok",
                    "project_id": "proj-remote-uuid",
                    "events": [ev1.to_dict(), ev2.to_dict()],
                }).encode("utf-8")
            raise ValueError(f"Unexpected request: {self.method} {self.url}")

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=15.0: MockServerHandler(req))

    clone_dest = tmp_path / "cloned_game"
    r = runner.invoke(cli, ["clone", "--server", server_url, "--project", "proj-remote-uuid", str(clone_dest)])
    assert r.exit_code == 0, f"Clone failed: {r.output}"
    assert "cloned project 'Super Remote Game' (proj-remote-uuid)" in r.output
    assert "pulled 2 events" in r.output

    # Check local cloned project state
    cloned_proj = Project(clone_dest)
    assert cloned_proj.project_id == "proj-remote-uuid"
    assert cloned_proj.name == "Super Remote Game"
    assert cloned_proj.config.get("server_url") == server_url

    # Check that events were projected locally into SQLite
    flame = flame_service.get_flame(cloned_proj, "remote-flame")
    assert flame["name"] == "remote-flame"
    assert len(flame["versions"]) == 2

    # Cloning again into existing directory must fail
    r2 = runner.invoke(cli, ["clone", "--server", server_url, "--project", "proj-remote-uuid", str(clone_dest)])
    assert r2.exit_code != 0
    assert "already initialized" in r2.output
