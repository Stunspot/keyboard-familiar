from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from .models import Directive, DirectiveProposal, StateSnapshot
from .scenes import SceneManager


class Arbitrator:
    def __init__(self, scene_manager: SceneManager, dedupe_window_ms: int = 30_000) -> None:
        self.scene_manager = scene_manager
        self.dedupe_window = timedelta(milliseconds=dedupe_window_ms)
        self._cooldowns: dict[str, datetime] = {}

    def _normalize_targets(self, target: str, known_surfaces: list[str]) -> list[str]:
        if target == "all":
            return known_surfaces
        if target == "primary_surface":
            return ["primary_surface"] if "primary_surface" in known_surfaces else known_surfaces[:1]
        return [target]

    async def arbitrate(
        self,
        proposals: list[DirectiveProposal],
        snapshot: StateSnapshot,
        known_surfaces: list[str],
    ) -> tuple[list[Directive], list[str]]:
        accepted: list[Directive] = []
        suppressed: list[str] = []
        grouped: dict[str, list[DirectiveProposal]] = defaultdict(list)

        now = datetime.now(timezone.utc)
        for proposal in proposals:
            for surface in self._normalize_targets(proposal.target, known_surfaces):
                grouped[surface].append(proposal)

        for surface, pset in grouped.items():
            pset.sort(key=lambda p: p.importance, reverse=True)
            winner = pset[0]
            if winner.cooldown_key:
                expiry = self._cooldowns.get(winner.cooldown_key)
                if expiry and expiry > now:
                    suppressed.append(f"{winner.id}:cooldown")
                    continue

            scene = winner.requested_scene or snapshot.active_scene
            owner = self.scene_manager.get_owner(surface)
            if owner and self.scene_manager.in_dwell(surface):
                if winner.importance <= 0.8 and not self.scene_manager.can_preempt(owner.scene, scene):
                    suppressed.append(f"{winner.id}:dwell")
                    continue

            directive = Directive.from_proposal(winner, surface, scene)
            accepted.append(directive)
            self.scene_manager.acquire(surface=surface, scene=scene, owner=str(winner.id), ttl_ms=winner.ttl_ms)
            if winner.cooldown_key:
                self._cooldowns[winner.cooldown_key] = now + self.dedupe_window

        return accepted, suppressed
