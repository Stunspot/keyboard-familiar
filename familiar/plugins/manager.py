from __future__ import annotations

from dataclasses import dataclass, field

from .base import BrainPlugin, PluginContext, SensorPlugin, SurfacePlugin


@dataclass
class PluginManager:
    sensors: dict[str, SensorPlugin] = field(default_factory=dict)
    brains: dict[str, BrainPlugin] = field(default_factory=dict)
    surfaces: dict[str, SurfacePlugin] = field(default_factory=dict)

    async def start_all(self, app: "FamiliarApp") -> None:
        for name, sensor in self.sensors.items():
            await sensor.start(PluginContext(app=app, config={"name": name}))
        for name, brain in self.brains.items():
            await brain.start(PluginContext(app=app, config={"name": name}))
        for name, surface in self.surfaces.items():
            await surface.start(PluginContext(app=app, config={"name": name}))

    async def stop_all(self) -> None:
        for plugin in [*self.sensors.values(), *self.brains.values(), *self.surfaces.values()]:
            await plugin.stop()

    def surface_names(self) -> list[str]:
        return list(self.surfaces.keys())

    def plugin_names(self) -> list[str]:
        return [*self.sensors.keys(), *self.brains.keys(), *self.surfaces.keys()]
