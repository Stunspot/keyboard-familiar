import shutil
from pathlib import Path

from typer.testing import CliRunner

from familiar.cli import app

runner = CliRunner()


def test_trigger_simulate_runs_complete_pipeline(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "trigger",
            "test.ping",
            "--message",
            "hello OLED",
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
    assert "OLED smoke test" in result.output


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
