from __future__ import annotations

from pathlib import Path
from typing import Any


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    """Very small fallback parser for key/value and one-level maps used in test config."""
    data: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(0, data)]
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.strip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key, val = key.strip(), val.strip()
        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        current = stack[-1][1]
        if not val:
            child: dict[str, Any] = {}
            current[key] = child
            stack.append((indent, child))
        else:
            current[key] = val.strip('"')
    return data


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        return yaml.safe_load(text) or {}
    except Exception:
        return _parse_simple_yaml(text)


def load_config_dir(config_dir: Path) -> dict[str, Any]:
    return {
        "app": load_yaml(config_dir / "app.yaml"),
        "plugins": load_yaml(config_dir / "plugins.yaml"),
        "scenes": load_yaml(config_dir / "scenes.yaml"),
        "rules": load_yaml(config_dir / "rules.yaml"),
    }
