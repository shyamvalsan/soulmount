"""Phase 1 acceptance: health shape/latency, identity compilation, auth."""

from __future__ import annotations

import time

import respx

from conftest import AUTH, SENTINELS


def test_health_shape_and_latency(client):
    t0 = time.perf_counter()
    r = client.get("/health")
    elapsed = time.perf_counter() - t0
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["upstream_provider"] == "openrouter"
    assert body["model"] == "x-ai/grok-4.5"
    assert len(body["soul_version"]) == 12
    assert "uptime_s" in body
    assert "budget" in body and body["budget"]["daily_cap_usd"] == 5.0
    # < 100 ms budget (generous local ceiling; no upstream call).
    assert elapsed < 0.5


@respx.mock
def test_health_makes_no_upstream_call(client):
    route = respx.post("https://openrouter.ai/api/v1/chat/completions")
    client.get("/health")
    assert not route.called


def test_identity_contains_sentinels_in_order(client):
    r = client.get("/v1/identity", headers=AUTH)
    assert r.status_code == 200
    text = r.json()["instructions"]
    # All planted sentinels present (SOUL, SELF, MEMORY, yesterday's daily).
    for key in ("soul", "self", "memory", "yesterday"):
        assert SENTINELS[key] in text, f"missing sentinel {key}"
    # §7.2 order: SOUL before SELF before HOUSE before honest-facts before memory.
    assert text.index(SENTINELS["soul"]) < text.index(SENTINELS["self"])
    assert text.index(SENTINELS["self"]) < text.index(SENTINELS["memory"])
    # Honest-self-facts block present.
    assert "fresh instance" in text
    assert "Honest facts about your situation" in text
    # HOUSE rules marked hard.
    assert "THESE ARE HARD" in text
    assert r.json()["soul_version"]


def test_identity_slim_is_smaller(client):
    full = client.get("/v1/identity", headers=AUTH).json()["instructions"]
    slim = client.get("/v1/identity?slim=true", headers=AUTH).json()["instructions"]
    assert len(slim) <= len(full)
    # Slim omits the volatile body-state block.
    assert "Your body, right now" not in slim


def test_auth_missing_token_401(client):
    assert client.get("/v1/identity").status_code == 401
    assert client.post("/v1/remember", json={"note": "x"}).status_code == 401


def test_auth_wrong_token_401(client):
    bad = {"Authorization": "Bearer nope"}
    assert client.get("/v1/identity", headers=bad).status_code == 401


def test_auth_unconfigured_key_503(data_dir, monkeypatch):
    # No BRAIN_API_KEY → fail closed (never serve /v1 wide open).
    monkeypatch.setenv("SOULMOUNT_DATA_DIR", str(data_dir))
    monkeypatch.delenv("BRAIN_API_KEY", raising=False)
    monkeypatch.setenv("REACHY_HOST", "192.0.2.1")
    from fastapi.testclient import TestClient

    from soulmount_brain.app import app
    from soulmount_brain.config import reset_settings

    reset_settings()
    with TestClient(app) as c:
        assert c.get("/v1/identity", headers={"Authorization": "Bearer anything"}).status_code == 503
    reset_settings()
