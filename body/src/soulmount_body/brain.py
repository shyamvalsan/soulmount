"""Brain connection for the body app (SPEC Phase 3 item 1).

Fetches identity at session start, syncs turns after each exchange (fire-and-
forget so body threads never block on the network), detects the sleep-state
payload, and calls the robot-facing tools (remember, say_privately, journal).
"""

from __future__ import annotations

import asyncio

import httpx


class BrainConnection:
    def __init__(self, base_url: str, auth_header: dict[str, str], client: httpx.AsyncClient | None = None):
        self.base = base_url.rstrip("/")
        self.auth = auth_header
        self._client = client
        self._owns = client is None
        self._bg_tasks: set = set()  # retain fire-and-forget tasks so they aren't GC'd

    def _c(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0))
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._owns:
            await self._client.aclose()

    async def health(self) -> dict | None:
        try:
            r = await self._c().get(f"{self.base}/health", timeout=5.0)
            if r.status_code != 200:
                return None
            data = r.json()
            return data if isinstance(data, dict) else None
        except (httpx.HTTPError, ValueError):
            return None

    async def is_healthy(self) -> bool:
        h = await self.health()
        return bool(h and h.get("status") == "ok")

    async def identity(self, slim: bool = False) -> str | None:
        try:
            # deliver=true: this session-start fetch IS the delivery, so a pending
            # succession letter is consumed (a plain inspection GET would not).
            r = await self._c().get(
                f"{self.base}/v1/identity", params={"slim": slim, "deliver": True}, headers=self.auth
            )
            if r.status_code != 200:
                return None
            data = r.json()
            return data.get("instructions") if isinstance(data, dict) else None
        except (httpx.HTTPError, ValueError):
            return None

    async def house(self) -> dict | None:
        try:
            r = await self._c().get(f"{self.base}/v1/house", headers=self.auth)
            if r.status_code != 200:
                return None
            data = r.json()
            return data if isinstance(data, dict) else None
        except (httpx.HTTPError, ValueError):
            return None

    async def chat(self, source: str, messages: list[dict], stream: bool = False) -> dict:
        """Guarded chat turn. Returns the completion JSON, or {'asleep': True, ...}."""
        r = await self._c().post(
            f"{self.base}/v1/chat/completions", headers=self.auth,
            json={"messages": messages, "stream": stream, "metadata": {"source": source}},
        )
        r.raise_for_status()
        return r.json()

    def sync_turn_bg(self, source: str, user_text: str, assistant_text: str) -> None:
        """Fire-and-forget sync so the voice loop never blocks (Phase 3 item 1).

        Must be called from within a running event loop. The task reference is
        retained until completion so it can't be garbage-collected mid-flight.
        """
        try:
            task = asyncio.get_running_loop().create_task(
                self._sync_turn(source, user_text, assistant_text)
            )
        except RuntimeError:
            # No running loop (called from a sync context) — run it to completion.
            asyncio.run(self._sync_turn(source, user_text, assistant_text))
            return
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def _sync_turn(self, source: str, user_text: str, assistant_text: str) -> None:
        try:
            await self._c().post(f"{self.base}/v1/sync_turn", headers=self.auth,
                                  json={"source": source, "user_text": user_text,
                                        "assistant_text": assistant_text})
        except httpx.HTTPError:
            pass  # a missed sync is not worth interrupting a conversation

    # Robot-facing tools the LLM can call; the body app executes them here.
    async def remember(self, note: str) -> None:
        await self._tool("/v1/remember", {"note": note})

    async def say_privately(self, person: str, text: str) -> None:
        await self._tool("/v1/say_privately", {"person": person, "text": text})

    async def journal(self, text: str) -> None:
        await self._tool("/v1/inner/journal", {"text": text})

    async def _tool(self, path: str, payload: dict) -> None:
        try:
            await self._c().post(f"{self.base}{path}", headers=self.auth, json=payload)
        except httpx.HTTPError:
            pass
