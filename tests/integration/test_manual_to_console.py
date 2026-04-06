import asyncio
from pathlib import Path

from familiar.bootstrap import create_app


def test_manual_event_reaches_debug_and_oled_dry_run() -> None:
    async def _run() -> None:
        app = await create_app(Path("config"))
        sensor = app.plugins.sensors["manual_trigger"]
        await sensor.trigger("test.ping", payload={"message": "hello"})

        console = app.plugins.surfaces["console_debug"]
        oled = app.plugins.surfaces["primary_surface"]

        assert len(console.rendered) == 1
        assert console.rendered[0].kind == "display.text"
        assert len(oled.transport.sent) == 1
        assert oled.transport.sent[0]["kind"] == "display.text"
        state = app.get_state_snapshot().domains["runtime"]
        assert state["last_event"]["type"] == "test.ping"
        assert state["event_count"] == 1
        assert any("proposal.emitted" in line for line in app.trace)
        assert any("directive.accepted" in line for line in app.trace)
        assert any("render.result" in line for line in app.trace)
        assert any(line.startswith("event test.ping") for line in app.trace)

    asyncio.run(_run())
