from __future__ import annotations

import asyncio
from pathlib import Path

from familiar.adapters.steelseries.transport import (
    SUPPORTED_CAPABILITIES,
    GameSenseTransport,
    RecordingSteelSeriesTransport,
    SteelSeriesTransport,
)
from familiar.app import FamiliarApp
from familiar.core.arbitration import Arbitrator
from familiar.core.bus import InMemoryEventBus
from familiar.core.config import load_config_dir
from familiar.core.focus import FocusStore, focus_path_for
from familiar.core.glance import GlanceDeck, parse_deck_settings
from familiar.core.routing import Router
from familiar.core.scenes import SceneManager
from familiar.core.state import InMemoryStateStore
from familiar.plugins.brains.rules_basic import RulesBasicBrain
from familiar.plugins.manager import PluginManager
from familiar.plugins.sensors.glance_deck import GlanceDeckSensor
from familiar.plugins.sensors.gpu_vram import GpuVramSensor
from familiar.plugins.sensors.manual_trigger import ManualTriggerSensor
from familiar.plugins.sensors.timer import TimerSensor
from familiar.plugins.surfaces.console_debug import ConsoleDebugSurface
from familiar.plugins.surfaces.steelseries_oled import SteelSeriesSurface


def _as_int(value: object, name: str, minimum: int = 0) -> int:
    try:
        result = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer; got {value!r}.") from exc
    if result < minimum:
        raise ValueError(f"{name} must be at least {minimum}; got {result}.")
    return result


