# Extending the glance deck

Keyboard Familiar has one deliberately small information-source seam: `CardProvider` in
`familiar/core/glance.py`. A provider has a stable `source` name and returns either a `GlanceCard` or
`None`. `None` means “not relevant now,” which is how the focus card disappears between sessions.

To add a built-in source:

1. Implement `card()` and a no-op `acknowledge()` method in `familiar/core/glance.py`.
2. Add the source name to `SUPPORTED_CARD_SOURCES`.
3. Construct it in `GlanceDeck._provider()` from a `CardSpec`.
4. Add it to `config/deck.yaml` only if it improves the default experience.
5. Add tests for availability, malformed configuration, rotation, and degraded behavior.

Keep providers quick and side-effect free. Slow work should use a thread or cache. A provider failure is
isolated and reported by `preview` and `doctor`; it must not prevent clock, focus, or other healthy cards
from rotating.

Use `alert=True` only for information that deserves to preempt the current card. Alerts also activate the
configured function-key color handler, while ordinary cards never alter lighting. Call `acknowledge()` only
when an alert needs durable one-shot semantics; focus completion uses it to avoid repeated notifications
after the primary surface confirms delivery.

Dynamic third-party provider loading is intentionally absent. The current seam keeps source behavior,
configuration, diagnostics, and tests reviewable without turning the product into a plugin host.
