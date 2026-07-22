"""Inner-life writes: journal, doodle, wishlist, interests (SPEC §7.1, §7.5).

The coding agent scaffolds these tools but never ghost-writes content into inner/
or SELF.md (guardrail 12) — only the robot's own calls populate them.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

from .changelog import Changelog
from .datadir import DataDir


class Inner:
    def __init__(self, dd: DataDir, changelog: Changelog, now_fn: Callable[[], datetime]):
        self.dd = dd
        self.changelog = changelog
        self._now = now_fn

    def _stamp(self) -> str:
        return self._now().strftime("%Y-%m-%dT%H%M%S")

    def journal(self, text: str) -> Path:
        p = self.dd.inner("journal", f"{self._stamp()}.md")
        self.dd.write(p, text.rstrip() + "\n")
        return p

    def doodle(self, svg: str) -> Path:
        p = self.dd.inner("doodles", f"{self._stamp()}.svg")
        self.dd.write(p, svg.rstrip() + "\n")
        return p

    def wishlist_add(self, item: str) -> Path:
        p = self.dd.inner("WISHLIST.md")
        day = self._now().strftime("%Y-%m-%d")
        self.dd.append(p, f"- [{day}] {item.strip()}\n")
        return p

    def interests_replace(self, markdown: str) -> Path:
        """Replace INTERESTS.md wholesale (robot-authored). Previous versions are
        retrievable via the data dir's local git. Write + attribution are atomic."""
        self.changelog.write_tracked(
            "inner/INTERESTS.md", markdown.rstrip() + "\n",
            "INTERESTS.md updated by the robot (via /v1/inner/interests)",
        )
        return self.dd.inner("INTERESTS.md")

    def self_update(self, markdown: str) -> Path:
        """SELF.md is the robot's own (via me time). Write + attribution are atomic."""
        self.changelog.write_tracked(
            "soul/SELF.md", markdown.rstrip() + "\n", "SELF.md updated by the robot (me time)"
        )
        return self.dd.soul("SELF.md")
