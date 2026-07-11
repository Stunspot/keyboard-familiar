import asyncio
from pathlib import Path

from familiar.adapters.steelseries.transport import RecordingSteelSeriesTransport
from familiar.bootstrap import create_app


def test_manual_event_reaches_debug_and_explicit_device_substitute() -> None:
    async def _run() -> None:
        transport = RecordingSteelSeriesTransport()
        app = await create_app(
            Path("config"), steelseries_transport=transport, start_background_sensors=False
        )
        sensor = app.plugins.sensors["manual_trigger"]
        try:
            await sensor.trigger("test.ping", payload={"message": "hello"})

            console = app.plugins.surfaces["console_debug"]

            assert len(console.rendered) == 1
            assert console.rendered[0].kind == "display.text"
            assert len(transport.frames) == 1
            assert transport.frames[0].title == "Keyboard Familiar"
            assert transport.frames[0].body == "hello"
            state = app.get_state_snapshot().domains["runtime"]
            assert state["last_event"]["type"] == "test.ping"
            assert state["event_count"] == 1
            assert any("proposal.emitted" in line for line in app.trace)
            assert any("directive.accepted" in line for line in app.trace)
            assert any("render.result" in line for line in app.trace)
            assert any(line.startswith("event test.ping") for line in app.trace)
        finally:
            await app.plugins.stop_all()

    asyncio.run(_run())
