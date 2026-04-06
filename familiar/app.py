from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from dataclasses import dataclass, field

from familiar.core.arbitration import Arbitrator
from familiar.core.bus import InMemoryEventBus
from familiar.core.models import Directive, Event, RenderResult, StatePatch, StateSnapshot
from familiar.core.routing import Router
from familiar.core.scenes import SceneManager
from familiar.core.state import InMemoryStateStore
from familiar.plugins.manager import PluginManager


@dataclass
class FamiliarApp:
    bus: InMemoryEventBus
    state: InMemoryStateStore
    plugins: PluginManager
    scene_manager: SceneManager
    arbitrator: Arbitrator
    router: Router
    trace: list[str] = field(default_factory=list)
    runtime_file: Path | None = None

    def load_runtime(self) -> None:
        if not self.runtime_file or not self.runtime_file.exists():
            return
        data = json.loads(self.runtime_file.read_text(encoding="utf-8"))
        self.trace = list(data.get("trace", []))
        domains = data.get("state", {}).get("domains", {})
        self.state._snapshot.domains = domains  # internal restore for CLI continuity

    def save_runtime(self) -> None:
        if not self.runtime_file:
            return
        self.runtime_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "trace": self.trace[-500:],
            "state": asdict(self.state.get_snapshot()),
        }
        self.runtime_file.write_text(json.dumps(payload, default=str, indent=2), encoding="utf-8")

    async def publish_event(self, event: Event) -> list[RenderResult]:
        self.trace.append(f"event.received type={event.type} source={event.source}")
        await self.bus.publish(event)

        results = []
        for brain_name, brain in self.plugins.brains.items():
            brain_result = await brain.on_event(event, self.state.get_snapshot())
            for proposal in brain_result.proposals:
                self.trace.append(
                    f"proposal.emitted brain={brain_name} kind={proposal.kind} target={proposal.target} importance={proposal.importance:.2f}"
                )
            for patch in brain_result.state_patches:
                await self.apply_state_patch(patch)


    async def publish_event(self, event: Event) -> list[RenderResult]:
        self.trace.append(f"event {event.type} from {event.source}")
        await self.bus.publish(event)

        results = []
        for brain in self.plugins.brains.values():
            brain_result = await brain.on_event(event, self.state.get_snapshot())
            for patch in brain_result.state_patches:
                await self.apply_state_patch(patch)
            directives, suppressed = await self.arbitrator.arbitrate(
                brain_result.proposals,
                self.state.get_snapshot(),
                known_surfaces=self.plugins.surface_names(),
            )
            for directive in directives:
                self.trace.append(
                    f"directive.accepted kind={directive.kind} surface={directive.target_surface} scene={directive.scene}"
                )
            for sup in suppressed:
                self.trace.append(f"directive.suppressed {sup}")

            routed = await self.route_directives(directives)
            for render in routed:
                self.trace.append(
                    f"render.result surface={render.surface} ok={render.ok} detail={render.detail} latency_ms={render.latency_ms}"
                )
            results.extend(routed)
            for derived in brain_result.derived_events:
                await self.publish_event(derived)

        self.save_runtime()
            for s in suppressed:
                self.trace.append(f"suppressed {s}")
            routed = await self.route_directives(directives)
            results.extend(routed)
            for derived in brain_result.derived_events:
                await self.publish_event(derived)
        return results

    def get_state_snapshot(self) -> StateSnapshot:
        return self.state.get_snapshot()

    async def apply_state_patch(self, patch: StatePatch) -> None:
        await self.state.apply_patch(patch)
        self.trace.append(f"state.patch {patch.domain}.{patch.path} strategy={patch.merge_strategy}")

    async def route_directives(self, directives: list[Directive]) -> list[RenderResult]:
        self.trace.extend([f"directive.route kind={d.kind} target={d.target_surface}" for d in directives])
        self.trace.append(f"patch {patch.domain}.{patch.path}")

    async def route_directives(self, directives: list[Directive]) -> list[RenderResult]:
        self.trace.extend([f"directive {d.kind} -> {d.target_surface}" for d in directives])
        return await self.router.route_directives(directives)
