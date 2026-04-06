from __future__ import annotations

from familiar.adapters.steelseries.transport import SteelSeriesTransport
from familiar.core.models import Directive, PluginManifest, RenderResult, SurfaceCapabilities


class SteelSeriesOledSurface:
    manifest = PluginManifest(name="steelseries_oled", version="0.1.0", plugin_type="surface", consumes=["display.*"])
    capabilities = SurfaceCapabilities(
        surface="primary_surface",
        supports={"display.text", "display.card"},
        max_chars_title=20,
        max_chars_body=40,
        supports_icons=False,
    )

    def __init__(self, dry_run: bool = True) -> None:
        self.transport = SteelSeriesTransport(dry_run=dry_run)

    async def start(self, ctx) -> None:
        self._ctx = ctx

    async def stop(self) -> None:
        self._ctx = None

    async def render(self, directive: Directive) -> RenderResult:
        packet = {
            "kind": directive.kind,
            "scene": directive.scene,
            "payload": directive.payload,
        }
        await self.transport.send(packet)
        if hasattr(self, "_ctx") and self._ctx:
            self._ctx.app.trace.append(f"steelseries_oled rendered {directive.kind} scene={directive.scene}")
        return RenderResult(surface="primary_surface", directive_id=directive.id, ok=True, detail="dry-run")

    async def clear(self) -> None:
        await self.transport.send({"kind": "clear"})
