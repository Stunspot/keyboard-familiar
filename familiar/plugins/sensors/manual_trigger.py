from __future__ import annotations

from familiar.core.events import make_event
from familiar.core.models import PluginManifest


class ManualTriggerSensor:
    manifest = PluginManifest(name="manual_trigger", version="0.1.0", plugin_type="sensor", emits=["*"])

    def __init__(self) -> None:
        self._ctx = None

    async def start(self, ctx) -> None:
        self._ctx = ctx

    async def stop(self) -> None:
        self._ctx = None

    async def trigger(self, event_type: str, source: str = "manual", payload: dict | None = None) -> None:
        if self._ctx is None:
            raise RuntimeError("manual trigger sensor not started")
        await self._ctx.app.publish_event(make_event(event_type, source=source, payload=payload or {}))