def _as_float(
    value: object,
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


def _steelseries_config(plugins: dict) -> tuple[dict, str]:
    if "steelseries" in plugins:
        return _plugin_config(plugins, "steelseries"), "steelseries"
    if "steelseries_oled" in plugins:
        return _plugin_config(plugins, "steelseries_oled"), "steelseries_oled"
    return {}, "steelseries"


def _capabilities(config: dict, config_name: str) -> frozenset[str]:
    default = ["screen"] if config_name == "steelseries_oled" else sorted(SUPPORTED_CAPABILITIES)
    value = config.get("capabilities", default)
    if not isinstance(value, list) or not value or not all(isinstance(item, str) for item in value):
        raise ValueError(f"plugins.{config_name}.capabilities must be a non-empty YAML list.")
    capabilities = frozenset(value)
    unknown = capabilities - SUPPORTED_CAPABILITIES
    if unknown:
        raise ValueError(
            f"plugins.{config_name}.capabilities contains unsupported values: {', '.join(sorted(unknown))}."
        )
    return capabilities


def _color(config: dict, config_name: str) -> tuple[int, int, int]:
    value = config.get("alert_color", [255, 64, 32])
    if (
        not isinstance(value, list)
        or len(value) != 3
        or any(isinstance(item, bool) or not isinstance(item, int) or not 0 <= item <= 255 for item in value)
    ):
        raise ValueError(f"plugins.{config_name}.alert_color must be three integers from 0 to 255.")
    return value[0], value[1], value[2]


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

    actual_runtime_file = runtime_file or Path(".familiar/runtime.json")
    runtime_cfg = config.get("app", {}).get("runtime", {})
    if not isinstance(runtime_cfg, dict):
        raise ValueError("app.yaml `runtime` must be a YAML mapping.")
    timezone_name = runtime_cfg.get("timezone", "local")
    if not isinstance(timezone_name, str) or not timezone_name:
        raise ValueError("runtime.timezone must be `local` or an IANA timezone string.")
    focus_store = FocusStore(focus_path_for(actual_runtime_file))
    deck_settings = parse_deck_settings(config.get("deck", {}))
    glance_deck = GlanceDeck(deck_settings, focus_store, timezone_name=timezone_name)

    steelseries_cfg, steelseries_name = _steelseries_config(plugins_cfg)
    steelseries_enabled = _enabled(steelseries_cfg, True)
    steelseries_capabilities = _capabilities(steelseries_cfg, steelseries_name)
    alert_color = _color(steelseries_cfg, steelseries_name)

    bus = InMemoryEventBus()
    state = InMemoryStateStore()
    scene_manager = SceneManager(
        dwell_ms=_as_int(arbitration_cfg.get("min_dwell_ms", 5000), "arbitration.min_dwell_ms")
    )
    arbitrator = Arbitrator(
        scene_manager,
        dedupe_window_ms=_as_int(
            arbitration_cfg.get("dedupe_window_ms", 30000), "arbitration.dedupe_window_ms"
        ),
    )

    sensors = {}
    if _enabled(_plugin_config(plugins_cfg, "manual_trigger"), True):
        sensors["manual_trigger"] = ManualTriggerSensor()

    deck_cfg = _plugin_config(plugins_cfg, "glance_deck")
    if _enabled(deck_cfg, True):
        sensors["glance_deck"] = GlanceDeckSensor(
            glance_deck,
            alerts_only=steelseries_enabled and "screen" not in steelseries_capabilities,
        )

    gpu_cfg = _plugin_config(plugins_cfg, "gpu_vram")
    if _enabled(gpu_cfg, False):
        sensors["gpu_vram"] = GpuVramSensor(
            every_seconds=_as_int(gpu_cfg.get("every_seconds", 3), "gpu_vram.every_seconds", 1),
            gpu_index=_as_int(gpu_cfg.get("gpu_index", 0), "gpu_vram.gpu_index"),
            change_threshold_pct=_as_float(
                gpu_cfg.get("change_threshold_pct", 2.0),
                "gpu_vram.change_threshold_pct",
                maximum=100.0,
            ),
            alert_threshold_pct=_as_float(
                gpu_cfg.get("alert_threshold_pct", 90.0),
                "gpu_vram.alert_threshold_pct",
                maximum=100.0,
            ),
        )
    timer_cfg = _plugin_config(plugins_cfg, "timer")
    if _enabled(timer_cfg, False):
        sensors["timer"] = TimerSensor(
            every_seconds=_as_int(timer_cfg.get("every_seconds", 30), "timer.every_seconds", 1)
        )

    surfaces = {}
    if _enabled(_plugin_config(plugins_cfg, "console_debug"), True):
        surfaces["console_debug"] = ConsoleDebugSurface()

    if steelseries_enabled:
        mode = steelseries_mode or steelseries_cfg.get("mode", "gamesense")
        if mode not in {"gamesense", "simulate"}:
            raise ValueError(f"plugins.{steelseries_name}.mode must be `gamesense` or `simulate`.")
        transport = steelseries_transport
        if transport is None and mode == "simulate":
            transport = RecordingSteelSeriesTransport(capabilities=steelseries_capabilities)
        if transport is None:
            configured_path = steelseries_cfg.get("core_props_path")
            if configured_path is not None and not isinstance(configured_path, str):
                raise ValueError(f"plugins.{steelseries_name}.core_props_path must be a path string.")
            path = Path(configured_path).expanduser() if configured_path else None
            timeout = _as_float(
                steelseries_cfg.get("timeout_seconds", 2.0),
                f"plugins.{steelseries_name}.timeout_seconds",
                0.1,
                10.0,
            )
            transport = GameSenseTransport(
                core_props_path=path,
                timeout_seconds=timeout,
                capabilities=steelseries_capabilities,
            )
        surfaces["primary_surface"] = SteelSeriesSurface(transport=transport, alert_color=alert_color)

    if not surfaces:
        raise ValueError("At least one output surface must be enabled in plugins.yaml.")

    rules_cfg = _plugin_config(plugins_cfg, "rules_basic")
    brains = {"rules_basic": RulesBasicBrain()} if _enabled(rules_cfg, True) else {}
    manager = PluginManager(sensors=sensors, brains=brains, surfaces=surfaces)
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
        focus_store=focus_store,
        glance_deck=glance_deck,
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
