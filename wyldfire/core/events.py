"""Event schema, creation, and serialization."""

from dataclasses import dataclass, asdict, field
from datetime import datetime
import json
import os
import getpass
from typing import Any
import uuid

from wyldfire.core.time_utils import utc_now, utc_iso_now, timestamp_for_filename


def get_current_actor() -> str:
    """Determine the actor attributing this event."""
    if os.environ.get("WYLD_AGENT") == "1":
        return os.environ.get("WYLD_ACTOR", "agent")
    if explicit := os.environ.get("WYLD_ACTOR"):
        return explicit
    if user := os.environ.get("USER"):
        return user
    try:
        return getpass.getuser()
    except Exception:
        return "dev"


def check_agent_guardrail(action_description: str) -> None:
    """Refuse judgment actions when WYLD_AGENT=1 is set."""
    if os.environ.get("WYLD_AGENT") == "1":
        from wyldfire.core.exceptions import WyldError
        raise WyldError(
            f"agent execution refused: {action_description} requires human judgment",
            "WYLD_AGENT=1 is set; bookkeeping agents may transcribe but never judge",
        )


@dataclass
class Event:
    id: str
    ts: str
    actor: str
    type: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Event":
        return cls(
            id=str(data["id"]),
            ts=str(data["ts"]),
            actor=str(data.get("actor", "dev")),
            type=str(data["type"]),
            payload=dict(data.get("payload", {})),
        )

    def filename(self) -> str:
        """Generate filename for event file: <utc-timestamp>-<uuid-prefix>.json."""
        # Parse timestamp if possible to ensure standard format
        try:
            # Handle ISO string with or without Z
            cleaned_ts = self.ts.replace("Z", "+00:00")
            dt = datetime.fromisoformat(cleaned_ts)
            ts_str = timestamp_for_filename(dt)
        except Exception:
            ts_str = timestamp_for_filename()
        
        # UUID 8 chars or full if shorter
        short_id = self.id.replace("-", "")[:8]
        return f"{ts_str}-{short_id}.json"


def create_event(event_type: str, payload: dict[str, Any], actor: str | None = None) -> Event:
    """Create a new Event with auto-generated UUID and UTC timestamp."""
    event_id = str(uuid.uuid4())
    ts = utc_iso_now()
    resolved_actor = actor or get_current_actor()
    return Event(
        id=event_id,
        ts=ts,
        actor=resolved_actor,
        type=event_type,
        payload=payload,
    )
