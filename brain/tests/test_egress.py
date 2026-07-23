"""Egress allowlist (SPEC §9.6 / guardrail 6)."""

from __future__ import annotations

import httpx
import pytest

from soulmount_brain.config import Settings
from soulmount_brain.egress import EgressViolation, allowed_hosts, event_hooks


def _s(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def test_allowlist_openrouter_plus_telegram_and_search():
    h = allowed_hosts(_s(brain_provider="openrouter", search_api_provider="brave"))
    assert "openrouter.ai" in h
    assert "api.telegram.org" in h
    assert "api.search.brave.com" in h
    assert "www.googleapis.com" not in h  # studio disabled


def test_allowlist_includes_googleapis_only_with_studio():
    assert "www.googleapis.com" in allowed_hosts(_s(studio_enabled=True))


def test_allowlist_langsearch_host():
    h = allowed_hosts(_s(search_api_provider="langsearch"))
    assert "api.langsearch.com" in h
    assert "api.search.brave.com" not in h  # not the default provider here


async def test_hook_allows_allowlisted_and_blocks_others():
    check = event_hooks({"openrouter.ai"})["request"][0]
    await check(httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions"))  # ok
    with pytest.raises(EgressViolation):
        await check(httpx.Request("GET", "https://exfiltrate.example.com/steal"))
