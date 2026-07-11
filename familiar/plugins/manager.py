from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .base import BrainPlugin, PluginContext, SensorPlugin, SurfacePlugin

if TYPE_CHECKING:
    from familiar.app import FamiliarApp


@dataclass
class PluginManager:
    sensors: dict[str, SensorPlugin] = field(default_factory=dict)
    brains: dict[str, BrainPlugin] = field(default_factory=dict)
    surfaces: dict[str, SurfacePlugin] = field(default_factory=dict)

    async def start_all(self, app: "FamiliarApp", *, start_background_sensors: bool = True) -> None:
        for name, surface in self.surfaces.items():
            await surface.start(PluginContext(app=app, config={"name": name}))
        for name, brain in self.brains.items():
            await brain.start(PluginContext(app=app, config={"name": name}))
        for name, sensor in self.sensors.items():
            if name == "manual_trigger":
                await sensor.start(PluginContext(app=app, config={"name": name}))
        if start_background_sensors:
            await self.start_background_sensors(app)

    async def start_background_sensors(self, app: "FamiliarApp") -> None:
        for name, sensor in self.sensors.items():
            if name != "manual_trigger":
                await sensor.start(PluginContext(app=app, config={"name": name}))

    async def stop_all(self) -> None:
        for plugin in [*self.sensors.values(), *self.brains.values(), *self.surfaces.values()]:
            await plugin.stop()

    def surface_names(self) -> list[str]:
        return list(self.surfaces.keys())

    def plugin_names(self) -> list[str]:
        return [*self.sensors.keys(), *self.brains.keys(), *self.surfaces.keys()]
