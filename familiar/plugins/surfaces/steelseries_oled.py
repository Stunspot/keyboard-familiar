from __future__ import annotations

import asyncio
import contextlib

from familiar.adapters.steelseries.transport import DeviceFrame, SteelSeriesTransport
from familiar.core.models import Directive, PluginManifest, RenderResult, SurfaceCapabilities


class SteelSeriesSurface:
    manifest = PluginManifest(
        name="steelseries", version="0.2.0", plugin_type="surface", consumes=["display.*"]
    )
    capabilities = SurfaceCapabilities(
        surface="primary_surface",
        supports={"display.text", "display.card"},
        max_chars_title=20,
        max_chars_body=40,
        supports_icons=False,
    )

    def __init__(
        self,
        transport: SteelSeriesTransport,
        alert_color: tuple[int, int, int] = (255, 64, 32),
    ) -> None:
        self.transport = transport
        self.alert_color = alert_color
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
        frame = self.frame_from_directive(directive)
        await self.transport.send_frame(frame)
        if self._heartbeat_task is None:
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        if self._ctx:
            self._ctx.app.trace.append(
                f"steelseries rendered {directive.kind} scene={directive.scene} "
                f"mode={self.transport.mode} capabilities={','.join(sorted(self.transport.capabilities))}"
            )
        return RenderResult(
            surface="primary_surface",
            directive_id=directive.id,
            ok=True,
            detail=f"{self.transport.mode}:{'+'.join(sorted(self.transport.capabilities))}",
        )

    async def clear(self) -> None:
        await self.transport.send_frame(DeviceFrame(title="", body=""))

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(10)
            try:
                await self.transport.heartbeat()
            except Exception as exc:  # noqa: BLE001 - health is reported through trace
                if self._ctx:
                    self._ctx.app.trace.append(f"steelseries heartbeat failed: {exc}")

    def frame_from_directive(self, directive: Directive) -> DeviceFrame:
        if directive.kind == "display.card":
            title = str(directive.payload.get("title", "Keyboard Familiar"))
            body = str(directive.payload.get("subtitle", ""))
        elif directive.kind == "display.text":
            title = str(directive.payload.get("title", "Keyboard Familiar"))
            body = str(directive.payload.get("text", ""))
        else:
            raise ValueError(f"SteelSeries surface does not support directive kind {directive.kind!r}.")
        alert = directive.scene == "ALERT" or bool(directive.payload.get("alert", False))
        return DeviceFrame(
            title=title[: self.capabilities.max_chars_title],
            body=body[: self.capabilities.max_chars_body],
            alert=alert,
            signal_color=self.alert_color,
        )


# Compatibility for code written against the OLED-only MVP.
SteelSeriesOledSurface = SteelSeriesSurface
