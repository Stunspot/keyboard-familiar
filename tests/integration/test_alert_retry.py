import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from familiar.adapters.steelseries.transport import DeviceFrame, SteelSeriesError
from familiar.bootstrap import create_app


class FailingSteelSeriesTransport:
    mode = "test-failure"
    capabilities = frozenset({"screen", "function_key_lighting"})

    async def initialize(self) -> None:
        return

    async def send_frame(self, frame: DeviceFrame) -> None:
        raise SteelSeriesError("device disconnected")

    async def heartbeat(self) -> None:
        return


def test_focus_alert_retries_when_console_mirror_succeeds_but_device_fails(tmp_path: Path) -> None:
    async def run() -> None:
        app = await create_app(
            Path("config"),
            runtime_file=tmp_path / "runtime.json",
            steelseries_transport=FailingSteelSeriesTransport(),
            start_background_sensors=False,
        )
        try:
            now = datetime.now(timezone.utc)
            app.focus_store.start("Reconnect device", 1, now=now - timedelta(minutes=2))
            sensor = app.plugins.sensors["glance_deck"]
            delivered = await sensor.publish_once(app)

            assert delivered is False
            assert app.focus_store.snapshot().completion_announced is False
            assert any("deck.alert retry" in line for line in app.trace)
            console = app.plugins.surfaces["console_debug"]
            assert console.rendered[-1].payload["title"] == "FOCUS COMPLETE"
        finally:
            await app.plugins.stop_all()

    asyncio.run(run())
