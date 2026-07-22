"""Configuration — every SPEC §7.6 variable, loaded from the environment / .env.

The Makefile exports the repo-root ``.env`` before running any entry point, so
values usually arrive via the process environment. When an entry point is run
directly (e.g. ``uv run soulmount-brain`` from ``brain/``), we also locate and
read the repo-root ``.env`` as a fallback. Environment always wins over the file.

Secrets are read here but never logged (see ``logging_utils.redact``).
"""

from __future__ import annotations

import os
from datetime import datetime, tzinfo
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_dotenv() -> str | None:
    """Walk up from CWD to find the repo-root .env (dev convenience)."""
    here = Path.cwd()
    for parent in (here, *here.parents):
        candidate = parent / ".env"
        if candidate.is_file():
            return str(candidate)
    return None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_find_dotenv(),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Paths & hosts ────────────────────────────────────────────────────────
    soulmount_data_dir: str = ""
    reachy_host: str = "reachy-mini.local"
    reachy_ip: str = ""
    reachy_ssh_user: str = "pollen"
    brain_host: str = "127.0.0.1"
    brain_port: int = 8100
    brain_ssh_port: int = 2222
    brain_api_key: str = ""

    # ── Upstream provider ─────────────────────────────────────────────────────
    brain_provider: str = "openrouter"
    openrouter_api_key: str = ""
    brain_model: str = "x-ai/grok-4.5"
    metime_model: str = ""
    studio_model: str = ""
    anthropic_api_key: str = ""
    brain_upstream_base_url: str = ""
    brain_upstream_api_key: str = ""

    # ── Budget guard & sleep state (§7.7) ─────────────────────────────────────
    budget_daily_usd: float = 5.0
    budget_monthly_usd: float = 30.0
    budget_tz: str = ""
    budget_goodnight_reserve_usd: float = 0.05
    # SPEC GAP (resolved): budget caps are in USD, me-time/studio caps in EUR, with
    # no conversion rate given. OpenRouter reports cost in USD, so we convert the
    # EUR caps to USD via this documented rate. See FACTS.md §7. Override in .env.
    eur_usd_rate: float = 1.08
    identity_max_tokens: int = 6000
    memory_daily_days: int = 3

    # ── Voice ─────────────────────────────────────────────────────────────────
    voice_backend: str = "local"
    realtime_identity_max_tokens: int = 1500

    # ── Channels — Telegram (Phase 5) ─────────────────────────────────────────
    telegram_bot_token: str = ""
    telegram_allowed_user_ids: str = ""
    telegram_family_chat_id: str = ""
    proactive_weekly_cap_per_person: int = 5
    sunday_doodle: bool = True

    # ── Inner life — me time (Phase 6) ────────────────────────────────────────
    metime_hour: int = 23
    metime_eur_cap: float = 0.50
    metime_max_tool_calls: int = 25
    metime_price_table: str = ""
    search_api_provider: str = "brave"
    search_api_key: str = ""
    searxng_base_url: str = ""

    # ── Studio (Phase 8, gated) ───────────────────────────────────────────────
    studio_enabled: bool = False
    studio_per_video_eur_cap: float = 0.75
    youtube_client_secrets_path: str = ""
    youtube_channel_id: str = ""
    youtube_default_visibility: str = "unlisted"

    # ── Derived helpers ───────────────────────────────────────────────────────
    @property
    def robot_host(self) -> str:
        """mDNS name preferred; reserved IP wins when set (WSL prod)."""
        return self.reachy_ip or self.reachy_host

    @property
    def daemon_base_url(self) -> str:
        return f"http://{self.robot_host}:8000"

    @property
    def allowed_user_ids(self) -> list[int]:
        out: list[int] = []
        for tok in self.telegram_allowed_user_ids.replace(" ", "").split(","):
            if tok:
                try:
                    out.append(int(tok))
                except ValueError:
                    continue
        return out

    @property
    def timezone(self) -> tzinfo:
        """Budget day/month boundaries evaluated here. Empty = system tz."""
        if self.budget_tz:
            return ZoneInfo(self.budget_tz)
        local = datetime.now().astimezone().tzinfo
        return local if local is not None else ZoneInfo("UTC")

    def model_for(self, runner: str) -> str:
        """Per-runner model override, defaulting to BRAIN_MODEL (§7.1)."""
        if runner == "metime" and self.metime_model:
            return self.metime_model
        if runner == "studio" and self.studio_model:
            return self.studio_model
        return self.brain_model

    def metime_cap_usd(self) -> float:
        return round(self.metime_eur_cap * self.eur_usd_rate, 6)

    def studio_cap_usd(self) -> float:
        return round(self.studio_per_video_eur_cap * self.eur_usd_rate, 6)

    @property
    def data_dir(self) -> Path:
        if not self.soulmount_data_dir:
            raise RuntimeError(
                "SOULMOUNT_DATA_DIR is not set. Run `make init-data` (or set it in .env)."
            )
        return Path(self.soulmount_data_dir).expanduser()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings() -> None:
    """Test helper: drop the cached Settings so a new env is picked up."""
    get_settings.cache_clear()


# Convenience for scripts that just want the current env snapshot.
def env_snapshot() -> dict[str, str]:
    return {k: v for k, v in os.environ.items()}
