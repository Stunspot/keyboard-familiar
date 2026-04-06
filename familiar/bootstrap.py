from __future__ import annotations

import asyncio
from pathlib import Path

from familiar.app import FamiliarApp
from familiar.core.arbitration import Arbitrator
from familiar.core.bus import InMemoryEventBus
from familiar.core.config import load_config_dir
from familiar.core.routing import Router
from familiar.core.scenes import SceneManager
from familiar.core.state import InMemoryStateStore
from familiar.plugins.brains.rules_basic import RulesBasicBrain
from familiar.plugins.manager import PluginManager
from familiar.plugins.sensors.manual_trigger import ManualTriggerSensor
from familiar.plugins.sensors.timer import TimerSensor
from familiar.plugins.surfaces.console_debug import ConsoleDebugSurface
from familiar.plugins.surfaces.steelseries_oled import SteelSeriesOledSurface


def _as_int(value: object, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except Exception:
        return default


async def create_app(config_dir: Path, runtime_file: Path | None = None) -> FamiliarApp:
    config = load_config_dir(config_dir)
    plugins_cfg = config.get("plugins", {}).get("plugins", {})
    arbitration_cfg = config.get("app", {}).get("arbitration", {})

    bus = InMemoryEventBus()
    state = InMemoryStateStore()
    scene_manager = SceneManager(dwell_ms=_as_int(arbitration_cfg.get("min_dwell_ms", 5000), 5000))
    arbitrator = Arbitrator(
        scene_manager,
        dedupe_window_ms=_as_int(arbitration_cfg.get("dedupe_window_ms", 30000), 30000),
    )

    sensors = {"manual_trigger": ManualTriggerSensor()}
    if str(plugins_cfg.get("timer", {}).get("enabled", "true")).lower() != "false":
        sensors["timer"] = TimerSensor(
            every_seconds=_as_int(plugins_cfg.get("timer", {}).get("every_seconds", 30), 30)
        )

    manager = PluginManager(
        sensors=sensors,
        brains={"rules_basic": RulesBasicBrain()},
        surfaces={
            "console_debug": ConsoleDebugSurface(),
            "primary_surface": SteelSeriesOledSurface(dry_run=True),
        },
    )
    router = Router(manager.surfaces)

    app = FamiliarApp(
        bus=bus,
        state=state,
        plugins=manager,
        scene_manager=scene_manager,
        arbitrator=arbitrator,
        router=router,
        runtime_file=runtime_file,
    )
    app.load_runtime()
    await manager.start_all(app)
    return app


async def run_app(app: FamiliarApp) -> None:
    app.trace.append("runtime.started")
    app.save_runtime()
    while True:
        await asyncio.sleep(1)
