"""Pure decision helpers (no SDK import, so they stay unit-testable)."""

from __future__ import annotations


def sleep_info(health: dict | None) -> tuple[bool, str | None]:
    """Derive (asleep, wake_at) from the brain's /health budget block (§7.7).

    Lets the body app enter the sleep pose proactively without a chat turn.
    """
    if not health:
        return False, None
    budget = health.get("budget") or {}
    return budget.get("state") == "asleep", budget.get("wake_at")
