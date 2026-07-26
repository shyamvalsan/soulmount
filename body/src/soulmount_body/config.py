"""Robot-side config for the soulmount body app.

Loads the robot-side `.env` (the daemon launches the app WITHOUT it — only the
Phase-4 systemd autostart unit would use EnvironmentFile), then reads settings.
Precedence: process environment > .env file > default. Kept dependency-light: no
pydantic/dotenv on the robot.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_env_file() -> dict[str, str]:
    """Find and parse the robot-side .env. Honors $SOULMOUNT_BODY_ENV; else walks up
    from this package (editable install: ~/soulmount-body/src/soulmount_body/config.py
    → ~/soulmount-body/.env). Returns {} if none found."""
    candidates = []
    override = os.getenv("SOULMOUNT_BODY_ENV")
    if override:
        candidates.append(Path(override))
    here = Path(__file__).resolve()
    candidates += [p / ".env" for p in here.parents]
    for env in candidates:
        try:
            if not env.is_file():
                continue
        except OSError:
            continue
        out: dict[str, str] = {}
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
        return out
    return {}


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
    voice_service_url: str = ""         # companion-host cascade (STT/TTS); defaults to brain host :8200

    @property
    def brain_base_url(self) -> str:
        return f"http://{self.brain_host}:{self.brain_port}"

    @property
    def auth_header(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.brain_api_key}"} if self.brain_api_key else {}


def load_config() -> BodyConfig:
    env_file = _load_env_file()

    def get(name: str, default: str) -> str:
        # process env wins, then the .env file, then the default.
        return os.environ.get(name) or env_file.get(name) or default

    brain_host = get("BRAIN_HOST", "127.0.0.1")
    return BodyConfig(
        brain_host=brain_host,
        brain_port=int(get("BRAIN_PORT", "8100")),
        brain_api_key=get("BRAIN_API_KEY", ""),
        daemon_url=get("DAEMON_URL", "http://127.0.0.1:8000"),
        voice_backend=get("VOICE_BACKEND", "local"),
        retry_interval_s=float(get("BODY_RETRY_INTERVAL_S", "5")),
        health_poll_s=float(get("BODY_HEALTH_POLL_S", "10")),
        greeting=get("BODY_GREETING", "Hi. I'm awake."),
        # cascade runs on the companion host (the brain host for now) on :8200.
        voice_service_url=get("VOICE_SERVICE_URL", "") or f"http://{brain_host}:8200",
    )
