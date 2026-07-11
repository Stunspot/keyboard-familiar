from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import psutil

from familiar.core.focus import FocusStore

SUPPORTED_CARD_SOURCES = {"clock", "system", "focus"}


@dataclass(frozen=True)
class GlanceCard:
    source: str
    title: str
    body: str
    alert: bool = False
    importance: float = 0.25
    ttl_ms: int = 12_000

    def payload(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "title": self.title,
            "body": self.body,
            "alert": self.alert,
            "importance": self.importance,
            "ttl_ms": self.ttl_ms,
        }


@dataclass(frozen=True)
class CardSpec:
    source: str
    title: str
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DeckSettings:
    interval_seconds: int
    cards: tuple[CardSpec, ...]
    default_focus_minutes: int


class CardProvider(Protocol):
    source: str

    def card(self, now: datetime | None = None) -> GlanceCard | None: ...

    def acknowledge(self, card: GlanceCard) -> None: ...


class ClockProvider:
    source = "clock"

    def __init__(self, title: str, time_format: str, timezone_name: str) -> None:
        self.title = title
        self.time_format = time_format
        self.timezone_name = timezone_name
        if timezone_name == "local":
            self.timezone = None
        else:
            try:
                self.timezone = ZoneInfo(timezone_name)
            except ZoneInfoNotFoundError as exc:
                raise ValueError(
                    f"runtime.timezone {timezone_name!r} is unknown; use `local` or an IANA timezone."
                ) from exc

    def card(self, now: datetime | None = None) -> GlanceCard:
        if now is None:
            current = (
                datetime.now(self.timezone).astimezone()
                if self.timezone is None
                else datetime.now(self.timezone)
            )
        else:
            current = now.astimezone() if self.timezone is None else now.astimezone(self.timezone)
        return GlanceCard(source=self.source, title=self.title, body=current.strftime(self.time_format))

    def acknowledge(self, card: GlanceCard) -> None:
        return


class SystemProvider:
    source = "system"

    def __init__(self, title: str) -> None:
        self.title = title

    def card(self, now: datetime | None = None) -> GlanceCard:
        cpu = round(psutil.cpu_percent(interval=None))
        memory = round(psutil.virtual_memory().percent)
        return GlanceCard(source=self.source, title=self.title, body=f"CPU {cpu}% · RAM {memory}%")

    def acknowledge(self, card: GlanceCard) -> None:
        return


class FocusProvider:
    source = "focus"

    def __init__(self, title: str, store: FocusStore) -> None:
        self.title = title
        self.store = store

    def card(self, now: datetime | None = None) -> GlanceCard | None:
        snapshot = self.store.snapshot(now)
        if snapshot is None:
            return None
        if snapshot.completed:
            if snapshot.completion_announced:
                return None
            return GlanceCard(
                source=self.source,
                title="FOCUS COMPLETE",
                body=snapshot.task,
                alert=True,
                importance=0.96,
                ttl_ms=15_000,
            )
        return GlanceCard(
            source=self.source,
            title=f"{self.title} · {snapshot.remaining_minutes}m",
            body=snapshot.task,
            importance=0.45,
        )

    def acknowledge(self, card: GlanceCard) -> None:
        if card.alert:
            self.store.mark_completion_announced()


class GlanceDeck:
    def __init__(self, settings: DeckSettings, focus_store: FocusStore, timezone_name: str = "local") -> None:
        self.settings = settings
        self.focus_store = focus_store
        self.timezone_name = timezone_name
        self.providers = tuple(self._provider(spec) for spec in settings.cards)
        self.provider_errors: dict[str, str] = {}
        self._index = 0

    def preview_cards(self, now: datetime | None = None) -> list[GlanceCard]:
        cards: list[GlanceCard] = []
        self.provider_errors.clear()
        for provider in self.providers:
            try:
                card = provider.card(now)
            except Exception as exc:  # noqa: BLE001 - provider isolation is the product boundary
                self.provider_errors[provider.source] = str(exc)
                continue
            if card is not None:
                cards.append(card)
        return cards

    def next_card(self, now: datetime | None = None) -> GlanceCard | None:
        cards = self.preview_cards(now)
        if not cards:
            return None
        alert = next((card for card in cards if card.alert), None)
        if alert is not None:
            return alert
        card = cards[self._index % len(cards)]
        self._index += 1
        return card

    def acknowledge(self, card: GlanceCard) -> None:
        for provider in self.providers:
            if provider.source == card.source:
                provider.acknowledge(card)
                return

    def sources(self) -> tuple[str, ...]:
        return tuple(provider.source for provider in self.providers)

    def _provider(self, spec: CardSpec) -> CardProvider:
        if spec.source == "clock":
            return ClockProvider(
                spec.title,
                str(spec.options.get("time_format", "%a %I:%M %p")),
                self.timezone_name,
            )
        if spec.source == "system":
            return SystemProvider(spec.title)
        if spec.source == "focus":
            return FocusProvider(spec.title, self.focus_store)
        raise ValueError(f"Unsupported glance card source: {spec.source}")


def parse_deck_settings(config: dict[str, Any]) -> DeckSettings:
    root = config.get("deck", {})
    if not isinstance(root, dict):
        raise ValueError("deck.yaml `deck` must be a YAML mapping.")
    interval = _integer(root.get("interval_seconds", 15), "deck.interval_seconds", 5, 3600)
    raw_cards = root.get("cards")
    if raw_cards is None:
        raw_cards = [
            {"source": "clock", "title": "NOW", "time_format": "%a %I:%M %p"},
            {"source": "system", "title": "SYSTEM PULSE"},
            {"source": "focus", "title": "FOCUS"},
        ]
    if not isinstance(raw_cards, list) or not raw_cards:
        raise ValueError("deck.cards must be a non-empty YAML list.")

    specs: list[CardSpec] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_cards):
        if not isinstance(raw, dict):
            raise ValueError(f"deck.cards[{index}] must be a YAML mapping.")
        if raw.get("enabled", True) is False:
            continue
        source = raw.get("source")
        if source not in SUPPORTED_CARD_SOURCES:
            choices = ", ".join(sorted(SUPPORTED_CARD_SOURCES))
            raise ValueError(f"deck.cards[{index}].source must be one of: {choices}.")
        if source in seen:
            raise ValueError(f"deck.cards contains duplicate source {source!r}.")
        seen.add(source)
        title = raw.get("title", source.upper())
        if not isinstance(title, str) or not title.strip() or len(title) > 20:
            raise ValueError(f"deck.cards[{index}].title must be 1-20 characters.")
        options = {key: value for key, value in raw.items() if key not in {"source", "title", "enabled"}}
        if source == "clock":
            time_format = options.get("time_format", "%a %I:%M %p")
            if not isinstance(time_format, str) or not time_format or len(time_format) > 80:
                raise ValueError(f"deck.cards[{index}].time_format must be 1-80 characters.")
        specs.append(CardSpec(source=source, title=title.strip(), options=options))
    if not specs:
        raise ValueError("deck.cards must enable at least one card.")

    focus = config.get("focus", {})
    if not isinstance(focus, dict):
        raise ValueError("deck.yaml `focus` must be a YAML mapping.")
    default_minutes = _integer(focus.get("default_minutes", 25), "focus.default_minutes", 1, 480)
    return DeckSettings(interval_seconds=interval, cards=tuple(specs), default_focus_minutes=default_minutes)


def _integer(value: object, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer between {minimum} and {maximum}.")
    try:
        result = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer between {minimum} and {maximum}.") from exc
    if not minimum <= result <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}; got {result}.")
    return result
