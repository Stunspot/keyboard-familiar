import asyncio
from pathlib import Path

from familiar.bootstrap import create_app


def test_gpu_vram_event_updates_state_and_renders_alert() -> None:
    async def _run() -> None:
        app = await create_app(Path("config"))
        sensor = app.plugins.sensors["manual_trigger"]

        await sensor.trigger(
            "gpu.vram.changed",
            payload={
                "percent_used": 72.5,
                "used_gib": 8.7,
                "total_gib": 12.0,
                "gpu_index": 0,
                "sample_source": "test",
                "alert_threshold_pct": 90.0,
            },
        )
        await sensor.trigger(
            "gpu.vram.changed",
            payload={
                "percent_used": 92.2,
                "used_gib": 11.1,
                "total_gib": 12.0,
                "gpu_index": 0,
                "sample_source": "test",
                "alert_threshold_pct": 90.0,
            },
        )

        snapshot = app.get_state_snapshot()
        assert snapshot.domains["gpu"]["vram"]["percent_used"] == 92.2
        assert snapshot.domains["gpu"]["vram"]["used_gib"] == 11.1

        console = app.plugins.surfaces["console_debug"]
        assert console.rendered[0].kind == "display.text"
        assert console.rendered[-1].kind == "display.card"
        assert console.rendered[-1].scene == "ALERT"

        assert any("event.received type=gpu.vram.changed" in line for line in app.trace)
        assert any("proposal.emitted" in line for line in app.trace)
        assert any("directive.accepted" in line for line in app.trace)
        assert any("render.result" in line for line in app.trace)

    asyncio.run(_run())
