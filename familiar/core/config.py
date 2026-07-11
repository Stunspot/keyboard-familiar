from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class ConfigurationError(ValueError):
    """Configuration cannot be loaded or safely interpreted."""


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigurationError(f"Required configuration file is missing: {path}")
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"Cannot load YAML configuration {path}: {exc}") from exc
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigurationError(f"Configuration file must contain a YAML mapping: {path}")
    return value


def load_config_dir(config_dir: Path) -> dict[str, Any]:
    if not config_dir.is_dir():
        raise ConfigurationError(
            f"Configuration directory not found: {config_dir}. Run from the repository root or pass --config-dir."
        )
    return {
        "app": load_yaml(config_dir / "app.yaml"),
        "plugins": load_yaml(config_dir / "plugins.yaml"),
        "scenes": load_yaml(config_dir / "scenes.yaml"),
        "rules": load_yaml(config_dir / "rules.yaml"),
    }
