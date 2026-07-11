from __future__ import annotations

import asyncio
import contextlib

from familiar.core.events import make_event
from familiar.core.glance import GlanceDeck
from familiar.core.models import PluginManifest


class GlanceDeckSensor:
    manifest = PluginManifest(name="glance_deck", version="0.1.0", plugin_type="sensor", emits=["deck.card"])

    def __init__(self, deck: GlanceDeck, *, alerts_only: bool = False) -> None:
        self.deck = deck
        self.alerts_only = alerts_only
        self._ctx = None
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._reported_errors: dict[str, str] = {}

    async def start(self, ctx) -> None:
        self._ctx = ctx
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None
        self._ctx = None

    async def _loop(self) -> None:
        while self._running and self._ctx:
            await self.publish_once()
            await asyncio.sleep(self.deck.settings.interval_seconds)

    async def publish_once(self, app=None) -> bool:
        target_app = app or (self._ctx.app if self._ctx else None)
        if target_app is None:
            raise RuntimeError("glance deck sensor not started")
        card = self.deck.next_card()
        for source, error in self.deck.provider_errors.items():
            if self._reported_errors.get(source) != error:
                target_app.trace.append(f"deck.provider unavailable source={source} detail={error}")
        self._reported_errors = dict(self.deck.provider_errors)
        if card is None:
            return False
        if self.alerts_only and not card.alert:
            return False
        results = await target_app.publish_event(
            make_event("deck.card", source=f"deck:{card.source}", payload=card.payload())
        )
        primary_configured = "primary_surface" in target_app.plugins.surfaces
        delivered = any(
            result.ok and (result.surface == "primary_surface" if primary_configured else True)
            for result in results
        )
        if delivered:
            self.deck.acknowledge(card)
        elif card.alert:
            target_app.trace.append(f"deck.alert retry source={card.source} reason=primary-render-failed")
        return delivered
