from __future__ import annotations

import asyncio

from familiar.core.events import make_event
from familiar.core.models import PluginManifest


class TimerSensor:
    manifest = PluginManifest(name="timer", version="0.1.0", plugin_type="sensor", emits=["timer.tick"])

    def __init__(self, every_seconds: int = 30) -> None:
        self.every_seconds = every_seconds
        self._ctx = None
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self, ctx) -> None:
        self._ctx = ctx
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()

    async def _loop(self) -> None:
        while self._running and self._ctx:
            await asyncio.sleep(self.every_seconds)
            await self._ctx.app.publish_event(make_event("timer.tick", source="timer", payload={"every_seconds": self.every_seconds}))
