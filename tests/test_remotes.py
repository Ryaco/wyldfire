"""Tests for the remotes registry (users build 0.2.0)."""

from pathlib import Path
import pytest

from wyldfire.core import remotes
from wyldfire.core.exceptions import WyldError


@pytest.fixture(autouse=True)
def _isolate_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = tmp_path / ".config"
    monkeypatch.setattr(
        "wyldfire.core.config.get_credentials_path", lambda: cfg / "credentials"
    )
    monkeypatch.setattr(
        "wyldfire.core.config.get_global_wyld_dir", lambda: tmp_path / ".wyld"
    )


def test_add_list_default_and_resolve():
    remotes.add_remote("main", "https://35.202.3.19")
    data = remotes.load_remotes()
    assert data["default"] == "main"  # first remote becomes the default
    assert data["remotes"]["main"]["url"] == "https://35.202.3.19"
    assert remotes.resolve_remote() == ("main", "https://35.202.3.19")
    assert remotes.resolve_remote("main") == ("main", "https://35.202.3.19")


def test_second_remote_does_not_steal_default():
    remotes.add_remote("main", "https://one.example.com")
    remotes.add_remote("backup", "https://two.example.com")
    assert remotes.load_remotes()["default"] == "main"
    assert remotes.resolve_remote() == ("main", "https://one.example.com")
    assert remotes.resolve_remote("backup") == ("backup", "https://two.example.com")


def test_resolve_requires_a_choice_when_several_and_no_default():
    remotes.add_remote("a", "https://a.example.com")
    remotes.add_remote("b", "https://b.example.com")
    remotes.set_default_remote("a")
    assert remotes.resolve_remote() == ("a", "https://a.example.com")
    data = remotes.load_remotes()
    data["default"] = None
    remotes.save_remotes(data)
    with pytest.raises(WyldError, match="no default"):
        remotes.resolve_remote()


def test_resolve_server_escape_hatch():
    name, url = remotes.resolve_remote(server="https://adhoc.example.com")
    assert name is None and url == "https://adhoc.example.com"


def test_resolve_no_remotes():
    with pytest.raises(WyldError, match="no remote registered"):
        remotes.resolve_remote()


def test_duplicate_and_invalid_names():
    remotes.add_remote("main", "https://one.example.com")
    with pytest.raises(WyldError, match="already exists"):
        remotes.add_remote("main", "https://two.example.com")
    with pytest.raises(WyldError, match="invalid remote name"):
        remotes.add_remote("bad name!", "https://x.example.com")
    with pytest.raises(WyldError, match="invalid server URL"):
        remotes.add_remote("ok", "ftp://x.example.com")


def test_set_url_rename_remove(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    remotes.add_remote("main", "https://one.example.com")
    remotes.set_remote_url("main", "https://new.example.com")
    assert remotes.resolve_remote("main") == ("main", "https://new.example.com")
    # Rename rewrites project configs that reference the old name.
    proj_dir = tmp_path / "proj"
    (proj_dir / ".wyld").mkdir(parents=True)
    from wyldfire.core.config import ProjectConfig, register_project

    cfg = ProjectConfig(proj_dir / ".wyld")
    cfg.set("remote", "main")
    cfg.set("name", "my-game")
    register_project(proj_dir, "my-game")
    res = remotes.rename_remote("main", "primary")
    assert res["updated_projects"] == ["my-game"]
    assert remotes.resolve_remote("primary") == ("primary", "https://new.example.com")
    with pytest.raises(WyldError, match="not found"):
        remotes.resolve_remote("main")
    remotes.remove_remote("primary")
    assert remotes.load_remotes()["remotes"] == {}
    with pytest.raises(WyldError, match="no remote registered"):
        remotes.resolve_remote()
