import asyncio
from pathlib import Path

from familiar.adapters.steelseries.transport import RecordingSteelSeriesTransport
from familiar.bootstrap import create_app


def test_alert_preempts_glance() -> None:
    async def _run() -> None:
        app = await create_app(
            Path("config"),
            steelseries_transport=RecordingSteelSeriesTransport(),
            start_background_sensors=False,
        )
        sensor = app.plugins.sensors["manual_trigger"]
        try:
            await sensor.trigger("test.ping", payload={"message": "idle"})
            await sensor.trigger("build.failed", payload={"project": "demo", "summary": "bad build"})

            console = app.plugins.surfaces["console_debug"]
            assert console.rendered[-1].scene == "ALERT"
            assert console.rendered[-1].kind == "display.card"
        finally:
            await app.plugins.stop_all()

    asyncio.run(_run())
