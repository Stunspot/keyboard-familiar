from __future__ import annotations

from familiar.core.models import BrainResult, DirectiveProposal, Event, PluginManifest, StatePatch


class RulesBasicBrain:
    manifest = PluginManifest(name="rules_basic", version="0.1.0", plugin_type="brain", consumes=["*"], emits=["display.*"])

    async def start(self, ctx) -> None:
        self._ctx = ctx

    async def stop(self) -> None:
        self._ctx = None

    async def on_event(self, event: Event, snapshot) -> BrainResult:
        runtime_domain = snapshot.domains.get("runtime", {})
        count = int(runtime_domain.get("event_count", 0)) + 1
        patches = [
            StatePatch(
                domain="runtime",
                path="last_event",
                value={"type": event.type, "source": event.source, "event_id": str(event.id)},
                merge_strategy="replace",
                source_event_id=event.id,
            ),
            StatePatch(
                domain="runtime",
                path="event_count",
                value=count,
                merge_strategy="replace",
                source_event_id=event.id,
            ),
            )
        ]

        proposals: list[DirectiveProposal] = []
        if event.type == "build.failed":
            proposals.append(
                DirectiveProposal(
                    proposer="rules_basic",
                    kind="display.card",
                    target="primary_surface",
                    importance=0.95,
                    ttl_ms=15000,
                    requested_scene="ALERT",
                    cooldown_key=f"build.failed:{event.payload.get('project', 'unknown')}",
                    payload={
                        "title": event.payload.get("project", "BUILD FAILED"),
                        "subtitle": event.payload.get("summary", "Build failed"),
                    },
                    source_event_ids=[event.id],
                    reasons=["build.failed mapping"],
                )
            )
        elif event.type in {"test.ping", "timer.tick"}:
            proposals.append(
                DirectiveProposal(
                    proposer="rules_basic",
                    kind="display.text",
                    target="primary_surface",
                    importance=0.20,
                    ttl_ms=8000,
                    requested_scene="GLANCE",
                    payload={"text": event.payload.get("message", "System nominal")},
                    source_event_ids=[event.id],
                    reasons=["default glance mapping"],
                )
            )

        return BrainResult(state_patches=patches, proposals=proposals)
