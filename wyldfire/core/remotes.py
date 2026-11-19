"""Global remote registry: `wyld remote` (users build 0.2.0).

Remotes live in the global config (`~/.config/wyldfire/remotes.toml`),
shared by every project on the machine. Project configs store the remote
*name*; the URL resolves at runtime. This replaces the 0.1.1 heuristic
(one stored credential -> use it, several -> suggest) with something
explicit and robust.

TOML shape:
    default = "main"

    [remotes.main]
    url = "https://35.202.3.19"
"""

from __future__ import annotations

import os
import re
from pathlib import Path
import tomllib
from typing import Any, Dict, List, Optional, Tuple

from wyldfire.core.exceptions import WyldError

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def get_remotes_path() -> Path:
    """Return path to remotes.toml, next to the credentials file."""
    from wyldfire.core.config import get_credentials_path

    return get_credentials_path().parent / "remotes.toml"


def load_remotes() -> Dict[str, Any]:
    """Load the remotes file. Returns {"default": str|None, "remotes": {...}}."""
    path = get_remotes_path()
    if not path.exists():
        return {"default": None, "remotes": {}}
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"default": None, "remotes": {}}
    remotes = data.get("remotes", {})
    if not isinstance(remotes, dict):
        remotes = {}
    clean = {}
    for name, info in remotes.items():
        if isinstance(info, dict) and isinstance(info.get("url"), str):
            clean[name] = {"url": info["url"]}
    default = data.get("default")
    if default not in clean:
        default = None
    return {"default": default, "remotes": clean}


def save_remotes(data: Dict[str, Any]) -> None:
    """Write the remotes file (0600). TOML is written by hand — the shape
    is small and fixed, and stdlib has no TOML writer."""
    path = get_remotes_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    lines: List[str] = []
    if data.get("default"):
        lines.append(f'default = "{data["default"]}"')
        lines.append("")
    for name in sorted(data.get("remotes", {})):
        url = data["remotes"][name]["url"]
        lines.append(f"[remotes.{name}]")
        lines.append(f'url = "{url}"')
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _validate_name(name: str) -> str:
    name = (name or "").strip()
    if not _NAME_RE.match(name):
        raise WyldError(
            f"invalid remote name '{name}'",
            "use letters, digits, dashes and underscores, starting with a letter or digit",
        )
    return name


def _validate_url(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    if not url.startswith("http://") and not url.startswith("https://"):
        raise WyldError(f"invalid server URL '{url}'", "must start with http:// or https://")
    return url


def add_remote(name: str, url: str) -> Dict[str, Any]:
    name = _validate_name(name)
    url = _validate_url(url)
    data = load_remotes()
    if name in data["remotes"]:
        raise WyldError(
            f"remote '{name}' already exists",
            f"remove it first ('wyld remote remove {name}') or pick another name",
        )
    data["remotes"][name] = {"url": url}
    if len(data["remotes"]) == 1:
        data["default"] = name
    save_remotes(data)
    return {"name": name, "url": url}


def remove_remote(name: str) -> Dict[str, Any]:
    name = _validate_name(name)
    data = load_remotes()
    if name not in data["remotes"]:
        raise WyldError(f"remote '{name}' not found", "list remotes with 'wyld remote'")
    url = data["remotes"][name]["url"]
    del data["remotes"][name]
    if data.get("default") == name:
        data["default"] = next(iter(data["remotes"]), None)
    save_remotes(data)
    return {"name": name, "url": url}


def set_remote_url(name: str, url: str) -> Dict[str, Any]:
    name = _validate_name(name)
    url = _validate_url(url)
    data = load_remotes()
    if name not in data["remotes"]:
        raise WyldError(f"remote '{name}' not found", "list remotes with 'wyld remote'")
    data["remotes"][name] = {"url": url}
    save_remotes(data)
    return {"name": name, "url": url}


def rename_remote(old: str, new: str) -> Dict[str, Any]:
    """Rename a remote and rewrite referencing project configs.

    Returns the names of the project configs that were updated.
    """
    old = _validate_name(old)
    new = _validate_name(new)
    data = load_remotes()
    if old not in data["remotes"]:
        raise WyldError(f"remote '{old}' not found", "list remotes with 'wyld remote'")
    if new in data["remotes"]:
        raise WyldError(
            f"remote '{new}' already exists",
            f"remove it first ('wyld remote remove {new}') or pick another name",
        )
    data["remotes"][new] = data["remotes"].pop(old)
    if data.get("default") == old:
        data["default"] = new
    save_remotes(data)
    updated: List[str] = []
    from wyldfire.core.config import load_registry, ProjectConfig

    for project_path in load_registry():
        wyld_dir = Path(project_path) / ".wyld"
        if not wyld_dir.exists():
            continue
        cfg = ProjectConfig(wyld_dir)
        if cfg.get("remote") == old:
            cfg.set("remote", new)
            updated.append(cfg.get("name") or project_path)
    return {"old": old, "new": new, "updated_projects": updated}


def set_default_remote(name: str) -> Dict[str, Any]:
    name = _validate_name(name)
    data = load_remotes()
    if name not in data["remotes"]:
        raise WyldError(f"remote '{name}' not found", "list remotes with 'wyld remote'")
    data["default"] = name
    save_remotes(data)
    return {"name": name}


def resolve_remote(name: Optional[str] = None, server: Optional[str] = None) -> Tuple[Optional[str], str]:
    """Resolve which remote a command targets.

    An explicit --remote wins; --server is the ad-hoc escape hatch for
    unregistered servers (used only when no --remote is given).
    """
    data = load_remotes()
    remotes = data["remotes"]
    if name:
        name = _validate_name(name)
        if name not in remotes:
            raise WyldError(
                f"remote '{name}' not found",
                "list remotes with 'wyld remote' or add it with 'wyld remote add'",
            )
        return name, remotes[name]["url"]
    if server:
        return None, _validate_url(server)
    if len(remotes) == 1:
        only = next(iter(remotes))
        return only, remotes[only]["url"]
    if data.get("default") and data["default"] in remotes:
        default = data["default"]
        return default, remotes[default]["url"]
    if not remotes:
        raise WyldError(
            "no remote registered",
            "register one with 'wyld remote add <name> <url>' first",
        )
    known = ", ".join(sorted(remotes))
    raise WyldError(
        "several remotes registered and no default set",
        f"pick one with '--remote <name>' (known: {known}) or set a default with 'wyld remote set-default'",
    )
