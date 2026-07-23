"""Egress allowlist, enforced in code (SPEC §9.6 / guardrail 6).

An httpx request event-hook that raises if an outbound request targets a host outside
the allowlist derived from settings: the model provider, api.telegram.org, the search
provider (+ googleapis while the studio is enabled), and the LAN robot/brain hosts.
Wired into every httpx client the brain/channels create, so an accidental or future
off-allowlist call fails loudly instead of silently leaving the network.

Verify at runtime: `ss -tnp` on the brain box should show connections only to these
hosts; a provider/proxy egress log is the belt-and-suspenders check.
"""

from __future__ import annotations

from urllib.parse import urlparse

import httpx

from .config import Settings


class EgressViolation(RuntimeError):
    pass


def _host(url: str | None) -> str:
    if not url:
        return ""
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def allowed_hosts(s: Settings) -> set[str]:
    hosts: set[str] = {"api.telegram.org", "127.0.0.1", "localhost", "0.0.0.0"}
    if s.brain_provider == "openrouter":
        hosts.add("openrouter.ai")
    elif s.brain_provider == "anthropic":
        hosts.add(_host(s.brain_upstream_base_url) or "api.anthropic.com")
    if s.brain_upstream_base_url:
        hosts.add(_host(s.brain_upstream_base_url))
    if s.search_api_provider == "brave":
        hosts.add("api.search.brave.com")
    if s.search_api_provider == "langsearch":
        hosts.add("api.langsearch.com")
    if s.searxng_base_url:
        hosts.add(_host(s.searxng_base_url))
    for h in (s.robot_host, s.reachy_host, s.reachy_ip, s.brain_host):
        if h:
            hosts.add(h.lower())
    if s.studio_enabled:
        hosts.update({"www.googleapis.com", "googleapis.com", "oauth2.googleapis.com"})
    return {h for h in hosts if h}


def event_hooks(allowed: set[str]) -> dict:
    async def _check(request: httpx.Request) -> None:
        host = (request.url.host or "").lower()
        if host not in allowed:
            raise EgressViolation(f"blocked egress to non-allowlisted host: {host}")

    return {"request": [_check]}


def hooks_for(settings: Settings) -> dict:
    return event_hooks(allowed_hosts(settings))
