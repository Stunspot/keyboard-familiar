from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from ipaddress import ip_address
from pathlib import Path
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

GAME_ID = "KEYBOARD_FAMILIAR"
SIGNAL_GAME_ID = "KEYBOARD_FAMILIAR_ALERTS"
GLANCE_EVENT_ID = "GLANCE"
ALERT_EVENT_ID = "ALERT"
SIGNAL_EVENT_ID = "SIGNAL"
SUPPORTED_CAPABILITIES = frozenset({"screen", "function_key_lighting"})


class SteelSeriesError(RuntimeError):
    """An actionable SteelSeries GameSense failure."""


@dataclass(frozen=True)
class DeviceFrame:
    title: str
    body: str
    alert: bool = False
    signal_color: tuple[int, int, int] = (255, 64, 32)


# Compatibility for integrations that imported the MVP name.
ScreenFrame = DeviceFrame


class SteelSeriesTransport(Protocol):
    mode: str
    capabilities: frozenset[str]

    async def initialize(self) -> None: ...

    async def send_frame(self, frame: DeviceFrame) -> None: ...

    async def heartbeat(self) -> None: ...


class RecordingSteelSeriesTransport:
    """Deterministic substitute used only when simulation is explicitly selected."""

    mode = "simulate"

    def __init__(self, capabilities: frozenset[str] = SUPPORTED_CAPABILITIES) -> None:
        self.capabilities = capabilities
        self.initialized = False
        self.frames: list[DeviceFrame] = []
        self.heartbeat_count = 0

    async def initialize(self) -> None:
        self.initialized = True

    async def send_frame(self, frame: DeviceFrame) -> None:
        if not self.initialized:
            await self.initialize()
        if not frame.alert and "screen" not in self.capabilities:
            raise SteelSeriesError(
                "This message needs the configured `screen` capability. Use --alert for lighting-only hardware."
            )
        self.frames.append(frame)

    async def heartbeat(self) -> None:
        self.heartbeat_count += 1


