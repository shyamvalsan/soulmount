"""Provider adapter unit tests: exact cost readback vs price-table estimate."""

from __future__ import annotations

import httpx
import pytest
import respx

from soulmount_brain.config import Settings
from soulmount_brain.provider import UpstreamProvider

URL = "https://openrouter.ai/api/v1/chat/completions"


def _settings(**kw) -> Settings:
    return Settings(brain_provider="openrouter", openrouter_api_key="test-or-dummy-key", _env_file=None, **kw)


@respx.mock
async def test_acomplete_reads_inline_cost():
    respx.post(URL).mock(return_value=httpx.Response(200, json={
        "id": "g1", "model": "x-ai/grok-4.5",
        "choices": [{"message": {"content": "hi"}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 5, "total_tokens": 105, "cost": 0.00042,
                  "prompt_tokens_details": {"cached_tokens": 80}},
    }))
    p = UpstreamProvider(_settings())
    res = await p.acomplete({"model": "x-ai/grok-4.5", "messages": [{"role": "user", "content": "x"}]})
    assert res.text == "hi"
    assert res.usage.cost_usd == 0.00042
    assert res.usage.cached_tokens == 80
    assert res.usage.estimated is False
    await p.aclose()


@respx.mock
async def test_acomplete_estimates_when_no_cost():
    respx.post(URL).mock(return_value=httpx.Response(200, json={
        "id": "g2", "model": "x-ai/grok-4.5",
        "choices": [{"message": {"content": "hi"}}],
        "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000, "total_tokens": 2_000_000},
    }))
    p = UpstreamProvider(_settings())
    res = await p.acomplete({"model": "x-ai/grok-4.5", "messages": [{"role": "user", "content": "x"}]})
    # 1M prompt @ $2 + 1M completion @ $6 = $8.00 (price table fallback).
    assert res.usage.cost_usd == pytest.approx(8.0)
    assert res.usage.estimated is True
    await p.aclose()


@respx.mock
async def test_stream_captures_final_usage():
    sse = (
        'data: {"choices":[{"delta":{"content":"a"}}]}\n\n'
        'data: {"choices":[{"delta":{}}],"usage":{"prompt_tokens":10,"completion_tokens":1,"total_tokens":11,"cost":0.00005}}\n\n'
        "data: [DONE]\n\n"
    )
    respx.post(URL).mock(return_value=httpx.Response(200, content=sse.encode()))
    p = UpstreamProvider(_settings())
    session = p.stream({"model": "x-ai/grok-4.5", "messages": [{"role": "user", "content": "x"}]})
    chunks = [c async for c in session.iter_sse()]
    assert any(b"[DONE]" in c for c in chunks)
    assert session.usage.cost_usd == 0.00005
    await p.aclose()


@respx.mock
async def test_stream_finalize_estimates_cost_on_disconnect():
    # Content deltas but NO usage chunk (the client disconnected before the final one).
    sse = 'data: {"choices":[{"delta":{"content":"' + "word " * 40 + '"}}]}\n\n'
    respx.post(URL).mock(return_value=httpx.Response(200, content=sse.encode()))
    p = UpstreamProvider(_settings())
    session = p.stream({"model": "x-ai/grok-4.5", "messages": [{"role": "user", "content": "x" * 400}]})
    agen = session.iter_sse()
    async for _ in agen:  # consume the one content chunk, then simulate a disconnect
        break
    await agen.aclose()
    session.finalize()
    # A conservative, non-zero estimate is recorded so the hard cap isn't under-counted.
    assert session.usage.estimated is True
    assert session.usage.cost_usd > 0
    await p.aclose()


async def test_cost_estimate_fails_closed_for_unknown_model():
    # No provider cost + no price row must NOT record $0 (that would let the cap fail
    # open). A high fallback rate is charged so the budget guard still engages.
    p = UpstreamProvider(_settings())
    u = p._estimate_usage("some/unpriced-model", 1_000_000, 0)
    assert u.estimated is True
    assert u.cost_usd > 0
    await p.aclose()


@respx.mock
async def test_stream_start_raises_on_4xx_before_bytes():
    respx.post(URL).mock(return_value=httpx.Response(429, text="rate limited"))
    from soulmount_brain.provider import ProviderError
    p = UpstreamProvider(_settings())
    session = p.stream({"model": "x-ai/grok-4.5", "messages": [{"role": "user", "content": "x"}]})
    with pytest.raises(ProviderError):
        await session.start()   # detected before any SSE byte is relayed
    await p.aclose()


@respx.mock
async def test_upstream_4xx_raises():
    from soulmount_brain.provider import ProviderError
    respx.post(URL).mock(return_value=httpx.Response(401, text="unauthorized"))
    p = UpstreamProvider(_settings())
    with pytest.raises(ProviderError):
        await p.acomplete({"model": "x-ai/grok-4.5", "messages": [{"role": "user", "content": "x"}]})
    await p.aclose()
