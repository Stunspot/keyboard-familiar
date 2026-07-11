from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


class FocusStateError(ValueError):
    """The persisted focus session cannot be interpreted safely."""


@dataclass(frozen=True)
class FocusSession:
    task: str
    started_at: str
    ends_at: str
    completion_announced: bool = False


@dataclass(frozen=True)
class FocusSnapshot:
    task: str
    remaining_minutes: int
    completed: bool
    completion_announced: bool


class FocusStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def start(self, task: str, minutes: int, now: datetime | None = None) -> FocusSession:
        if not 1 <= minutes <= 480:
            raise FocusStateError("Focus duration must be between 1 and 480 minutes.")
        clean_task = " ".join(task.split()).strip()
        if not clean_task:
            raise FocusStateError("Focus task cannot be empty.")
        if len(clean_task) > 80:
            raise FocusStateError("Focus task must be 80 characters or fewer.")
        started = now or datetime.now(timezone.utc)
        session = FocusSession(
            task=clean_task,
            started_at=started.isoformat(),
            ends_at=(started + timedelta(minutes=minutes)).isoformat(),
        )
        self._write(session)
        return session

    def stop(self) -> bool:
        if not self.path.exists():
            return False
        self.path.unlink()
        return True

    def load(self) -> FocusSession | None:
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            session = FocusSession(**data)
            self._parse_time(session.started_at)
            self._parse_time(session.ends_at)
        except (OSError, json.JSONDecodeError, TypeError, FocusStateError) as exc:
            raise FocusStateError(
                f"Cannot read focus state {self.path}: {exc}. Run `familiar focus stop` to reset it."
            ) from exc
        return session

    def snapshot(self, now: datetime | None = None) -> FocusSnapshot | None:
        session = self.load()
        if session is None:
            return None
        current = now or datetime.now(timezone.utc)
        remaining_seconds = (self._parse_time(session.ends_at) - current).total_seconds()
        return FocusSnapshot(
            task=session.task,
            remaining_minutes=max(0, math.ceil(remaining_seconds / 60)),
            completed=remaining_seconds <= 0,
            completion_announced=session.completion_announced,
        )

    def mark_completion_announced(self) -> None:
        session = self.load()
        if session is None or session.completion_announced:
            return
        self._write(
            FocusSession(
                task=session.task,
                started_at=session.started_at,
                ends_at=session.ends_at,
                completion_announced=True,
            )
        )

    def _write(self, session: FocusSession) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(json.dumps(asdict(session), indent=2), encoding="utf-8")
        temporary.replace(self.path)

    @staticmethod
    def _parse_time(value: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value)
        except (TypeError, ValueError) as exc:
            raise FocusStateError(f"invalid timestamp {value!r}") from exc
        if parsed.tzinfo is None:
            raise FocusStateError(f"timestamp has no timezone: {value!r}")
        return parsed


def focus_path_for(runtime_file: Path) -> Path:
    return runtime_file.parent / "focus.json"
