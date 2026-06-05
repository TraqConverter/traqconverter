"""Single source of truth for settings.

This module previously defined its own `Settings` class which conflicted with
`app/config.py` — Stripe routes called `getattr(settings, ...)` on keys that
weren't present here, causing 500s in production. We now re-export the
canonical instance from `app.config` so there is exactly one Settings class.
"""
from app.config import settings, Settings

__all__ = ["settings", "Settings"]
