# ADR 0004 - a quiet glance deck is the product center

Keyboard Familiar treats the keyboard as an ambient attention surface, not a miniature dashboard.

Built-in providers produce concise cards. The deck rotates ordinary information slowly, omits irrelevant
cards, and lets alerts preempt. Regular cards use screens only; lighting is reserved for alerts so normal
operation does not overwrite the user's keyboard aesthetic. Provider failures are isolated, and hardware
capabilities are explicit because GameSense does not enumerate matching physical devices.

The provider seam is deliberately code-defined. Configuration selects and tunes known behavior but does
not execute arbitrary templates or Python.
