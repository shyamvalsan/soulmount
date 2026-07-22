"""Chat completions with a mocked upstream: identity injection, cost recording,
streaming relay, and the sleep-state payload (§7.1, §7.7). No real spend."""

from __future__ import annotations

import json

import httpx
import respx

from conftest import AUTH

URL = "https://openrouter.ai/api/v1/chat/completions"


def _completion(cost: float = 0.002) -> dict:
    return {
        "id": "gen-123",
        "model": "x-ai/grok-4.5",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": "hello there"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1200, "completion_tokens": 8, "total_tokens": 1208, "cost": cost},
    }


@respx.mock
def test_nonstream_injects_identity_and_records_cost(client, data_dir):
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=_completion(0.002)))
    r = client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]}, headers=AUTH)
    assert r.status_code == 200
    assert r.json()["choices"][0]["message"]["content"] == "hello there"

    # Identity was injected as a system message (caller sent none).
    sent = json.loads(route.calls[0].request.content)
    assert sent["messages"][0]["role"] == "system"
    assert "SENTINEL_SOUL_PURPOSE_XYZZY" in sent["messages"][0]["content"]
    assert sent["model"] == "x-ai/grok-4.5"

    # Cost recorded to the ledger.
    ledgers = list((data_dir / "ops" / "ledger").glob("*.jsonl"))
    assert ledgers
    entry = json.loads(ledgers[0].read_text().strip().splitlines()[-1])
    assert entry["usd"] == 0.002 and entry["runner"] == "conversation"
    assert entry["estimated"] is False


@respx.mock
def test_caller_system_prompt_is_not_overridden(client):
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=_completion()))
    client.post("/v1/chat/completions", json={
        "messages": [{"role": "system", "content": "I am the caller's prompt"},
                     {"role": "user", "content": "hi"}],
    }, headers=AUTH)
    sent = json.loads(route.calls[0].request.content)
    assert sent["messages"][0]["content"] == "I am the caller's prompt"
    assert "SENTINEL" not in sent["messages"][0]["content"]


@respx.mock
def test_stream_relays_and_records_cost(client, data_dir):
    sse = (
        'data: {"choices":[{"delta":{"content":"he"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"llo"}}]}\n\n'
        'data: {"choices":[{"delta":{}}],"usage":{"prompt_tokens":10,"completion_tokens":2,"total_tokens":12,"cost":0.0009}}\n\n'
        "data: [DONE]\n\n"
    )
    respx.post(URL).mock(return_value=httpx.Response(200, content=sse.encode(), headers={"content-type": "text/event-stream"}))
    with client.stream("POST", "/v1/chat/completions",
                       json={"stream": True, "messages": [{"role": "user", "content": "hi"}]},
                       headers=AUTH) as r:
        assert r.status_code == 200
        body = "".join(chunk for chunk in r.iter_text())
    assert '"content":"he"' in body and "[DONE]" in body

    entry = json.loads(list((data_dir / "ops" / "ledger").glob("*.jsonl"))[0].read_text().strip().splitlines()[-1])
    assert entry["usd"] == 0.0009


@respx.mock
def test_stream_upstream_error_is_502_not_truncated_200(client):
    respx.post(URL).mock(return_value=httpx.Response(429, text="rate limited"))
    r = client.post("/v1/chat/completions",
                    json={"stream": True, "messages": [{"role": "user", "content": "hi"}]},
                    headers=AUTH)
    # The error is detected before the stream starts → a real 502, not a 200 empty body.
    assert r.status_code == 502


@respx.mock
def test_asleep_returns_payload_without_upstream(make_client):
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=_completion()))
    with make_client(BUDGET_DAILY_USD="0") as c:  # forced cap → asleep immediately
        r = c.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]}, headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["asleep"] is True and body["reason"] == "daily"
    assert body["wake_at"]  # next local midnight
    assert not route.called  # ZERO upstream calls when asleep (§7.7)


@respx.mock
def test_goodnight_forces_short_turn(make_client):
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=_completion(0.001)))
    # reserve default 0.05; daily 0.04 → remaining 0.04 <= reserve → goodnight.
    with make_client(BUDGET_DAILY_USD="0.04") as c:
        c.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": "hi"}], "max_tokens": 4000}, headers=AUTH)
    sent = json.loads(route.calls[0].request.content)
    assert sent["max_tokens"] == 256  # capped to the goodnight ceiling
