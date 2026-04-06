from __future__ import annotations

import re
from typing import Any

from .models import Event

_EVENT_PATTERN = re.compile(r"^[a-z0-9_]+(?:[.][a-z0-9_]+)+$")


def validate_event_type(event_type: str) -> bool:
    return bool(_EVENT_PATTERN.match(event_type))


def make_event(event_type: str, source: str, payload: dict[str, Any] | None = None) -> Event:
    if not validate_event_type(event_type):
        raise ValueError(f"Invalid event type: {event_type}")
    return Event(type=event_type, source=source, payload=payload or {})
