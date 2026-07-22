"""Test harness: a temp data dir built from templates/ (SPEC Phase 1 acceptance —
the repo must run with zero personal data). Sentinels are planted here so identity
compilation can be asserted without any real household content.
"""

from __future__ import annotations

import shutil
from datetime import date, timedelta
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = REPO_ROOT / "templates"

# Unique sentinels planted into template-derived files; asserted in identity tests.
SENTINELS = {
    "soul": "SENTINEL_SOUL_PURPOSE_XYZZY",
    "self": "SENTINEL_SELF_INTRO_PLUGH",
    "memory": "SENTINEL_MEMORY_KEEPER_QUUX",
    "yesterday": "SENTINEL_YESTERDAY_FACT_FROB",
}


def _build_data_dir(dest: Path) -> Path:
    for sub in ("soul", "inner", "memory"):
        shutil.copytree(TEMPLATES / sub, dest / sub, dirs_exist_ok=True)
    (dest / ".leakcheck-terms").write_text("# no real terms in tests\n", encoding="utf-8")

    # Plant sentinels.
    soul = dest / "soul" / "SOUL.md"
    soul.write_text(soul.read_text() + f"\n<!-- {SENTINELS['soul']} -->\n", encoding="utf-8")
    self_md = dest / "soul" / "SELF.md"
    self_md.write_text(self_md.read_text() + f"\n{SENTINELS['self']}\n", encoding="utf-8")
    mem = dest / "memory" / "MEMORY.md"
    mem.write_text(mem.read_text() + f"\n- {SENTINELS['memory']}\n", encoding="utf-8")

    # Yesterday's daily file, dated relative to the real clock so it always falls
    # within MEMORY_DAILY_DAYS of "today".
    daily = dest / "memory" / "daily"
    daily.mkdir(parents=True, exist_ok=True)
    yday = (date.today() - timedelta(days=1)).isoformat()
    (daily / f"{yday}.md").write_text(
        f"# {yday}\n\n### 10:00 · voice\n**them:** {SENTINELS['yesterday']}\n", encoding="utf-8"
    )
    return dest


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return _build_data_dir(tmp_path / "data")


_BASE_ENV = {
    "BRAIN_API_KEY": "test-bearer-abc123",
    "BRAIN_PROVIDER": "openrouter",
    "BRAIN_MODEL": "x-ai/grok-4.5",
    "OPENROUTER_API_KEY": "test-openrouter-dummy-key",
    "BUDGET_TZ": "UTC",
    "MEMORY_DAILY_DAYS": "3",
    "IDENTITY_MAX_TOKENS": "6000",
    # Hermetic: never touch the real robot (reachable on this LAN); the online
    # body-state path is covered separately with a mocked daemon.
    "REACHY_HOST": "192.0.2.1",  # TEST-NET-1, unroutable
    "REACHY_IP": "",             # neutralise any REACHY_IP in the dev .env
    "SOULMOUNT_DISABLE_DOTENV": "1",  # ignore the repo .env in tests
}


def _apply_env(monkeypatch, data_dir, overrides: dict | None = None):
    env = dict(_BASE_ENV, SOULMOUNT_DATA_DIR=str(data_dir))
    env.update({k: str(v) for k, v in (overrides or {}).items()})
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    from soulmount_brain.bodystate import BodyStateProbe
    from soulmount_brain.config import reset_settings

    async def _offline(self, *a, **k):
        return {"online": False, "note": "robot unreachable (test)"}

    monkeypatch.setattr(BodyStateProbe, "fetch", _offline)
    reset_settings()


@pytest.fixture
def env(data_dir, monkeypatch):
    _apply_env(monkeypatch, data_dir)
    yield
    from soulmount_brain.config import reset_settings

    reset_settings()


@pytest.fixture
def client(env):
    from fastapi.testclient import TestClient

    from soulmount_brain.app import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def make_client(data_dir, monkeypatch):
    """Factory: a TestClient with arbitrary env overrides (e.g. forced budget)."""
    from contextlib import contextmanager

    @contextmanager
    def _make(**overrides):
        _apply_env(monkeypatch, data_dir, overrides)
        from fastapi.testclient import TestClient

        from soulmount_brain.app import app

        with TestClient(app) as c:
            yield c

    return _make


AUTH = {"Authorization": "Bearer test-bearer-abc123"}
