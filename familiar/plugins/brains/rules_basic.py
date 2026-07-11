from __future__ import annotations

from familiar.core.models import BrainResult, DirectiveProposal, Event, PluginManifest, StatePatch


class RulesBasicBrain:
    manifest = PluginManifest(
        name="rules_basic", version="0.1.0", plugin_type="brain", consumes=["*"], emits=["display.*"]
    )

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
        ]

        proposals: list[DirectiveProposal] = []
        if event.type in {"deck.card", "focus.changed", "user.message"}:
            proposals.append(self._card_proposal(event))
            patches.append(
                StatePatch(
                    domain="deck",
                    path="current",
                    value={
                        "source": event.payload.get("source", event.source),
                        "title": event.payload.get("title", "Keyboard Familiar"),
                        "body": event.payload.get("body", event.payload.get("message", "")),
                        "alert": bool(event.payload.get("alert", False)),
                    },
                    merge_strategy="replace",
                    source_event_id=event.id,
                )
            )
        elif event.type == "build.failed":
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
                        "alert": True,
                    },
                    source_event_ids=[event.id],
                    reasons=["build.failed mapping"],
                )
            )
        elif event.type == "gpu.vram.changed":
            percent_used = float(event.payload.get("percent_used", 0.0))
            used_gib = float(event.payload.get("used_gib", 0.0))
            total_gib = float(event.payload.get("total_gib", 0.0))
            alert_threshold = float(event.payload.get("alert_threshold_pct", 90.0))
            patches.append(
                StatePatch(
                    domain="gpu",
                    path="vram",
                    value={
                        "gpu_index": int(event.payload.get("gpu_index", 0)),
                        "percent_used": percent_used,
                        "used_gib": used_gib,
                        "total_gib": total_gib,
                        "sample_source": event.payload.get("sample_source", "unknown"),
                        "alert_threshold_pct": alert_threshold,
                    },
                    merge_strategy="replace",
                    source_event_id=event.id,
                )
            )

            if percent_used >= alert_threshold:
                proposals.append(
                    DirectiveProposal(
                        proposer="rules_basic",
                        kind="display.card",
                        target="primary_surface",
                        importance=0.93,
                        ttl_ms=15000,
                        requested_scene="ALERT",
                        cooldown_key=f"gpu.vram.alert:{int(percent_used)}",
                        payload={
                            "title": f"VRAM {percent_used:.0f}%",
                            "subtitle": f"{used_gib:.1f}/{total_gib:.1f} GiB",
                            "alert": True,
                        },
                        source_event_ids=[event.id],
                        reasons=["gpu vram threshold alert"],
                    )
                )
            else:
                proposals.append(
                    DirectiveProposal(
                        proposer="rules_basic",
                        kind="display.text",
                        target="primary_surface",
                        importance=0.35,
                        ttl_ms=8000,
                        requested_scene="GLANCE",
                        payload={"text": f"VRAM {percent_used:.0f}% ({used_gib:.1f}/{total_gib:.1f} GiB)"},
                        source_event_ids=[event.id],
                        reasons=["gpu vram glance"],
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

    @staticmethod
    def _card_proposal(event: Event) -> DirectiveProposal:
        alert = bool(event.payload.get("alert", False))
        title = str(event.payload.get("title", "Keyboard Familiar"))
        body = str(event.payload.get("body", event.payload.get("message", "")))
        importance = float(event.payload.get("importance", 0.92 if alert else 0.30))
        ttl_ms = int(event.payload.get("ttl_ms", 15_000 if alert else 12_000))
        return DirectiveProposal(
            proposer="rules_basic",
            kind="display.card",
            target="primary_surface",
            importance=importance,
            ttl_ms=ttl_ms,
            requested_scene="ALERT" if alert else "GLANCE",
            cooldown_key=event.payload.get("cooldown_key"),
            payload={"title": title, "subtitle": body, "alert": alert},
            source_event_ids=[event.id],
            reasons=[f"{event.type} card"],
        )
