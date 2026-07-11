from __future__ import annotations

import asyncio
import json
import os
import platform
import shutil
from collections.abc import Coroutine
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import typer

from familiar.adapters.steelseries.transport import RecordingSteelSeriesTransport, SteelSeriesError
from familiar.bootstrap import create_app, run_app
from familiar.core.config import ConfigurationError
from familiar.core.focus import FocusStateError

app = typer.Typer(
    help="A quiet glance deck for SteelSeries screens and function-key alerts.",
    no_args_is_help=True,
)
focus_app = typer.Typer(help="Start, stop, and inspect a keyboard-visible focus session.")
state_app = typer.Typer(help="Inspect persisted runtime state.")
trace_app = typer.Typer(help="Inspect diagnostic runtime traces.")
surfaces_app = typer.Typer(help="Inspect configured output surfaces.")
plugins_app = typer.Typer(help="Inspect configured sources and surfaces.")
render_app = typer.Typer(help="Exercise rendering without physical hardware.")
app.add_typer(focus_app, name="focus")
app.add_typer(state_app, name="state")
app.add_typer(trace_app, name="trace")
app.add_typer(surfaces_app, name="surfaces")
app.add_typer(plugins_app, name="plugins")
app.add_typer(render_app, name="render")

DEFAULT_CONFIG_DIR = "config"
DEFAULT_RUNTIME_FILE = ".familiar/runtime.json"


def _user_config_dir() -> Path:
    if appdata := os.environ.get("APPDATA"):
        return Path(appdata) / "Keyboard Familiar"
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "keyboard-familiar"


def _user_runtime_file() -> Path:
    if local_appdata := os.environ.get("LOCALAPPDATA"):
        return Path(local_appdata) / "Keyboard Familiar" / "runtime.json"
    base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))
    return base / "keyboard-familiar" / "runtime.json"


def _resolve_config_dir(value: str) -> Path:
    requested = Path(value)
    if value != DEFAULT_CONFIG_DIR:
        return requested
    if configured := os.environ.get("FAMILIAR_CONFIG_DIR"):
        return Path(configured)
    if requested.is_dir():
        return requested
    user_config = _user_config_dir()
    return user_config if user_config.is_dir() else requested


def _resolve_runtime_file(value: str, config_dir: Path) -> Path:
    if value != DEFAULT_RUNTIME_FILE:
        return Path(value)
    if config_dir == _user_config_dir():
        return _user_runtime_file()
    return Path(value)


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
    resolved_config = _resolve_config_dir(config_dir)
    return await create_app(
        resolved_config,
        runtime_file=_resolve_runtime_file(runtime_file, resolved_config),
        steelseries_mode="simulate" if simulate else None,
        start_background_sensors=start_background_sensors,
    )


@app.command("setup")
def setup(
    from_dir: str = typer.Option("config", help="Configuration directory to copy."),
    destination: str | None = typer.Option(None, help="Destination; defaults to the user config folder."),
    force: bool = typer.Option(False, "--force", help="Replace an existing user configuration."),
) -> None:
    """Install editable user configuration so commands work from any directory."""
    source = Path(from_dir)
    target = Path(destination) if destination else _user_config_dir()
    if not source.is_dir():
        typer.echo(f"Error: Configuration directory not found: {source}", err=True)
        raise typer.Exit(code=1)
    if target.exists():
        if not force:
            typer.echo(
                f"Error: Configuration already exists at {target}. Edit it there or rerun with --force.",
                err=True,
            )
            raise typer.Exit(code=1)
        shutil.rmtree(target)
    shutil.copytree(source, target)
    typer.echo(f"User configuration installed at {target}")
    typer.echo(f"Runtime state will live at {_user_runtime_file()}")
    typer.echo("Run `familiar preview`, then `familiar doctor`.")


