from __future__ import annotations

import asyncio
from datetime import datetime

from .models import Directive, RenderResult


class Router:
    def __init__(self, surfaces: dict[str, object], timeout_s: float = 1.0, mirror_debug: bool = True) -> None:
        self.surfaces = surfaces
        self.timeout_s = timeout_s
        self.mirror_debug = mirror_debug

    async def route_directives(self, directives: list[Directive]) -> list[RenderResult]:
        results: list[RenderResult] = []
        for directive in directives:
            targets = [directive.target_surface]
            if self.mirror_debug and "console_debug" in self.surfaces and directive.target_surface != "console_debug":
                targets.append("console_debug")

            for target_name in targets:
                surface = self.surfaces.get(target_name)
                if surface is None:
                    results.append(RenderResult(surface=target_name, directive_id=directive.id, ok=False, detail="surface-missing"))
                    continue

                routed = directive if target_name == directive.target_surface else Directive(
                    kind=directive.kind,
                    target_surface=target_name,
                    importance=directive.importance,
                    ttl_ms=directive.ttl_ms,
                    payload=directive.payload,
                    scene=directive.scene,
                    winning_proposal_id=directive.winning_proposal_id,
                    created_at=directive.created_at,
                    expires_at=directive.expires_at,
                )
                start = datetime.now()
                try:
                    result = await asyncio.wait_for(surface.render(routed), timeout=self.timeout_s)
                    result.latency_ms = int((datetime.now() - start).total_seconds() * 1000)
                    results.append(result)
                except TimeoutError:
                    results.append(RenderResult(surface=target_name, directive_id=directive.id, ok=False, detail="render-timeout"))
                except Exception as exc:  # noqa: BLE001
                    results.append(RenderResult(surface=target_name, directive_id=directive.id, ok=False, detail=f"render-failed:{exc}"))
        return results
