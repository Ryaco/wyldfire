"""Per-remote session storage (users build 0.2.0).

Sessions and held tokens live in the same credentials file as the legacy
URL-keyed tokens (`~/.config/wyldfire/credentials`, 0600), under a
"remotes" key so the old entries stay readable for migration:

    {
      "remotes": {
        "main": {
          "session_token": "wyld_sess_...",
          "session_expires_at": "2027-01-29T00:00:00Z",
          "held_token": "wyld_sess_... (user token) or the master token",
          "held_kind": "user" | "master",
          "username": "ryan",
          "email": "rj.cupar@gmail.com",
          "role": "member"
        }
      }
    }

The legacy top-level URL -> token entries are the 0.1.2 shared tokens.
On upgrade, `wyld remote login --admin` reuses a stored one as the
master token, so the admin does not re-enter it.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

# NB: resolve get_credentials_path dynamically (via the module) so tests
# can monkeypatch wyldfire.core.config.get_credentials_path and have the
# patch take effect here. A top-level `from ... import` would bind the
# original function and leak test writes into the real home config.
from wyldfire.core import config as _config


def _read_all() -> Dict[str, Any]:
    path = _config.get_credentials_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_all(data: Dict[str, Any]) -> None:
    path = _config.get_credentials_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def load_remote_auth() -> Dict[str, Dict[str, Any]]:
    data = _read_all()
    remotes = data.get("remotes", {})
    return remotes if isinstance(remotes, dict) else {}


def get_remote_auth(name: str) -> Optional[Dict[str, Any]]:
    entry = load_remote_auth().get(name)
    return dict(entry) if isinstance(entry, dict) else None


def set_remote_auth(name: str, entry: Dict[str, Any]) -> None:
    data = _read_all()
    remotes = data.get("remotes", {})
    if not isinstance(remotes, dict):
        remotes = {}
    remotes[name] = dict(entry)
    data["remotes"] = remotes
    _write_all(data)


def clear_remote_auth(name: str) -> None:
    data = _read_all()
    remotes = data.get("remotes", {})
    if isinstance(remotes, dict) and name in remotes:
        del remotes[name]
        data["remotes"] = remotes
        _write_all(data)


def get_legacy_token_for_url(url: str) -> Optional[str]:
    """The 0.1.2 URL-keyed token for a URL (the shared token = master token).

    Used once at upgrade time so `wyld remote login --admin` can reuse the
    stored token instead of asking for it again.
    """
    data = _read_all()
    token = data.get(url.rstrip("/"))
    return token if isinstance(token, str) and token else None
