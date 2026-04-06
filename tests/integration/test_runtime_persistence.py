import asyncio
from pathlib import Path

from familiar.bootstrap import create_app


def test_persisted_state_and_trace_visible_across_app_instances(tmp_path: Path) -> None:
    async def _run() -> None:
        runtime_file = tmp_path / "runtime.json"

        app1 = await create_app(Path("config"), runtime_file=runtime_file)
        await app1.plugins.sensors["manual_trigger"].trigger("test.ping", payload={"message": "persist"})

        app2 = await create_app(Path("config"), runtime_file=runtime_file)
        runtime = app2.get_state_snapshot().domains.get("runtime", {})

        assert runtime.get("last_event", {}).get("type") == "test.ping"
        assert runtime.get("event_count") == 1
        assert any("event.received" in line for line in app2.trace)

    asyncio.run(_run())
