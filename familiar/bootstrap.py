from __future__ import annotations

import asyncio
from pathlib import Path

from familiar.adapters.steelseries.transport import (
    GameSenseTransport,
    RecordingSteelSeriesTransport,
    SteelSeriesTransport,
)
from familiar.app import FamiliarApp
from familiar.core.arbitration import Arbitrator
from familiar.core.bus import InMemoryEventBus
from familiar.core.config import load_config_dir
from familiar.core.routing import Router
from familiar.core.scenes import SceneManager
from familiar.core.state import InMemoryStateStore
from familiar.plugins.brains.rules_basic import RulesBasicBrain
from familiar.plugins.manager import PluginManager
from familiar.plugins.sensors.gpu_vram import GpuVramSensor
from familiar.plugins.sensors.manual_trigger import ManualTriggerSensor
from familiar.plugins.sensors.timer import TimerSensor
from familiar.plugins.surfaces.console_debug import ConsoleDebugSurface
from familiar.plugins.surfaces.steelseries_oled import SteelSeriesOledSurface


def _as_int(value: object, default: int, name: str, minimum: int = 0) -> int:
    try:
        result = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer; got {value!r}.") from exc
    if result < minimum:
        raise ValueError(f"{name} must be at least {minimum}; got {result}.")
    return result


def _as_float(
    value: object,
    default: float,
    name: str,
    minimum: float = 0.0,
    maximum: float | None = None,
) -> float:
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number; got {value!r}.") from exc
    if result < minimum:
        raise ValueError(f"{name} must be at least {minimum}; got {result}.")
    if maximum is not None and result > maximum:
        raise ValueError(f"{name} must be at most {maximum}; got {result}.")
    return result


def _plugin_config(plugins: dict, name: str) -> dict:
    value = plugins.get(name, {})
    if not isinstance(value, dict):
        raise ValueError(f"plugins.{name} must be a YAML mapping.")
    return value


def _enabled(config: dict, default: bool) -> bool:
    value = config.get("enabled", default)
    if not isinstance(value, bool):
        raise ValueError(f"enabled must be true or false; got {value!r}.")
    return value


async def create_app(
    config_dir: Path,
    runtime_file: Path | None = None,
    *,
    steelseries_mode: str | None = None,
    steelseries_transport: SteelSeriesTransport | None = None,
    start_background_sensors: bool = True,
) -> FamiliarApp:
    config = load_config_dir(config_dir)
    plugins_cfg = config.get("plugins", {}).get("plugins", {})
    if not isinstance(plugins_cfg, dict):
        raise ValueError("plugins.yaml `plugins` must be a YAML mapping.")
    arbitration_cfg = config.get("app", {}).get("arbitration", {})
    if not isinstance(arbitration_cfg, dict):
        raise ValueError("app.yaml `arbitration` must be a YAML mapping.")

    bus = InMemoryEventBus()
    state = InMemoryStateStore()
    scene_manager = SceneManager(
        dwell_ms=_as_int(arbitration_cfg.get("min_dwell_ms", 5000), 5000, "arbitration.min_dwell_ms")
    )
    arbitrator = Arbitrator(
        scene_manager,
        dedupe_window_ms=_as_int(
            arbitration_cfg.get("dedupe_window_ms", 30000), 30000, "arbitration.dedupe_window_ms"
        ),
    )

    sensors = {}
    if _enabled(_plugin_config(plugins_cfg, "manual_trigger"), True):
        sensors["manual_trigger"] = ManualTriggerSensor()

    gpu_cfg = _plugin_config(plugins_cfg, "gpu_vram")
    if _enabled(gpu_cfg, False):
        sensors["gpu_vram"] = GpuVramSensor(
            every_seconds=_as_int(gpu_cfg.get("every_seconds", 3), 3, "gpu_vram.every_seconds", 1),
            gpu_index=_as_int(gpu_cfg.get("gpu_index", 0), 0, "gpu_vram.gpu_index"),
            change_threshold_pct=_as_float(
                gpu_cfg.get("change_threshold_pct", 2.0),
                2.0,
                "gpu_vram.change_threshold_pct",
                maximum=100.0,
            ),
            alert_threshold_pct=_as_float(
                gpu_cfg.get("alert_threshold_pct", 90.0),
                90.0,
                "gpu_vram.alert_threshold_pct",
                maximum=100.0,
            ),
        )
    timer_cfg = _plugin_config(plugins_cfg, "timer")
    if _enabled(timer_cfg, False):
        sensors["timer"] = TimerSensor(
            every_seconds=_as_int(timer_cfg.get("every_seconds", 30), 30, "timer.every_seconds", 1)
        )

    surfaces = {}
    console_cfg = _plugin_config(plugins_cfg, "console_debug")
    if _enabled(console_cfg, True):
        surfaces["console_debug"] = ConsoleDebugSurface()

    steelseries_cfg = _plugin_config(plugins_cfg, "steelseries_oled")
    if _enabled(steelseries_cfg, True):
        mode = steelseries_mode or steelseries_cfg.get("mode", "gamesense")
        if mode not in {"gamesense", "simulate"}:
            raise ValueError("steelseries_oled.mode must be `gamesense` or `simulate`.")
        transport = steelseries_transport
        if transport is None and mode == "simulate":
            transport = RecordingSteelSeriesTransport()
        if transport is None:
            configured_path = steelseries_cfg.get("core_props_path")
            if configured_path is not None and not isinstance(configured_path, str):
                raise ValueError("steelseries_oled.core_props_path must be a path string.")
            path = Path(configured_path).expanduser() if configured_path else None
            timeout = _as_float(
                steelseries_cfg.get("timeout_seconds", 2.0), 2.0, "steelseries_oled.timeout_seconds", 0.1
            )
            transport = GameSenseTransport(core_props_path=path, timeout_seconds=timeout)
        surfaces["primary_surface"] = SteelSeriesOledSurface(transport=transport)

    if not surfaces:
        raise ValueError("At least one output surface must be enabled in plugins.yaml.")

    rules_cfg = _plugin_config(plugins_cfg, "rules_basic")
    brains = {"rules_basic": RulesBasicBrain()} if _enabled(rules_cfg, True) else {}
    manager = PluginManager(
        sensors=sensors,
        brains=brains,
        surfaces=surfaces,
    )
    runtime_cfg = config.get("app", {}).get("runtime", {})
    if not isinstance(runtime_cfg, dict):
        raise ValueError("app.yaml `runtime` must be a YAML mapping.")
    mirror_debug = runtime_cfg.get("debug_surface_mirror", True)
    if not isinstance(mirror_debug, bool):
        raise ValueError("runtime.debug_surface_mirror must be true or false.")
    router = Router(manager.surfaces, mirror_debug=mirror_debug)

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
    await manager.start_all(app, start_background_sensors=start_background_sensors)
    return app


async def run_app(app: FamiliarApp) -> None:
    app.trace.append("runtime.started")
    app.save_runtime()
    try:
        while True:
            await asyncio.sleep(1)
    finally:
        await app.plugins.stop_all()
