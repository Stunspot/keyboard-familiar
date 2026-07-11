from pathlib import Path

import pytest

from familiar.core.config import ConfigurationError, load_config_dir, load_yaml


def test_missing_config_directory_is_actionable(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="Run from the repository root"):
        load_config_dir(tmp_path / "missing")


def test_malformed_yaml_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("plugins: [", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="Cannot load YAML"):
        load_yaml(path)