async def _publish(harness, event_type: str, payload: dict, source: str = "manual") -> None:
    sensor = harness.plugins.sensors.get("manual_trigger")
    if sensor is None:
        raise ConfigurationError("manual_trigger is disabled; enable it to publish messages.")
    results = await sensor.trigger(event_type=event_type, source=source, payload=payload)
    if not results:
        raise ConfigurationError(
            "The event was recorded but produced no device directive. Confirm rules_basic is enabled."
        )
    failures = [result for result in results if not result.ok]
    if failures:
        details = "; ".join(f"{item.surface}: {item.detail}" for item in failures)
        raise SteelSeriesError(f"The event was recorded, but device rendering failed: {details}")


@app.command("run")
def run(
    config_dir: str = typer.Option("config", help="Directory containing Keyboard Familiar YAML."),
    runtime_file: str = typer.Option(".familiar/runtime.json", help="Persisted state and trace file."),
    simulate: bool = typer.Option(False, "--simulate", help="Use the explicit device substitute."),
) -> None:
    """Run the glance deck and alert sources until Ctrl+C."""

    async def operation() -> None:
        harness = await _create(config_dir, runtime_file, simulate)
        try:
            degraded: list[str] = []
            harness.glance_deck.preview_cards()
            degraded.extend(
                f"{source} card unavailable: {error}"
                for source, error in harness.glance_deck.provider_errors.items()
            )
            gpu = harness.plugins.sensors.get("gpu_vram")
            if gpu and await gpu.sample() is None:
                harness.plugins.sensors.pop("gpu_vram")
                degraded.append("NVIDIA telemetry unavailable; VRAM cards disabled")

            surface = harness.plugins.surfaces.get("primary_surface")
            if surface:
                await surface.probe()
            await harness.plugins.start_background_sensors(harness)

            mode = surface.transport.mode if surface else "console-only"
            capabilities = ", ".join(sorted(surface.transport.capabilities)) if surface else "console"
            sources = ", ".join(harness.glance_deck.sources()) if harness.glance_deck else "events only"
            typer.echo(f"Keyboard Familiar is running ({mode}; {capabilities}).")
            if surface and "screen" not in surface.transport.capabilities:
                typer.echo("Lighting-only alert watch: focus completion, VRAM, and manual alerts.")
            else:
                typer.echo(f"Glance deck: {sources}. Ctrl+C stops it.")
            for detail in degraded:
                typer.echo(f"Degraded: {detail}.", err=True)
            await run_app(harness)
        except asyncio.CancelledError:
            typer.echo("Keyboard Familiar stopped.")
            return
        except BaseException:
            await harness.plugins.stop_all()
            raise

    try:
        _execute(operation())
    except KeyboardInterrupt:
        typer.echo("Keyboard Familiar stopped.")


@app.command("preview")
def preview(
    config_dir: str = typer.Option("config", help="Configuration directory."),
    runtime_file: str = typer.Option(
        ".familiar/runtime.json", help="Runtime file used to locate focus state."
    ),
) -> None:
    """Preview the configured deck in rotation order without contacting hardware."""

    async def operation() -> None:
        harness = await _create(config_dir, runtime_file, simulate=True)
        try:
            cards = harness.glance_deck.preview_cards() if harness.glance_deck else []
            if not cards:
                typer.echo("The deck currently has no visible cards.")
                return
            typer.echo(
                f"Glance deck · {harness.glance_deck.settings.interval_seconds}s rotation · no hardware contacted"
            )
            for index, card in enumerate(cards, start=1):
                marker = "ALERT" if card.alert else card.source
                typer.echo(f"{index}. [{marker}] {card.title[:20]}")
                typer.echo(f"   {card.body[:40]}")
            for source, error in harness.glance_deck.provider_errors.items():
                typer.echo(f"Unavailable [{source}]: {error}", err=True)
            surface = harness.plugins.surfaces.get("primary_surface")
            if surface and "screen" not in surface.transport.capabilities:
                typer.echo(
                    "Configured lighting-only: quiet cards are previewed here; focus completion and alerts signal."
                )
            if surface and "function_key_lighting" in surface.transport.capabilities:
                typer.echo(
                    f"Alerts also signal on function keys with RGB{surface.alert_color}; regular cards do not alter lighting."
                )
        finally:
            await harness.plugins.stop_all()

    _execute(operation())


