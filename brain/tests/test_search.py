"""Search providers (SPEC §7.6). Focus: the langsearch adapter + graceful-off."""

from __future__ import annotations

import httpx
import respx

from soulmount_brain.config import Settings
from soulmount_brain.search import SearchProvider


def _s(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


async def test_langsearch_unavailable_without_key():
    sp = SearchProvider(_s(search_api_provider="langsearch", search_api_key=""))
    assert sp.available() is False
    assert await sp.search("q") == []  # degrades to no-op, never crashes
    await sp.aclose()


@respx.mock
async def test_langsearch_parses_results_and_sends_bearer():
    payload = {"data": {"webPages": {"value": [
        {"name": "T1", "url": "https://a.example/1", "snippet": "s1"},
        {"name": "T2", "url": "https://a.example/2", "snippet": "s2"},
        {"name": "T3", "url": "https://a.example/3", "snippet": "s3"},
    ]}}}
    route = respx.post("https://api.langsearch.com/v1/web-search").mock(
        return_value=httpx.Response(200, json=payload))
    sp = SearchProvider(_s(search_api_provider="langsearch", search_api_key="lk"))
    out = await sp.search("hello", k=2)
    await sp.aclose()

    assert route.called
    req = route.calls.last.request
    assert req.headers["Authorization"] == "Bearer lk"
    import json
    assert json.loads(req.content)["count"] == 2  # k clamped into 1..10
    assert out == [
        {"title": "T1", "url": "https://a.example/1", "snippet": "s1"},
        {"title": "T2", "url": "https://a.example/2", "snippet": "s2"},
    ]  # truncated to k
