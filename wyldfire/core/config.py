"""Project and global configuration management."""

import os
from pathlib import Path
import json
import tomllib
from typing import Any


def get_global_wyld_dir() -> Path:
    """Return ~/.wyld directory."""
    d = Path.home() / ".wyld"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_credentials_path() -> Path:
    """Return path to credentials file in ~/.config/wyldfire/credentials."""
    d = Path.home() / ".config" / "wyldfire"
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d / "credentials"


def load_credentials() -> dict[str, str]:
    """Load credentials mapping server_url -> token."""
    path = get_credentials_path()
    if not path.exists():
        return {}
    try:
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            return {}
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # Fallback if stored as toml
            return tomllib.loads(content)
    except Exception:
        return {}


def save_credential(server_url: str, token: str) -> None:
    """Store token for server_url in ~/.config/wyldfire/credentials with 0600 permissions."""
    creds = load_credentials()
    creds[server_url.rstrip("/")] = token
    path = get_credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    path.write_text(json.dumps(creds, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def remove_credential(server_url: str | None = None) -> None:
    """Remove stored credentials for server_url, or all if None."""
    path = get_credentials_path()
    if not path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    if server_url is None:
        path.write_text("{}", encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return
    creds = load_credentials()
    creds.pop(server_url.rstrip("/"), None)
    path.write_text(json.dumps(creds, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def get_registry_path() -> Path:
    """Return path to ~/.wyld/registry.json."""
    return get_global_wyld_dir() / "registry.json"


def load_registry() -> dict[str, str]:
    """Load project registry mapping absolute path -> project name."""
    path = get_registry_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def register_project(project_path: Path, name: str) -> None:
    """Register project in ~/.wyld/registry.json."""
    registry = load_registry()
    registry[str(project_path.resolve())] = name
    path = get_registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry, indent=2), encoding="utf-8")


class ProjectConfig:
    def __init__(self, wyld_dir: Path):
        self.wyld_dir = wyld_dir
        self.config_path = wyld_dir / "config.toml"
        self._data: dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        if self.config_path.exists():
            try:
                self._data = tomllib.loads(self.config_path.read_text(encoding="utf-8"))
            except Exception:
                self._data = {}
        else:
            self._data = {}

    def save(self) -> None:
        lines = []
        for k, v in self._data.items():
            if isinstance(v, str):
                lines.append(f'{k} = "{v}"')
            elif isinstance(v, bool):
                lines.append(f'{k} = {str(v).lower()}')
            elif isinstance(v, (int, float)):
                lines.append(f'{k} = {v}')
            elif isinstance(v, list):
                items = ", ".join(f'"{x}"' for x in v)
                lines.append(f'{k} = [{items}]')
        self.config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def get(self, key: str, default: Any = None) -> Any:
        self.load()
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        self.save()
