"""Live body-state, fetched from the daemon and cached (SPEC §7.2 item 5).

Never on the audio critical path; short timeouts; returns an honest offline stub
when the robot is unreachable (Phase 1 acceptance). The daemon exposes **no**
battery/charge (FACTS §1.1) and **no** awake flag, so we report what it does give
and are honest about the rest.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from .config import Settings
from .logging_utils import get_logger

log = get_logger("soulmount.bodystate")

EMOTIONS_DATASET = "pollen-robotics/reachy-mini-emotions-library"

# Offline fallback movement vocabulary (subset; FACTS §1.3). Used only when the
# daemon can't be reached to enumerate the live list.
_FALLBACK_EMOTIONS = [
    "curious1", "cheerful1", "thoughtful1", "surprised1", "loving1",
    "welcoming1", "proud1", "shy1", "yes1", "no1", "attentive1", "sad1",
]


class BodyStateProbe:
    def __init__(
        self,
        settings: Settings,
        cache_ttl_s: float = 30.0,
        client: httpx.AsyncClient | None = None,
        now_fn=None,
    ):
        self.settings = settings
        self.cache_ttl = cache_ttl_s
        self._client = client
        self._owns_client = client is None
        self._now = now_fn or (lambda: datetime.now(settings.timezone))
        self._cache: dict[str, Any] | None = None
        self._cache_at: float = 0.0
        self._emotions: list[str] | None = None

    def _client_or_new(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(2.0, connect=1.0))
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    async def _get_json(self, path: str) -> Any | None:
        try:
            r = await self._client_or_new().get(f"{self.settings.daemon_base_url}{path}")
            if r.status_code == 200:
                return r.json()
        except (httpx.HTTPError, ValueError):
            return None
        return None

    async def _emotion_vocabulary(self) -> list[str]:
        if self._emotions is not None:
            return self._emotions
        data = await self._get_json(
            f"/api/move/recorded-move-datasets/list/{EMOTIONS_DATASET}"
        )
        names: list[str] = []
        if isinstance(data, list):
            names = [str(x) for x in data]
        elif isinstance(data, dict):
            names = [str(x) for x in (data.get("moves") or data.keys())]
        if names:
            self._emotions = names
        return names or _FALLBACK_EMOTIONS

    async def fetch(self, monotonic: float | None = None) -> dict:
        """Cached live body state. Returns an offline stub when unreachable."""
        import time as _time

        clock = monotonic if monotonic is not None else _time.monotonic()
        if self._cache is not None and (clock - self._cache_at) < self.cache_ttl:
            return self._cache

        status = await self._get_json("/api/daemon/status")
        if status is None:
            state = {
                "online": False,
                "note": "robot unreachable — body state unavailable",
            }
            self._cache, self._cache_at = state, clock
            return state

        app = await self._get_json("/api/apps/current-app-status")
        volume = await self._get_json("/api/volume/current")
        emotions = await self._emotion_vocabulary()

        current_app = None
        if isinstance(app, dict):
            current_app = app.get("app_name") or app.get("name") or app.get("app")

        state = {
            "online": True,
            "current_app": current_app,          # None when no app is running
            "volume": (volume or {}).get("volume") if isinstance(volume, dict) else None,
            "motor_mode": (status.get("backend_status") or {}).get("motor_control_mode"),
            "wireless": status.get("wireless_version"),
            # Honest gaps (FACTS §1.1 / §1.2):
            "battery": "unknown (LED-only hardware; daemon exposes no charge)",
            "awake": "unknown (daemon exposes no awake flag; body app tracks this)",
            "emotions": emotions,
        }
        self._cache, self._cache_at = state, clock
        return state
