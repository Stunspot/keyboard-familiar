from __future__ import annotations

import fnmatch
from collections.abc import Awaitable, Callable

from .models import Event

EventHandler = Callable[[Event], Awaitable[None]]


class Subscription:
    def __init__(self, bus: "InMemoryEventBus", pattern: str, handler: EventHandler) -> None:
        self._bus = bus
        self.pattern = pattern
        self.handler = handler

    def unsubscribe(self) -> None:
        self._bus.unsubscribe(self)


class InMemoryEventBus:
    def __init__(self) -> None:
        self._subs: list[Subscription] = []

    def subscribe(self, event_pattern: str, handler: EventHandler) -> Subscription:
        sub = Subscription(self, event_pattern, handler)
        self._subs.append(sub)
        return sub

    def unsubscribe(self, subscription: Subscription) -> None:
        self._subs = [s for s in self._subs if s is not subscription]

    async def publish(self, event: Event) -> None:
        for sub in list(self._subs):
            if fnmatch.fnmatch(event.type, sub.pattern):
                await sub.handler(event)
