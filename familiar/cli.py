from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from familiar.bootstrap import create_app, run_app

app = typer.Typer(help="Keyboard Familiar Harness CLI")


def _load(config_dir: str, runtime_file: str) -> "FamiliarApp":
    return asyncio.run(create_app(Path(config_dir), runtime_file=Path(runtime_file)))


@app.command("run")
def run(config_dir: str = "config", runtime_file: str = ".familiar/runtime.json") -> None:
    harness = _load(config_dir, runtime_file)
    typer.echo("familiar runtime started (Ctrl+C to stop)")
    try:
        asyncio.run(run_app(harness))
    except KeyboardInterrupt:
        typer.echo("familiar runtime stopped")


@app.command("trigger")
def trigger(
    event_type: str,
    source: str = "manual",
    message: str = "System nominal",
    config_dir: str = "config",
    runtime_file: str = ".familiar/runtime.json",
) -> None:
    harness = _load(config_dir, runtime_file)
    sensor = harness.plugins.sensors["manual_trigger"]
    asyncio.run(sensor.trigger(event_type=event_type, source=source, payload={"message": message}))
    typer.echo("event published and recorded")
def _load(config_dir: str) -> "FamiliarApp":
    return asyncio.run(create_app(Path(config_dir)))


@app.command("run")
def run(config_dir: str = "config") -> None:
    harness = _load(config_dir)
    asyncio.run(run_app(harness))
    typer.echo("familiar running (skeleton)")


@app.command("trigger")
def trigger(event_type: str, source: str = "manual", message: str = "System nominal", config_dir: str = "config") -> None:
    harness = _load(config_dir)
    sensor = harness.plugins.sensors["manual_trigger"]
    asyncio.run(sensor.trigger(event_type=event_type, source=source, payload={"message": message}))
    typer.echo("event published")


state_app = typer.Typer()
trace_app = typer.Typer()
surfaces_app = typer.Typer()
plugins_app = typer.Typer()
render_app = typer.Typer()
app.add_typer(state_app, name="state")
app.add_typer(trace_app, name="trace")
app.add_typer(surfaces_app, name="surfaces")
app.add_typer(plugins_app, name="plugins")
app.add_typer(render_app, name="render")


@state_app.command("show")
def state_show(config_dir: str = "config", runtime_file: str = ".familiar/runtime.json") -> None:
    harness = _load(config_dir, runtime_file)
def state_show(config_dir: str = "config") -> None:
    harness = _load(config_dir)
    typer.echo(harness.get_state_snapshot().model_dump_json(indent=2))


@trace_app.command("tail")
def trace_tail(lines: int = 20, config_dir: str = "config", runtime_file: str = ".familiar/runtime.json") -> None:
    harness = _load(config_dir, runtime_file)
    if not harness.trace:
        typer.echo("trace is empty. Run `familiar trigger test.ping` first.")
        return
def trace_tail(lines: int = 20, config_dir: str = "config") -> None:
    harness = _load(config_dir)
    for line in harness.trace[-lines:]:
        typer.echo(line)


@surfaces_app.command("list")
def surfaces_list(config_dir: str = "config", runtime_file: str = ".familiar/runtime.json") -> None:
    harness = _load(config_dir, runtime_file)
def surfaces_list(config_dir: str = "config") -> None:
    harness = _load(config_dir)
    for surface in harness.plugins.surface_names():
        typer.echo(surface)


@plugins_app.command("list")
def plugins_list(config_dir: str = "config", runtime_file: str = ".familiar/runtime.json") -> None:
    harness = _load(config_dir, runtime_file)
def plugins_list(config_dir: str = "config") -> None:
    harness = _load(config_dir)
    for plugin in harness.plugins.plugin_names():
        typer.echo(plugin)


@render_app.command("dry-run")
def render_dry_run(surface: str = "primary_surface", config_dir: str = "config", runtime_file: str = ".familiar/runtime.json") -> None:
    harness = _load(config_dir, runtime_file)
def render_dry_run(surface: str = "primary_surface", config_dir: str = "config") -> None:
    harness = _load(config_dir)
    target = harness.plugins.surfaces.get(surface)
    typer.echo(f"surface={surface} capabilities={sorted(target.capabilities.supports) if target else 'missing'}")


if __name__ == "__main__":
    app()