@app.command("show")
def show_message(
    message: str = typer.Argument(..., help="Message body to place on the keyboard."),
    title: str = typer.Option("Keyboard Familiar", help="Short card title."),
    alert: bool = typer.Option(False, "--alert", help="Preempt the deck and signal function-key lighting."),
    config_dir: str = typer.Option("config", help="Configuration directory."),
    runtime_file: str = typer.Option(".familiar/runtime.json", help="Persisted state and trace file."),
    simulate: bool = typer.Option(False, "--simulate", help="Use the explicit device substitute."),
) -> None:
    """Show a script-friendly one-off card."""

    async def operation() -> None:
        harness = await _create(config_dir, runtime_file, simulate)
        try:
            await _publish(
                harness,
                "user.message",
                {"source": "user", "title": title, "body": message, "alert": alert},
                source="show",
            )
            typer.echo("Alert sent." if alert else "Card shown.")
        finally:
            await harness.plugins.stop_all()

    _execute(operation())


@app.command("trigger", hidden=True)
def trigger(
    event_type: str = typer.Argument(..., help="Dotted event type."),
    source: str = typer.Option("manual", help="Event source recorded in state and trace."),
    message: str = typer.Option("System nominal", help="Message for compatible legacy events."),
    config_dir: str = typer.Option("config", help="Configuration directory."),
    runtime_file: str = typer.Option(".familiar/runtime.json", help="Persisted state and trace file."),
    simulate: bool = typer.Option(False, "--simulate", help="Use the explicit device substitute."),
) -> None:
    """Publish a low-level event (compatibility and development command)."""

    async def operation() -> None:
        harness = await _create(config_dir, runtime_file, simulate)
        try:
            await _publish(harness, event_type, {"message": message}, source)
            typer.echo("Event published and rendered successfully.")
        finally:
            await harness.plugins.stop_all()

    _execute(operation())


@focus_app.command("start")
def focus_start(
    task: str = typer.Argument(..., help="What deserves your attention."),
    minutes: int | None = typer.Option(None, min=1, max=480, help="Session length; defaults from deck.yaml."),
    config_dir: str = typer.Option("config", help="Configuration directory."),
    runtime_file: str = typer.Option(
        ".familiar/runtime.json", help="Runtime file used to locate focus state."
    ),
    simulate: bool = typer.Option(False, "--simulate", help="Use the explicit device substitute."),
) -> None:
    """Start or replace a focus session and show it immediately."""

    async def operation() -> None:
        harness = await _create(config_dir, runtime_file, simulate)
        try:
            duration = minutes or harness.glance_deck.settings.default_focus_minutes
            harness.focus_store.start(task, duration)
            surface = harness.plugins.surfaces.get("primary_surface")
            if surface and "screen" not in surface.transport.capabilities:
                typer.echo(f"Focus started for {duration} minutes: {task}")
                typer.echo("Lighting-only mode will signal completion; no countdown card was displayed.")
                return
            try:
                await _publish(
                    harness,
                    "focus.changed",
                    {
                        "source": "focus",
                        "title": f"FOCUS · {duration}m",
                        "body": task,
                        "importance": 0.60,
                    },
                    source="focus",
                )
            except SteelSeriesError as exc:
                raise SteelSeriesError(
                    f"Focus session was saved, but the initial device card failed. {exc}"
                ) from exc
            typer.echo(f"Focus started for {duration} minutes: {task}")
            typer.echo("A running Keyboard Familiar process will keep the countdown in the deck.")
        finally:
            await harness.plugins.stop_all()

    _execute(operation())


@focus_app.command("stop")
def focus_stop(
    config_dir: str = typer.Option("config", help="Configuration directory."),
    runtime_file: str = typer.Option(
        ".familiar/runtime.json", help="Runtime file used to locate focus state."
    ),
    simulate: bool = typer.Option(False, "--simulate", help="Use the explicit device substitute."),
) -> None:
    """End the current focus session."""

    async def operation() -> None:
        harness = await _create(config_dir, runtime_file, simulate)
        try:
            if not harness.focus_store.stop():
                typer.echo("No focus session is active.")
                return
            surface = harness.plugins.surfaces.get("primary_surface")
            if surface and "screen" not in surface.transport.capabilities:
                typer.echo("Focus session ended.")
                return
            await _publish(
                harness,
                "focus.changed",
                {"source": "focus", "title": "FOCUS ENDED", "body": "Back to the deck."},
                source="focus",
            )
            typer.echo("Focus session ended.")
        finally:
            await harness.plugins.stop_all()

    _execute(operation())


