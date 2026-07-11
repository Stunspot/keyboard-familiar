import asyncio
from pathlib import Path

from familiar.adapters.steelseries.transport import RecordingSteelSeriesTransport
from familiar.bootstrap import create_app


def test_persisted_state_and_trace_visible_across_app_instances(tmp_path: Path) -> None:
    async def _run() -> None:
        runtime_file = tmp_path / "runtime.json"

        app1 = await create_app(
            Path("config"),
            runtime_file=runtime_file,
            steelseries_transport=RecordingSteelSeriesTransport(),
            start_background_sensors=False,
        )
        try:
            await app1.plugins.sensors["manual_trigger"].trigger("test.ping", payload={"message": "persist"})
        finally:
            await app1.plugins.stop_all()

        app2 = await create_app(
            Path("config"),
            runtime_file=runtime_file,
            steelseries_transport=RecordingSteelSeriesTransport(),
            start_background_sensors=False,
        )
        try:
            runtime = app2.get_state_snapshot().domains.get("runtime", {})

            assert runtime.get("last_event", {}).get("type") == "test.ping"
            assert runtime.get("event_count") == 1
            assert any("event.received" in line for line in app2.trace)
        finally:
            await app2.plugins.stop_all()

    asyncio.run(_run())
