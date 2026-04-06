from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import UUID, uuid4


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ModelMixin:
    def model_copy(self, deep: bool = False):
        data = asdict(self)
        return self.__class__(**data)

    def model_dump_json(self, indent: int | None = None) -> str:
        return json.dumps(asdict(self), indent=indent, default=str)


@dataclass
class Event(ModelMixin):
    type: str
    source: str
    payload: dict[str, Any] = field(default_factory=dict)
    id: UUID = field(default_factory=uuid4)
    timestamp: datetime = field(default_factory=_utc_now)
    priority_hint: Literal["low", "med", "high"] = "low"
    tags: list[str] = field(default_factory=list)
    correlation_id: UUID | None = None
    causation_id: UUID | None = None
    schema_version: str = "1.0"


@dataclass
class SurfaceOwnership(ModelMixin):
    surface: str
    scene: str
    owner: str
    acquired_at: datetime
    expires_at: datetime | None = None
    preemptible: bool = True


@dataclass
class StateSnapshot(ModelMixin):
    updated_at: datetime = field(default_factory=_utc_now)
    active_scene: str = "GLANCE"
    domains: dict[str, Any] = field(default_factory=dict)
    surface_owners: dict[str, SurfaceOwnership] = field(default_factory=dict)
    health: dict[str, Any] = field(default_factory=dict)
    quiet_hours_active: bool = False


@dataclass
class StatePatch(ModelMixin):
    domain: str
    path: str
    value: Any
    merge_strategy: Literal["replace", "deep_merge", "append", "remove"] = "replace"
    source_event_id: UUID | None = None


@dataclass
class DirectiveProposal(ModelMixin):
    proposer: str
    kind: str
    target: str
    importance: float
    ttl_ms: int = 0
    cooldown_key: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    source_event_ids: list[UUID] = field(default_factory=list)
    requested_scene: str | None = None
    created_at: datetime = field(default_factory=_utc_now)
    id: UUID = field(default_factory=uuid4)


@dataclass
class Directive(ModelMixin):
    kind: str
    target_surface: str
    importance: float
    ttl_ms: int
    payload: dict[str, Any]
    scene: str
    winning_proposal_id: UUID
    created_at: datetime = field(default_factory=_utc_now)
    expires_at: datetime | None = None
    id: UUID = field(default_factory=uuid4)

    @classmethod
    def from_proposal(cls, proposal: DirectiveProposal, target_surface: str, scene: str) -> "Directive":
        created = _utc_now()
        expires = created + timedelta(milliseconds=proposal.ttl_ms) if proposal.ttl_ms > 0 else None
        return cls(
            kind=proposal.kind,
            target_surface=target_surface,
            importance=proposal.importance,
            ttl_ms=proposal.ttl_ms,
            payload=proposal.payload,
            scene=scene,
            winning_proposal_id=proposal.id,
            created_at=created,
            expires_at=expires,
        )


@dataclass
class SurfaceCapabilities(ModelMixin):
    surface: str
    supports: set[str] = field(default_factory=set)
    max_chars_title: int | None = None
    max_chars_body: int | None = None
    max_pages: int | None = None
    supports_bitmap_1bit: bool = False
    supports_animation: bool = False
    supports_icons: bool = False
    supports_progress_bar: bool = False


@dataclass
class PluginManifest(ModelMixin):
    name: str
    version: str
    plugin_type: Literal["sensor", "brain", "surface"]
    consumes: list[str] = field(default_factory=list)
    emits: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    config_schema: dict[str, Any] = field(default_factory=dict)
    enabled_by_default: bool = True


@dataclass
class BrainResult(ModelMixin):
    state_patches: list[StatePatch] = field(default_factory=list)
    derived_events: list[Event] = field(default_factory=list)
    proposals: list[DirectiveProposal] = field(default_factory=list)


@dataclass
class RenderResult(ModelMixin):
    surface: str
    directive_id: UUID
    ok: bool = True
    latency_ms: int = 0
    detail: str = "ok"
