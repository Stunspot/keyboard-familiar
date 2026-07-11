from __future__ import annotations

import asyncio
import json
import platform
from pathlib import Path
from typing import Any, Coroutine

import typer

from familiar.adapters.steelseries.transport import RecordingSteelSeriesTransport, SteelSeriesError
from familiar.bootstrap import create_app, run_app
from familiar.core.config import ConfigurationError, load_config_dir

app = typer.Typer(help="Monitor NVIDIA VRAM and show glance/alert status on a SteelSeries OLED.")
state_app = typer.Typer(help="Inspect persisted runtime state.")
trace_app = typer.Typer(help="Inspect diagnostic runtime traces.")
surfaces_app = typer.Typer(help="Inspect configured output surfaces.")
plugins_app = typer.Typer(help="Inspect configured plugins.")
render_app = typer.Typer(help="Inspect rendering without requiring hardware.")
app.add_typer(state_app, name="state")
app.add_typer(trace_app, name="trace")
app.add_typer(surfaces_app, name="surfaces")
app.add_typer(plugins_app, name="plugins")
app.add_typer(render_app, name="render")


def _execute(operation: Coroutine[Any, Any, None]) -> None:
    try:
        asyncio.run(operation)
    except (ConfigurationError, SteelSeriesError, ValueError, KeyError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc


async def _create(
    config_dir: str,
    runtime_file: str,
    simulate: bool = False,
    *,
    start_background_sensors: bool = False,
):
    return await create_app(
        Path(config_dir),
        runtime_file=Path(runtime_file),
        steelseries_mode="simulate" if simulate else None,
        start_background_sensors=start_background_sensors,
    )


@app.command("run")
def run(
    config_dir: str = typer.Option("config", help="Directory containing app/plugins/rules/scenes YAML."),
    runtime_file: str = typer.Option(".familiar/runtime.json", help="Persisted state and trace file."),
    simulate: bool = typer.Option(False, "--simulate", help="Use the explicit in-memory OLED substitute."),
) -> None:
    """Run the VRAM monitor until Ctrl+C."""

    async def operation() -> None:
        harness = await _create(config_dir, runtime_file, simulate)
        try:
            gpu = harness.plugins.sensors.get("gpu_vram")
            if gpu and await gpu.sample() is None:
                raise ConfigurationError(
                    "gpu_vram is enabled but NVIDIA telemetry is unavailable. "
                    "Update the NVIDIA driver, verify `nvidia-smi`, or disable gpu_vram."
                )
            oled = harness.plugins.surfaces.get("primary_surface")
            if oled:
                await oled.probe()
            mode = oled.transport.mode if oled else "console-only"
            await harness.plugins.start_background_sensors(harness)
            typer.echo(f"Keyboard Familiar started (OLED mode: {mode}; Ctrl+C to stop)")
            await run_app(harness)
        except BaseException:
            await harness.plugins.stop_all()
            raise

    try:
        _execute(operation())
    except KeyboardInterrupt:
        typer.echo("Keyboard Familiar stopped")


@app.command("trigger")
def trigger(
    event_type: str = typer.Argument(..., help="Dotted event type, for example test.ping."),
    source: str = typer.Option("manual", help="Event source recorded in state and trace."),
    message: str = typer.Option("System nominal", help="Text for test.ping display events."),
    config_dir: str = typer.Option("config", help="Configuration directory."),
    runtime_file: str = typer.Option(".familiar/runtime.json", help="Persisted state and trace file."),
    simulate: bool = typer.Option(False, "--simulate", help="Use the explicit in-memory OLED substitute."),
) -> None:
    """Publish one event and fail if any configured render target fails."""

    async def operation() -> None:
        harness = await _create(config_dir, runtime_file, simulate)
        try:
            sensor = harness.plugins.sensors.get("manual_trigger")
            if sensor is None:
                raise ConfigurationError("manual_trigger is disabled; enable it to use `familiar trigger`.")
            results = await sensor.trigger(event_type=event_type, source=source, payload={"message": message})
            if not results:
                raise ConfigurationError(
                    "event was recorded but produced no display directive. "
                    "Enable rules_basic and use a supported event such as test.ping."
                )
            failures = [result for result in results if not result.ok]
            if failures:
                details = "; ".join(f"{item.surface}: {item.detail}" for item in failures)
                raise SteelSeriesError(f"event was recorded, but rendering failed: {details}")
            typer.echo("Event published and rendered successfully.")
        finally:
            await harness.plugins.stop_all()

    _execute(operation())


@app.command("doctor")
def doctor(
    config_dir: str = typer.Option("config", help="Configuration directory."),
    runtime_file: str = typer.Option(".familiar/runtime.json", help="Persisted state and trace file."),
    simulate: bool = typer.Option(False, "--simulate", help="Validate with the in-memory OLED substitute."),
) -> None:
    """Check configuration, NVIDIA telemetry, and SteelSeries Engine connectivity."""

    async def operation() -> None:
        load_config_dir(Path(config_dir))
        typer.echo(f"[ok] configuration: {Path(config_dir).resolve()}")
        typer.echo(f"[info] operating system: {platform.system()} {platform.release()}")
        harness = await _create(config_dir, runtime_file, simulate)
        try:
            gpu = harness.plugins.sensors.get("gpu_vram")
            if gpu:
                metrics = await gpu.sample()
                if metrics is None:
                    typer.echo(
                        "[warn] NVIDIA telemetry unavailable: install a current NVIDIA driver and verify nvidia-smi.",
                        err=True,
                    )
                else:
                    typer.echo(
                        f"[ok] NVIDIA GPU {metrics['gpu_index']}: {metrics['percent_used']}% VRAM via {metrics['sample_source']}"
                    )
            else:
                typer.echo("[info] gpu_vram sensor is disabled")

            oled = harness.plugins.surfaces.get("primary_surface")
            if oled is None:
                typer.echo("[info] SteelSeries OLED surface is disabled")
            else:
                await oled.probe()
                typer.echo(f"[ok] SteelSeries OLED transport: {oled.transport.mode}")
            typer.echo("Doctor completed successfully.")
        finally:
            await harness.plugins.stop_all()

    _execute(operation())


async def _inspect(config_dir: str, runtime_file: str, action) -> None:
    harness = await _create(config_dir, runtime_file)
    try:
        action(harness)
    finally:
        await harness.plugins.stop_all()


@state_app.command("show")
def state_show(
    config_dir: str = typer.Option("config", help="Configuration directory."),
    runtime_file: str = typer.Option(".familiar/runtime.json", help="Persisted state and trace file."),
) -> None:
    """Print persisted state as JSON."""
    _execute(
        _inspect(
            config_dir,
            runtime_file,
            lambda harness: typer.echo(harness.get_state_snapshot().model_dump_json(indent=2)),
        )
    )


@trace_app.command("tail")
def trace_tail(
    lines: int = typer.Option(20, min=1, help="Number of recent trace entries."),
    config_dir: str = typer.Option("config", help="Configuration directory."),
    runtime_file: str = typer.Option(".familiar/runtime.json", help="Persisted state and trace file."),
) -> None:
    """Print recent persisted trace entries."""

    def show(harness) -> None:
        if not harness.trace:
            typer.echo("Trace is empty. Run `familiar trigger test.ping --simulate` first.")
            return
        for line in harness.trace[-lines:]:
            typer.echo(line)

    _execute(_inspect(config_dir, runtime_file, show))


@surfaces_app.command("list")
def surfaces_list(
    config_dir: str = typer.Option("config", help="Configuration directory."),
    runtime_file: str = typer.Option(".familiar/runtime.json", help="Persisted state and trace file."),
) -> None:
    """List enabled output surfaces."""
    _execute(
        _inspect(
            config_dir, runtime_file, lambda harness: typer.echo("\n".join(harness.plugins.surface_names()))
        )
    )


@plugins_app.command("list")
def plugins_list(
    config_dir: str = typer.Option("config", help="Configuration directory."),
    runtime_file: str = typer.Option(".familiar/runtime.json", help="Persisted state and trace file."),
) -> None:
    """List enabled sensors, brains, and surfaces."""
    _execute(
        _inspect(
            config_dir, runtime_file, lambda harness: typer.echo("\n".join(harness.plugins.plugin_names()))
        )
    )


@render_app.command("dry-run")
def render_dry_run(
    config_dir: str = typer.Option("config", help="Configuration directory."),
    runtime_file: str = typer.Option(".familiar/runtime.json", help="Persisted state and trace file."),
) -> None:
    """Render test.ping through the complete pipeline using the explicit OLED substitute."""

    async def operation() -> None:
        transport = RecordingSteelSeriesTransport()
        harness = await create_app(
            Path(config_dir),
            runtime_file=Path(runtime_file),
            steelseries_transport=transport,
            start_background_sensors=False,
        )
        try:
            sensor = harness.plugins.sensors.get("manual_trigger")
            if sensor is None:
                raise ConfigurationError("manual_trigger is disabled.")
            results = await sensor.trigger("test.ping", payload={"message": "OLED smoke test"})
            typer.echo(json.dumps([frame.__dict__ for frame in transport.frames], indent=2))
            if not transport.frames or any(not result.ok for result in results):
                raise SteelSeriesError("substitute render did not complete successfully.")
            typer.echo("Dry-run pipeline completed successfully (no hardware contacted).")
        finally:
            await harness.plugins.stop_all()

    _execute(operation())


if __name__ == "__main__":
    app()
