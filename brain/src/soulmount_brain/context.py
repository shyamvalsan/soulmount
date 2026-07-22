"""Shared runtime context — the wired-up services used by the API, channels,
me-time, and studio entry points. Built once per process.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime

from .bodystate import BodyStateProbe
from .budget import BudgetGuard
from .changelog import Changelog
from .config import Settings
from .datadir import DataDir
from .house import House, load_house
from .identity import IdentityCompiler
from .inner import Inner
from .memory import Memory
from .provider import UpstreamProvider


@dataclass
class BrainContext:
    settings: Settings
    dd: DataDir
    provider: UpstreamProvider
    guard: BudgetGuard
    changelog: Changelog
    identity: IdentityCompiler
    body: BodyStateProbe
    memory: Memory
    inner: Inner
    started_at: float

    def now(self) -> datetime:
        return datetime.now(self.settings.timezone)

    def house(self) -> House:
        return load_house(self.dd)

    async def aclose(self) -> None:
        await self.provider.aclose()
        await self.body.aclose()


def build_context(settings: Settings) -> BrainContext:
    dd = DataDir.from_settings(settings)
    now_fn = lambda: datetime.now(settings.timezone)  # noqa: E731
    changelog = Changelog(dd, now_fn)
    return BrainContext(
        settings=settings,
        dd=dd,
        provider=UpstreamProvider(settings),
        guard=BudgetGuard(settings, dd, now_fn),
        changelog=changelog,
        identity=IdentityCompiler(settings, dd, changelog, now_fn),
        body=BodyStateProbe(settings),
        memory=Memory(dd, now_fn),
        inner=Inner(dd, changelog, now_fn),
        started_at=time.monotonic(),
    )
