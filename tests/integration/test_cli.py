import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from typer.testing import CliRunner

from familiar.cli import app
from familiar.plugins.sensors.gpu_vram import GpuVramSensor

runner = CliRunner()


def test_trigger_simulate_runs_complete_pipeline(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "trigger",
            "test.ping",
            "--message",
            "hello screen",
            "--simulate",
            "--runtime-file",
            str(tmp_path / "runtime.json"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "rendered successfully" in result.output


def test_render_dry_run_is_explicit_about_hardware_boundary(tmp_path: Path) -> None:
    result = runner.invoke(app, ["render", "dry-run", "--runtime-file", str(tmp_path / "runtime.json")])
    assert result.exit_code == 0, result.output
    assert "no hardware contacted" in result.output
    assert "Quiet status" in result.output
    assert "Needs attention" in result.output
    assert "alert lighting data verified" in result.output


def test_missing_configuration_returns_nonzero(tmp_path: Path) -> None:
    result = runner.invoke(app, ["doctor", "--config-dir", str(tmp_path / "missing"), "--simulate"])
    assert result.exit_code == 1
    assert "Configuration directory not found" in result.output


def test_unavailable_gamesense_is_not_reported_as_success(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["trigger", "test.ping", "--runtime-file", str(tmp_path / "runtime.json")],
    )
    assert result.exit_code == 1
    assert "rendering failed" in result.output
    assert "SteelSeries GG" in result.output


def test_malformed_event_type_returns_nonzero(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["trigger", "not-dotted", "--simulate", "--runtime-file", str(tmp_path / "runtime.json")],
    )
    assert result.exit_code == 1
    assert "Invalid event type" in result.output


def test_malformed_numeric_configuration_returns_nonzero(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    shutil.copytree("config", config_dir)
    plugins = config_dir / "plugins.yaml"
    plugins.write_text(
        plugins.read_text(encoding="utf-8").replace("every_seconds: 3", "every_seconds: never"),
        encoding="utf-8",
    )
    result = runner.invoke(app, ["doctor", "--config-dir", str(config_dir), "--simulate"])
    assert result.exit_code == 1
    assert "gpu_vram.every_seconds must be an integer" in result.output


def test_unknown_deck_source_returns_nonzero_with_choices(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    shutil.copytree("config", config_dir)
    deck = config_dir / "deck.yaml"
    deck.write_text(
        deck.read_text(encoding="utf-8").replace("source: system", "source: weather"),
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        ["preview", "--config-dir", str(config_dir), "--runtime-file", str(tmp_path / "runtime.json")],
    )
    assert result.exit_code == 1
    assert "clock, focus, system" in result.output


def test_preview_teaches_the_default_deck(tmp_path: Path) -> None:
    result = runner.invoke(app, ["preview", "--runtime-file", str(tmp_path / "runtime.json")])
    assert result.exit_code == 0, result.output
    assert "clock" in result.output
    assert "SYSTEM PULSE" in result.output
    assert "regular cards do not alter lighting" in result.output


def test_focus_lifecycle_joins_preview_and_status(tmp_path: Path) -> None:
    runtime = str(tmp_path / "runtime.json")
    started = runner.invoke(
        app,
        ["focus", "start", "Write release notes", "--minutes", "12", "--simulate", "--runtime-file", runtime],
    )
    assert started.exit_code == 0, started.output
    assert "Focus started for 12 minutes" in started.output

    status = runner.invoke(app, ["focus", "status", "--runtime-file", runtime])
    assert status.exit_code == 0
    assert "Write release notes" in status.output

    preview = runner.invoke(app, ["preview", "--runtime-file", runtime])
    assert "FOCUS ·" in preview.output
    assert "Write release notes" in preview.output

    stopped = runner.invoke(app, ["focus", "stop", "--simulate", "--runtime-file", runtime])
    assert stopped.exit_code == 0, stopped.output
    assert "ended" in stopped.output


def test_lighting_only_profile_requires_alert_for_visible_output(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    shutil.copytree("config", config_dir)
    plugins = config_dir / "plugins.yaml"
    plugins.write_text(
        plugins.read_text(encoding="utf-8").replace(
            "capabilities: [screen, function_key_lighting]",
            "capabilities: [function_key_lighting]",
        ),
        encoding="utf-8",
    )
    runtime = str(tmp_path / "runtime.json")
    quiet = runner.invoke(
        app,
        ["show", "quiet", "--simulate", "--config-dir", str(config_dir), "--runtime-file", runtime],
    )
    assert quiet.exit_code == 1
    assert "Use --alert for lighting-only hardware" in quiet.output

    alert = runner.invoke(
        app,
        [
            "show",
            "attention",
            "--alert",
            "--simulate",
            "--config-dir",
            str(config_dir),
            "--runtime-file",
            runtime,
        ],
    )
    assert alert.exit_code == 0, alert.output
    assert "Alert sent" in alert.output

    focus = runner.invoke(
        app,
        [
            "focus",
            "start",
            "Lighting-only focus",
            "--minutes",
            "5",
            "--simulate",
            "--config-dir",
            str(config_dir),
            "--runtime-file",
            runtime,
        ],
    )
    assert focus.exit_code == 0, focus.output
    assert "will signal completion" in focus.output
    assert "no countdown card was displayed" in focus.output


def test_run_degrades_without_nvidia_but_keeps_deck(monkeypatch, tmp_path: Path) -> None:
    async def no_gpu(self):
        return None

    async def stop_after_start(harness):
        await harness.plugins.stop_all()

    monkeypatch.setattr(GpuVramSensor, "sample", no_gpu)
    monkeypatch.setattr("familiar.cli.run_app", stop_after_start)
    result = runner.invoke(
        app,
        ["run", "--simulate", "--runtime-file", str(tmp_path / "runtime.json")],
    )
    assert result.exit_code == 0, result.output
    assert "Glance deck: clock, system, focus" in result.output
    assert "VRAM cards disabled" in result.output


def test_status_calls_out_stale_runtime(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime.json"
    shown = runner.invoke(
        app,
        ["show", "hello", "--simulate", "--runtime-file", str(runtime)],
    )
    assert shown.exit_code == 0
    old = datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp()
    runtime.touch()
    os.utime(runtime, (old, old))
    result = runner.invoke(app, ["status", "--runtime-file", str(runtime)])
    assert result.exit_code == 0
    assert "Runtime: stale" in result.output


def test_doctor_isolates_corrupt_focus_state_and_gives_recovery(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime.json"
    focus = tmp_path / "focus.json"
    focus.write_text("broken", encoding="utf-8")
    result = runner.invoke(
        app,
        ["doctor", "--simulate", "--runtime-file", str(runtime)],
    )
    assert result.exit_code == 0, result.output
    assert "focus state unavailable" in result.output
    assert "familiar focus stop" in result.output
    assert "Doctor completed successfully" in result.output


def test_setup_makes_config_and_state_work_outside_checkout(monkeypatch, tmp_path: Path) -> None:
    source = Path("config").resolve()
    appdata = tmp_path / "appdata"
    local_appdata = tmp_path / "localappdata"
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setenv("LOCALAPPDATA", str(local_appdata))

    configured = runner.invoke(app, ["setup", "--from-dir", str(source)])
    assert configured.exit_code == 0, configured.output
    assert (appdata / "Keyboard Familiar" / "deck.yaml").is_file()

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    preview = runner.invoke(app, ["preview"])
    assert preview.exit_code == 0, preview.output
    assert "SYSTEM PULSE" in preview.output

    shown = runner.invoke(app, ["show", "portable", "--simulate"])
    assert shown.exit_code == 0, shown.output
    assert (local_appdata / "Keyboard Familiar" / "runtime.json").is_file()

    repeated = runner.invoke(app, ["setup", "--from-dir", str(source)])
    assert repeated.exit_code == 1
    assert "already exists" in repeated.output
