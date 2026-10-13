"""Pytest fixtures for Wyldfire tests."""

from pathlib import Path
import pytest
from click.testing import CliRunner

from wyldfire.core.project import init_project, Project


@pytest.fixture
def runner():
    """Click CLI test runner."""
    return CliRunner()


@pytest.fixture
def temp_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Project:
    """Fixture that initializes a new project in a temporary directory and sets cwd."""
    monkeypatch.chdir(tmp_path)
    # Isolate global wyld registry and config
    global_wyld = tmp_path / ".global_wyld"
    global_config = tmp_path / ".global_config"
    monkeypatch.setattr("wyldfire.core.config.get_global_wyld_dir", lambda: global_wyld)
    monkeypatch.setattr("wyldfire.core.config.get_credentials_path", lambda: global_config / "credentials")
    
    project = init_project(tmp_path, name="test-game")
    return project
