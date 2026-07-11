from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from familiar.core.focus import FocusStateError, FocusStore
from familiar.core.glance import GlanceDeck, parse_deck_settings


def test_default_deck_rotates_available_cards_and_focus_joins_when_active(tmp_path: Path) -> None:
    settings = parse_deck_settings({})
    now = datetime(2026, 7, 11, 15, 30, tzinfo=timezone.utc)
    focus = FocusStore(tmp_path / "focus.json")
    deck = GlanceDeck(settings, focus, timezone_name="America/Chicago")

    assert [deck.next_card(now).source for _ in range(2)] == ["clock", "system"]
    assert deck.preview_cards(now)[0].body == "Sat 10:30 AM"

    focus.start("Write the launch note", 25, now=now)
    assert [card.source for card in deck.preview_cards(now)] == ["clock", "system", "focus"]
    assert deck.preview_cards(now)[-1].body == "Write the launch note"


def test_focus_completion_becomes_one_acknowledgeable_alert(tmp_path: Path) -> None:
    settings = parse_deck_settings({})
    now = datetime(2026, 7, 11, 15, 30, tzinfo=timezone.utc)
    focus = FocusStore(tmp_path / "focus.json")
    focus.start("Review pull request", 1, now=now - timedelta(minutes=2))
    deck = GlanceDeck(settings, focus)

    card = deck.next_card(now)
    assert card.alert is True
    assert card.title == "FOCUS COMPLETE"
    deck.acknowledge(card)
    assert all(not candidate.alert for candidate in deck.preview_cards(now))


def test_corrupt_focus_state_isolated_from_other_cards_and_has_recovery(tmp_path: Path) -> None:
    path = tmp_path / "focus.json"
    path.write_text("not-json", encoding="utf-8")
    store = FocusStore(path)
    with pytest.raises(FocusStateError, match="familiar focus stop"):
        store.snapshot()
    deck = GlanceDeck(parse_deck_settings({}), store)
    assert [card.source for card in deck.preview_cards()] == ["clock", "system"]
    assert "familiar focus stop" in deck.provider_errors["focus"]


def test_deck_rejects_unknown_and_duplicate_sources() -> None:
    with pytest.raises(ValueError, match="must be one of"):
        parse_deck_settings({"deck": {"cards": [{"source": "weather"}]}})
    with pytest.raises(ValueError, match="duplicate source"):
        parse_deck_settings({"deck": {"cards": [{"source": "clock"}, {"source": "clock"}]}})


def test_deck_rejects_unknown_timezone(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="IANA timezone"):
        GlanceDeck(
            parse_deck_settings({}),
            FocusStore(tmp_path / "focus.json"),
            timezone_name="Mars/Olympus_Mons",
        )
