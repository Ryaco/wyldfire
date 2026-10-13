"""Time utilities for UTC timestamps and duration parsing."""

from datetime import datetime, timezone
import re
from wyldfire.core.exceptions import WyldError


def utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


def utc_iso_now() -> str:
    """Return current UTC ISO-8601 string (e.g. 2026-10-13T19:00:00.000000Z)."""
    return utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")


def timestamp_for_filename(dt: datetime | None = None) -> str:
    """Return timestamp formatted for event filename: YYYYMMDDTHHMMSS."""
    dt = dt or utc_now()
    return dt.strftime("%Y%m%dT%H%M%S")


def parse_duration_to_minutes(val: str) -> int:
    """Parse duration string such as '2h30m', '90m', '1.5h', '2h' into integer minutes."""
    s = val.strip().lower()
    if not s:
        raise WyldError(f"invalid duration '{val}'", "use formats like '2h30m', '90m', or '1.5h'")

    # Simple numeric check if just integer minutes
    if s.isdigit():
        return int(s)

    # Decimal hours like "1.5h"
    m_dech = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*h", s)
    if m_dech:
        return int(round(float(m_dech.group(1)) * 60))

    # Pattern like "2h30m" or "2h 30m" or "2h" or "30m"
    m_hm = re.fullmatch(r"(?:([0-9]+)\s*h)?\s*(?:([0-9]+)\s*m)?", s)
    if m_hm and (m_hm.group(1) or m_hm.group(2)):
        hours = int(m_hm.group(1)) if m_hm.group(1) else 0
        minutes = int(m_hm.group(2)) if m_hm.group(2) else 0
        return hours * 60 + minutes

    raise WyldError(
        f"cannot parse duration '{val}'",
        "accepts formats like '2h30m', '90m', or '1.5h'"
    )


def format_minutes(minutes: int) -> str:
    """Format integer minutes into human readable string, e.g. 2h 30m or 45m."""
    if minutes < 60:
        return f"{minutes}m"
    h = minutes // 60
    m = minutes % 60
    if m == 0:
        return f"{h}h"
    return f"{h}h {m}m"
