from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .models import SurfaceOwnership

SCENES = {"BOOT", "IDLE", "GLANCE", "ALERT", "INSPECT", "ART", "SLEEP"}


class SceneManager:
    def __init__(self, dwell_ms: int = 5000) -> None:
        self._owners: dict[str, SurfaceOwnership] = {}
        self._dwell_until: dict[str, datetime] = {}
        self._dwell_ms = dwell_ms

    def get_owner(self, surface: str) -> SurfaceOwnership | None:
        owner = self._owners.get(surface)
        if owner and owner.expires_at and owner.expires_at <= datetime.now(timezone.utc):
            self._owners.pop(surface, None)
            return None
        return owner

    def can_preempt(self, current_scene: str, next_scene: str) -> bool:
        if current_scene == next_scene:
            return True
        if next_scene == "ALERT" and current_scene in {"GLANCE", "ART", "IDLE"}:
            return True
        return False

    def acquire(self, surface: str, scene: str, owner: str, ttl_ms: int) -> SurfaceOwnership:
        now = datetime.now(timezone.utc)
        expires = now + timedelta(milliseconds=ttl_ms) if ttl_ms > 0 else None
        ownership = SurfaceOwnership(surface=surface, scene=scene, owner=owner, acquired_at=now, expires_at=expires)
        self._owners[surface] = ownership
        self._dwell_until[surface] = now + timedelta(milliseconds=self._dwell_ms)
        return ownership

    def in_dwell(self, surface: str) -> bool:
        return datetime.now(timezone.utc) < self._dwell_until.get(surface, datetime.min.replace(tzinfo=timezone.utc))
