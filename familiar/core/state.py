from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from .models import StatePatch, StateSnapshot


def _deep_merge(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(left)
    for key, value in right.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = deepcopy(value)
    return out


class InMemoryStateStore:
    def __init__(self) -> None:
        self._snapshot = StateSnapshot()
        self._patch_log: list[StatePatch] = []

    def get_snapshot(self) -> StateSnapshot:
        return self._snapshot.model_copy(deep=True)

    def get_patch_log(self) -> list[StatePatch]:
        return [p.model_copy(deep=True) for p in self._patch_log]

    async def apply_patch(self, patch: StatePatch) -> None:
        domain_data = self._snapshot.domains.setdefault(patch.domain, {})
        parts = [p for p in patch.path.split(".") if p]
        if not parts:
            raise ValueError("patch.path cannot be empty")

        node: Any = domain_data
        for key in parts[:-1]:
            node = node.setdefault(key, {})

        leaf = parts[-1]
        if patch.merge_strategy == "replace":
            node[leaf] = patch.value
        elif patch.merge_strategy == "deep_merge":
            current = node.get(leaf, {})
            if not isinstance(current, dict) or not isinstance(patch.value, dict):
                raise ValueError("deep_merge requires dict current and value")
            node[leaf] = _deep_merge(current, patch.value)
        elif patch.merge_strategy == "append":
            current = node.setdefault(leaf, [])
            if not isinstance(current, list):
                raise ValueError("append requires list at destination")
            current.append(patch.value)
        elif patch.merge_strategy == "remove":
            node.pop(leaf, None)
        else:
            raise ValueError(f"Unsupported merge strategy: {patch.merge_strategy}")

        self._snapshot.updated_at = datetime.now(timezone.utc)
        self._patch_log.append(patch)
