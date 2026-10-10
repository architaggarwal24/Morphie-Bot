"""
Time tool.

Accepts either a city name ("London", "Tokyo") or a formal IANA timezone
("Europe/London"). The model is told in the tool description that either
works; this module adds a small, explicit fallback table for common
cities in case the model passes a bare city name instead of translating
it to an IANA zone itself. It is deliberately not exhaustive - if a
location isn't recognized, the tool fails gracefully with a helpful
message instead of guessing.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .base import Tool

_CITY_TIMEZONES = {
    "london": "Europe/London",
    "paris": "Europe/Paris",
    "berlin": "Europe/Berlin",
    "madrid": "Europe/Madrid",
    "rome": "Europe/Rome",
    "moscow": "Europe/Moscow",
    "new york": "America/New_York",
    "los angeles": "America/Los_Angeles",
    "chicago": "America/Chicago",
    "toronto": "America/Toronto",
    "tokyo": "Asia/Tokyo",
    "beijing": "Asia/Shanghai",
    "shanghai": "Asia/Shanghai",
    "delhi": "Asia/Kolkata",
    "new delhi": "Asia/Kolkata",
    "mumbai": "Asia/Kolkata",
    "dubai": "Asia/Dubai",
    "singapore": "Asia/Singapore",
    "sydney": "Australia/Sydney",
    "hong kong": "Asia/Hong_Kong",
    "seoul": "Asia/Seoul",
    "sao paulo": "America/Sao_Paulo",
    "utc": "UTC",
}


def _resolve_timezone(location: str) -> ZoneInfo | None:
    # Try it as a formal IANA zone first (e.g. "Europe/London").
    try:
        return ZoneInfo(location)
    except (ZoneInfoNotFoundError, ValueError):
        pass

    # Fall back to a common city name (e.g. "London").
    mapped = _CITY_TIMEZONES.get(location.strip().lower())
    if mapped:
        try:
            return ZoneInfo(mapped)
        except (ZoneInfoNotFoundError, ValueError):
            return None
    return None


def get_current_time(location: str = "UTC") -> str:
    tz = _resolve_timezone(location)
    if tz is None:
        return (
            f"Unknown location '{location}'. Try a major city name (e.g. 'London', "
            "'Tokyo') or a formal IANA timezone (e.g. 'Europe/London')."
        )
    now = datetime.now(tz)
    return f"{now.strftime('%A, %d %B %Y, %H:%M:%S %Z')} in {location}."


time_tool = Tool(
    name="get_current_time",
    description=(
        "Get the current date and time in a city (e.g. 'London', 'Tokyo') or a "
        "formal IANA timezone (e.g. 'Europe/London'). Use this whenever the "
        "user asks what time or date it is, anywhere."
    ),
    parameters={
        "type": "object",
        "properties": {
            "location": {
                "type": "string",
                "description": "A city name or IANA timezone, e.g. 'Tokyo' or 'Asia/Tokyo'.",
            }
        },
        "required": [],
    },
    handler=get_current_time,
)