@focus_app.command("status")
def focus_status(
    config_dir: str = typer.Option("config", help="Configuration directory."),
    runtime_file: str = typer.Option(
        ".familiar/runtime.json", help="Runtime file used to locate focus state."
    ),
) -> None:
    """Show the current focus session without contacting hardware."""

    async def operation() -> None:
        harness = await _create(config_dir, runtime_file, simulate=True)
        try:
            snapshot = harness.focus_store.snapshot()
            if snapshot is None:
                typer.echo("No focus session is active.")
            elif snapshot.completed:
                typer.echo(f"Focus complete: {snapshot.task}")
            else:
                typer.echo(f"Focus · {snapshot.remaining_minutes}m remaining · {snapshot.task}")
        finally:
            await harness.plugins.stop_all()

    _execute(operation())


@app.command("status")
def status(
    config_dir: str = typer.Option("config", help="Configuration directory."),
    runtime_file: str = typer.Option(".familiar/runtime.json", help="Persisted state and trace file."),
) -> None:
    """Summarize what the keyboard should be doing now."""

    async def operation() -> None:
        harness = await _create(config_dir, runtime_file, simulate=True)
        try:
            typer.echo("Keyboard Familiar")
            typer.echo(f"Deck: {', '.join(harness.glance_deck.sources())}")
            try:
                focus = harness.focus_store.snapshot()
            except FocusStateError as exc:
                typer.echo(f"[warn] focus state unavailable: {exc}", err=True)
                focus = None
            if focus is None:
                typer.echo("Focus: inactive")
            elif focus.completed:
                typer.echo(f"Focus: complete · {focus.task}")
            else:
                typer.echo(f"Focus: {focus.remaining_minutes}m · {focus.task}")
            current = harness.get_state_snapshot().domains.get("deck", {}).get("current")
            if current:
                typer.echo(f"Last card: {current.get('title')} · {current.get('body')}")
            path = harness.runtime_file or Path(runtime_file)
            if path.exists():
                age = datetime.now(timezone.utc).timestamp() - path.stat().st_mtime
                if age > 86_400:
                    typer.echo(f"Runtime: stale ({round(age / 86_400)} days since last update)")
                else:
                    typer.echo(f"Runtime: updated {max(0, round(age))}s ago")
            else:
                typer.echo("Runtime: not started yet")
        finally:
            await harness.plugins.stop_all()

    _execute(operation())