class GameSenseTransport:
    """SteelSeries GG GameSense adapter for screened and illuminated keyboards."""

    mode = "gamesense"

    def __init__(
        self,
        core_props_path: Path | None = None,
        timeout_seconds: float = 2.0,
        capabilities: frozenset[str] = SUPPORTED_CAPABILITIES,
    ) -> None:
        unknown = capabilities - SUPPORTED_CAPABILITIES
        if unknown or not capabilities:
            raise ValueError(f"Invalid SteelSeries capabilities: {sorted(unknown or capabilities)}")
        self.core_props_path = core_props_path or self.default_core_props_path()
        self.timeout_seconds = timeout_seconds
        self.capabilities = capabilities
        self.base_url: str | None = None
        self.initialized = False

    @staticmethod
    def default_core_props_path() -> Path:
        program_data = os.environ.get("PROGRAMDATA")
        if program_data:
            return Path(program_data) / "SteelSeries" / "SteelSeries Engine 3" / "coreProps.json"
        return Path("C:/ProgramData/SteelSeries/SteelSeries Engine 3/coreProps.json")

    def discover(self) -> str:
        path = self.core_props_path
        if not path.is_file():
            raise SteelSeriesError(
                f"SteelSeries GG Engine is unavailable: {path} was not found. "
                "Install and start SteelSeries GG, open Engine, then run `familiar doctor`."
            )
        try:
            props = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SteelSeriesError(f"Cannot read SteelSeries Engine discovery file {path}: {exc}") from exc

        address = props.get("address")
        if not isinstance(address, str) or not address.strip():
            raise SteelSeriesError(f"SteelSeries Engine discovery file {path} has no valid `address` value.")
        base_url = f"http://{address.strip()}"
        parsed = urlsplit(base_url)
        try:
            host = parsed.hostname
            port = parsed.port
        except ValueError as exc:
            raise SteelSeriesError(
                f"SteelSeries Engine returned an invalid local address: {address!r}."
            ) from exc
        if host == "localhost":
            is_loopback = True
        else:
            try:
                is_loopback = bool(host) and ip_address(host).is_loopback
            except ValueError:
                is_loopback = False
        if not is_loopback or port is None:
            raise SteelSeriesError(
                f"SteelSeries Engine returned unsafe address {address!r}; only a loopback host with a port is accepted."
            )
        return base_url

    async def initialize(self) -> None:
        if self.initialized:
            return
        self.base_url = self.discover()
        if "screen" in self.capabilities:
            await self._metadata(GAME_ID, "Keyboard Familiar")
            await self._bind_event(GLANCE_EVENT_ID, [self._screen_handler()])
            await self._bind_event(ALERT_EVENT_ID, [self._screen_handler()])
        if "function_key_lighting" in self.capabilities:
            await self._metadata(SIGNAL_GAME_ID, "Keyboard Familiar Alerts")
            await self._bind_event(
                SIGNAL_EVENT_ID,
                [self._lighting_handler()],
                game=SIGNAL_GAME_ID,
            )
        self.initialized = True

    async def send_frame(self, frame: DeviceFrame) -> None:
        if not frame.alert and "screen" not in self.capabilities:
            raise SteelSeriesError(
                "This message needs the configured `screen` capability. Use --alert for lighting-only hardware."
            )
        await self.initialize()
        red, green, blue = frame.signal_color
        context = {
            "title": frame.title,
            "body": frame.body,
            "signal-color": {"red": red, "green": green, "blue": blue},
        }
        if "screen" in self.capabilities:
            await self._post(
                "game_event",
                {
                    "game": GAME_ID,
                    "event": ALERT_EVENT_ID if frame.alert else GLANCE_EVENT_ID,
                    "data": {
                        "value": 100 if frame.alert else 0,
                        "frame": context,
                    },
                },
            )
        if frame.alert and "function_key_lighting" in self.capabilities:
            await self._post(
                "game_event",
                {
                    "game": SIGNAL_GAME_ID,
                    "event": SIGNAL_EVENT_ID,
                    "data": {"value": 100, "frame": context},
                },
            )

    async def heartbeat(self) -> None:
        if self.initialized and "screen" in self.capabilities:
            await self._post("game_heartbeat", {"game": GAME_ID})

    async def _metadata(self, game: str, display_name: str) -> None:
        await self._post(
            "game_metadata",
            {"game": game, "game_display_name": display_name, "developer": "Keyboard Familiar"},
        )

    async def _bind_event(
        self,
        event: str,
        handlers: list[dict[str, Any]],
        *,
        game: str = GAME_ID,
    ) -> None:
        await self._post(
            "bind_game_event",
            {
                "game": game,
                "event": event,
                "min_value": 0,
                "max_value": 100,
                "value_optional": True,
                "handlers": handlers,
            },
        )

    @staticmethod
    def _screen_handler() -> dict[str, Any]:
        return {
            "device-type": "screened",
            "zone": "one",
            "mode": "screen",
            "datas": [
                {
                    "lines": [
                        {"has-text": True, "context-frame-key": "title", "bold": True},
                        {"has-text": True, "context-frame-key": "body", "wrap": 1},
                    ]
                }
            ],
        }

    @staticmethod
    def _lighting_handler() -> dict[str, Any]:
        return {
            "device-type": "keyboard",
            "zone": "function-keys",
            "mode": "context-color",
            "context-frame-key": "signal-color",
            "rate": {"frequency": 2},
        }

    async def _post(self, endpoint: str, payload: dict[str, Any]) -> None:
        if self.base_url is None:
            raise SteelSeriesError("SteelSeries GameSense endpoint has not been discovered.")
        await asyncio.to_thread(self._post_sync, endpoint, payload)

    def _post_sync(self, endpoint: str, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            f"{self.base_url}/{endpoint}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310 - loopback validated
                status = response.status
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace").strip()
            raise SteelSeriesError(
                f"SteelSeries GameSense rejected /{endpoint} with HTTP {exc.code}: {detail or exc.reason}"
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            self.initialized = False
            failed_url = self.base_url
            self.base_url = None
            raise SteelSeriesError(
                f"Cannot reach SteelSeries GG Engine at {failed_url}: {exc}. "
                "The next card will rediscover GG; confirm Engine is running or run `familiar doctor`."
            ) from exc
        if status != 200:
            raise SteelSeriesError(f"SteelSeries GameSense /{endpoint} returned unexpected HTTP {status}.")
