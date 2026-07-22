"""Robot-side config for the soulmount body app.

Reads the process environment (the autostart unit / deploy pushes a robot-side
.env via systemd EnvironmentFile, or the shell sets it in dev). Kept dependency-
light: no pydantic on the robot.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class BodyConfig:
    brain_host: str = "127.0.0.1"
    brain_port: int = 8100
    brain_api_key: str = ""
    daemon_url: str = "http://127.0.0.1:8000"
    voice_backend: str = "local"        # local | realtime (Phase 2 decision)
    retry_interval_s: float = 5.0       # brain-down droop/retry cadence
    health_poll_s: float = 10.0         # how often to re-check brain sleep/health
    greeting: str = "Hi. I'm awake."    # startup one-liner (overridden by profile in prod)

    @property
    def brain_base_url(self) -> str:
        return f"http://{self.brain_host}:{self.brain_port}"

    @property
    def auth_header(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.brain_api_key}"} if self.brain_api_key else {}


def load_config() -> BodyConfig:
    return BodyConfig(
        brain_host=os.getenv("BRAIN_HOST", "127.0.0.1"),
        brain_port=int(os.getenv("BRAIN_PORT", "8100")),
        brain_api_key=os.getenv("BRAIN_API_KEY", ""),
        daemon_url=os.getenv("DAEMON_URL", "http://127.0.0.1:8000"),
        voice_backend=os.getenv("VOICE_BACKEND", "local"),
    )
