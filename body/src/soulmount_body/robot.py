"""Daemon REST control (SPEC guardrail 3: motors via SDK/daemon REST only).

The app runs under the daemon on the robot, so the daemon is on localhost:8000.
Request shapes verified against the live OpenAPI (FACTS §1.2): volume/set takes
{"volume": int}; wake_up/goto_sleep are bodyless; recorded-move plays by
dataset+move (the dataset name keeps its slash — it is an HF repo id).
"""

from __future__ import annotations

import httpx

EMOTIONS_DATASET = "pollen-robotics/reachy-mini-emotions-library"


class RobotControl:
    def __init__(self, daemon_url: str, client: httpx.AsyncClient | None = None):
        self.base = daemon_url.rstrip("/")
        self._client = client
        self._owns = client is None

    def _c(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=3.0))
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._owns:
            await self._client.aclose()

    async def _post(self, path: str, json: dict | None = None) -> bool:
        try:
            r = await self._c().post(f"{self.base}{path}", json=json)
            return r.status_code < 400
        except httpx.HTTPError:
            return False

    async def is_up(self) -> bool:
        try:
            r = await self._c().get(f"{self.base}/api/daemon/status")
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    async def current_app(self) -> str | None:
        try:
            r = await self._c().get(f"{self.base}/api/apps/current-app-status")
            data = r.json() if r.status_code == 200 else None
        except (httpx.HTTPError, ValueError):
            return None
        if isinstance(data, dict):
            return data.get("app_name") or data.get("name") or data.get("app")
        return None

    async def wake_up(self) -> bool:
        return await self._post("/api/move/play/wake_up")

    async def sleep_pose(self) -> bool:
        return await self._post("/api/move/play/goto_sleep")

    async def play_emotion(self, move: str) -> bool:
        # Dataset name keeps its slash (route uses a :path converter).
        return await self._post(f"/api/move/play/recorded-move-dataset/{EMOTIONS_DATASET}/{move}")

    async def set_volume(self, volume: int) -> bool:
        volume = max(0, min(100, int(volume)))
        return await self._post("/api/volume/set", {"volume": volume})

    async def get_volume(self) -> int | None:
        try:
            r = await self._c().get(f"{self.base}/api/volume/current")
            return r.json().get("volume") if r.status_code == 200 else None
        except (httpx.HTTPError, ValueError):
            return None

    # A quick, local listening/thinking gesture — no brain call (SPEC Phase 3 item 6).
    async def instant_ack(self) -> bool:
        return await self.play_emotion("attentive1")

    async def droop(self) -> bool:
        # Antenna-droop while the brain is unreachable (Phase 3 item 2).
        return await self.play_emotion("sad1")
