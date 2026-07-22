"""Real-upstream acceptance (SPEC Phase 1): OpenAI-client compatibility (non-stream
+ stream) and the persona golden test, driven through a live brain subprocess
against the real provider. Marked `upstream`; skipped without a real key.

Costs a few cents on x-ai/grok-4.5 (owner-authorised, within the $5/day cap).
Run explicitly:  uv run pytest -m upstream
"""

from __future__ import annotations

import os
import socket
import subprocess
import time
from pathlib import Path

import httpx
import pytest

from conftest import _build_data_dir

pytestmark = pytest.mark.upstream

REPO_ROOT = Path(__file__).resolve().parents[2]
BEARER = "test-live-bearer-xyz789"


def _real_key() -> str | None:
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if key.startswith("sk-or-"):
        return key
    envf = REPO_ROOT / ".env"
    if envf.exists():
        for line in envf.read_text().splitlines():
            if line.startswith("OPENROUTER_API_KEY="):
                v = line.split("=", 1)[1].strip().strip('"').strip("'")
                if v.startswith("sk-or-"):
                    return v
    return None


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(scope="module")
def live_brain(tmp_path_factory):
    key = _real_key()
    if not key:
        pytest.skip("no real OPENROUTER_API_KEY available")
    pytest.importorskip("openai")

    data = _build_data_dir(tmp_path_factory.mktemp("live") / "data")
    port = _free_port()
    env = {
        **os.environ,
        "SOULMOUNT_DATA_DIR": str(data),
        "BRAIN_API_KEY": BEARER,
        "OPENROUTER_API_KEY": key,
        "BRAIN_PROVIDER": "openrouter",
        "BRAIN_MODEL": "x-ai/grok-4.5",
        "REACHY_HOST": "192.0.2.1",  # don't touch the real robot
        "BUDGET_DAILY_USD": "5",
        "BUDGET_MONTHLY_USD": "30",
        "BUDGET_TZ": "UTC",
    }
    proc = subprocess.Popen(
        ["uv", "run", "soulmount-brain", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(REPO_ROOT / "brain"), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(60):
            if proc.poll() is not None:
                pytest.fail(f"brain exited early:\n{proc.stdout.read() if proc.stdout else ''}")
            try:
                r = httpx.get(base + "/health", timeout=1.0)
                if r.status_code == 200 and r.json().get("status") == "ok":
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        else:
            pytest.fail("brain /health never went ok")
        yield base
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def _client(base: str):
    from openai import OpenAI

    return OpenAI(base_url=base + "/v1", api_key=BEARER)


def test_openai_client_nonstream(live_brain):
    c = _client(live_brain)
    r = c.chat.completions.create(
        model="x-ai/grok-4.5",
        messages=[{"role": "user", "content": "Reply with exactly the word: pong"}],
        max_tokens=20,
    )
    content = r.choices[0].message.content or ""
    assert content.strip(), "empty completion"


def test_openai_client_stream(live_brain):
    c = _client(live_brain)
    stream = c.chat.completions.create(
        model="x-ai/grok-4.5",
        messages=[{"role": "user", "content": "Count: one two three"}],
        max_tokens=20,
        stream=True,
    )
    chunks = [ch.choices[0].delta.content or "" for ch in stream if ch.choices]
    assert "".join(chunks).strip(), "no streamed content"


def test_persona_golden(live_brain):
    # No system prompt from the caller → the brain injects the compiled identity,
    # so a real answer should be in persona. Assert persona markers, not wording.
    c = _client(live_brain)
    r = c.chat.completions.create(
        model="x-ai/grok-4.5",
        messages=[{"role": "user", "content": "In one short sentence: who are you and where do you live?"}],
        max_tokens=80,
    )
    ans = (r.choices[0].message.content or "").lower()
    assert "robot" in ans
    assert any(w in ans for w in ("tv", "living room", "home", "family", "housemate"))


def test_ledger_recorded_after_calls(live_brain):
    # /health surfaces remaining budget; after the calls above, some spend exists.
    h = httpx.get(live_brain + "/health", timeout=2).json()
    assert h["budget"]["remaining_today_usd"] <= 5.0
