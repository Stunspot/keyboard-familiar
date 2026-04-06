import asyncio
from pathlib import Path

from familiar.bootstrap import create_app


def test_alert_preempts_glance() -> None:
    async def _run() -> None:
        app = await create_app(Path("config"))
        sensor = app.plugins.sensors["manual_trigger"]

        await sensor.trigger("test.ping", payload={"message": "idle"})
        await sensor.trigger("build.failed", payload={"project": "demo", "summary": "bad build"})

        console = app.plugins.surfaces["console_debug"]
        assert console.rendered[-1].scene == "ALERT"
        assert console.rendered[-1].kind == "display.card"

    asyncio.run(_run())
