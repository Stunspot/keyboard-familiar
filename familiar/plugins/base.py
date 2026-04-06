from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from familiar.core.models import BrainResult, Directive, Event, PluginManifest, RenderResult, StateSnapshot, SurfaceCapabilities


@dataclass(slots=True)
class PluginContext:
    app: "FamiliarApp"
    config: dict = field(default_factory=dict)


class Plugin(Protocol):
    manifest: PluginManifest

    async def start(self, ctx: PluginContext) -> None: ...
    async def stop(self) -> None: ...


class SensorPlugin(Plugin, Protocol):
    pass


class BrainPlugin(Plugin, Protocol):
    async def on_event(self, event: Event, snapshot: StateSnapshot) -> BrainResult: ...


class SurfacePlugin(Plugin, Protocol):
    capabilities: SurfaceCapabilities

    async def render(self, directive: Directive) -> RenderResult: ...
    async def clear(self) -> None: ...
