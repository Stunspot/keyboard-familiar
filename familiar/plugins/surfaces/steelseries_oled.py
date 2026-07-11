from __future__ import annotations

import asyncio
import contextlib

from familiar.adapters.steelseries.transport import ScreenFrame, SteelSeriesTransport
from familiar.core.models import Directive, PluginManifest, RenderResult, SurfaceCapabilities


class SteelSeriesOledSurface:
    manifest = PluginManifest(
        name="steelseries_oled", version="0.1.0", plugin_type="surface", consumes=["display.*"]
    )
    capabilities = SurfaceCapabilities(
        surface="primary_surface",
        supports={"display.text", "display.card"},
        max_chars_title=20,
        max_chars_body=40,
        supports_icons=False,
    )

    def __init__(self, transport: SteelSeriesTransport) -> None:
        self.transport = transport
        self._ctx = None
        self._heartbeat_task: asyncio.Task[None] | None = None

    async def start(self, ctx) -> None:
        self._ctx = ctx

    async def stop(self) -> None:
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._heartbeat_task
        self._heartbeat_task = None
        self._ctx = None

    async def probe(self) -> None:
        await self.transport.initialize()

    async def render(self, directive: Directive) -> RenderResult:
        frame = self._frame_from_directive(directive)
        await self.transport.send_frame(frame)
        if self._heartbeat_task is None:
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        if self._ctx:
            self._ctx.app.trace.append(
                f"steelseries_oled rendered {directive.kind} scene={directive.scene} mode={self.transport.mode}"
            )
        return RenderResult(
            surface="primary_surface",
            directive_id=directive.id,
            ok=True,
            detail=self.transport.mode,
        )

    async def clear(self) -> None:
        await self.transport.send_frame(ScreenFrame(title="", body=""))

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(10)
            try:
                await self.transport.heartbeat()
            except Exception as exc:  # noqa: BLE001 - health is reported through trace
                if self._ctx:
                    self._ctx.app.trace.append(f"steelseries_oled heartbeat failed: {exc}")

    @classmethod
    def _frame_from_directive(cls, directive: Directive) -> ScreenFrame:
        if directive.kind == "display.card":
            title = str(directive.payload.get("title", "Keyboard Familiar"))
            body = str(directive.payload.get("subtitle", ""))
        elif directive.kind == "display.text":
            title = "Keyboard Familiar"
            body = str(directive.payload.get("text", ""))
        else:
            raise ValueError(f"SteelSeries OLED does not support directive kind {directive.kind!r}.")
        return ScreenFrame(
            title=title[: cls.capabilities.max_chars_title], body=body[: cls.capabilities.max_chars_body]
        )
