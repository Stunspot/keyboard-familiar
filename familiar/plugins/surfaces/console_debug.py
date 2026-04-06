from __future__ import annotations

from familiar.core.models import Directive, PluginManifest, RenderResult, SurfaceCapabilities


class ConsoleDebugSurface:
    manifest = PluginManifest(name="console_debug", version="0.1.0", plugin_type="surface", consumes=["display.*"])
    capabilities = SurfaceCapabilities(surface="console_debug", supports={"display.text", "display.card", "log.entry"})

    def __init__(self) -> None:
        self.rendered: list[Directive] = []

    async def start(self, ctx) -> None:
        self._ctx = ctx

    async def stop(self) -> None:
        self._ctx = None

    async def render(self, directive: Directive) -> RenderResult:
        self.rendered.append(directive)
        if hasattr(self, "_ctx") and self._ctx:
            self._ctx.app.trace.append(f"console_debug rendered {directive.kind} scene={directive.scene}")
        return RenderResult(surface="console_debug", directive_id=directive.id, ok=True)

    async def clear(self) -> None:
        self.rendered.clear()