@app.command("doctor")
def doctor(
    config_dir: str = typer.Option("config", help="Configuration directory."),
    runtime_file: str = typer.Option(".familiar/runtime.json", help="Persisted state and trace file."),
    simulate: bool = typer.Option(False, "--simulate", help="Validate with the device substitute."),
) -> None:
    """Check the deck, information sources, state, and SteelSeries boundary."""

    async def operation() -> None:
        typer.echo(f"[ok] configuration: {_resolve_config_dir(config_dir).resolve()}")
        typer.echo(f"[info] operating system: {platform.system()} {platform.release()}")
        harness = await _create(config_dir, runtime_file, simulate)
        try:
            cards = harness.glance_deck.preview_cards()
            surface = harness.plugins.surfaces.get("primary_surface")
            if surface and "screen" not in surface.transport.capabilities:
                typer.echo(
                    f"[ok] alert watch: focus, VRAM, and manual alerts; "
                    f"{len(cards)} quiet cards available only in preview (screen not configured)"
                )
            else:
                typer.echo(
                    f"[ok] glance deck: {', '.join(harness.glance_deck.sources())} "
                    f"({len(cards)} visible now, {harness.glance_deck.settings.interval_seconds}s rotation)"
                )
            for source, error in harness.glance_deck.provider_errors.items():
                typer.echo(f"[warn] {source} card unavailable: {error}", err=True)
            gpu = harness.plugins.sensors.get("gpu_vram")
            if gpu:
                metrics = await gpu.sample()
                if metrics is None:
                    typer.echo(
                        "[warn] NVIDIA telemetry unavailable; the rest of the deck remains usable.", err=True
                    )
                else:
                    typer.echo(
                        f"[ok] NVIDIA GPU {metrics['gpu_index']}: {metrics['percent_used']}% VRAM "
                        f"via {metrics['sample_source']}"
                    )
            else:
                typer.echo("[info] gpu_vram source is disabled")

            try:
                focus = harness.focus_store.snapshot()
            except FocusStateError as exc:
                typer.echo(f"[warn] focus state unavailable: {exc}", err=True)
                focus = None
            if focus and not focus.completed:
                typer.echo(f"[ok] focus state: {focus.remaining_minutes}m · {focus.task}")
            elif focus and focus.completed:
                typer.echo(f"[info] focus completion waiting: {focus.task}")
            else:
                typer.echo("[ok] focus state: ready")

            if surface is None:
                typer.echo("[info] SteelSeries surface is disabled; console mirror only")
            else:
                await surface.probe()
                typer.echo(
                    f"[ok] SteelSeries transport: {surface.transport.mode}; configured capabilities: "
                    f"{', '.join(sorted(surface.transport.capabilities))}"
                )
                if surface.transport.mode == "gamesense":
                    typer.echo(
                        "[info] GG accepted the handlers. GameSense does not enumerate matching physical devices; "
                        'use `familiar show "Hardware OK"` and observe the keyboard.'
                    )
            typer.echo("Doctor completed successfully.")
        finally:
            await harness.plugins.stop_all()

    _execute(operation())


async def _inspect(config_dir: str, runtime_file: str, action) -> None:
    harness = await _create(config_dir, runtime_file, simulate=True)
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
            typer.echo('Trace is empty. Run `familiar show "Hello" --simulate` first.')
            return
        for line in harness.trace[-lines:]:
            typer.echo(line)

    _execute(_inspect(config_dir, runtime_file, show))


@surfaces_app.command("list")
def surfaces_list(
    config_dir: str = typer.Option("config", help="Configuration directory."),
    runtime_file: str = typer.Option(".familiar/runtime.json", help="Persisted state and trace file."),
) -> None:
    """List enabled surfaces and configured capabilities."""

    def show(harness) -> None:
        for name, surface in harness.plugins.surfaces.items():
            capabilities = getattr(getattr(surface, "transport", None), "capabilities", None)
            suffix = f" ({', '.join(sorted(capabilities))})" if capabilities else ""
            typer.echo(f"{name}{suffix}")

    _execute(_inspect(config_dir, runtime_file, show))


@plugins_app.command("list")
def plugins_list(
    config_dir: str = typer.Option("config", help="Configuration directory."),
    runtime_file: str = typer.Option(".familiar/runtime.json", help="Persisted state and trace file."),
) -> None:
    """List enabled sources, policy, and surfaces."""
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
    """Render a glance and alert through the complete pipeline without hardware."""

    async def operation() -> None:
        transport = RecordingSteelSeriesTransport()
        harness = await create_app(
            _resolve_config_dir(config_dir),
            runtime_file=_resolve_runtime_file(runtime_file, _resolve_config_dir(config_dir)),
            steelseries_transport=transport,
            start_background_sensors=False,
        )
        try:
            await _publish(
                harness,
                "user.message",
                {"source": "dry-run", "title": "GLANCE", "body": "Quiet status"},
            )
            harness.scene_manager.clear()
            await _publish(
                harness,
                "user.message",
                {"source": "dry-run", "title": "ALERT", "body": "Needs attention", "alert": True},
            )
            typer.echo(json.dumps([asdict(frame) for frame in transport.frames], indent=2))
            if len(transport.frames) != 2:
                raise SteelSeriesError("Substitute render did not produce both expected device frames.")
            typer.echo(
                "Dry-run completed: screen frames and alert lighting data verified; no hardware contacted."
            )
        finally:
            await harness.plugins.stop_all()

    _execute(operation())


if __name__ == "__main__":
    app()
