"""The data directory — the ONLY place personal content lives (SPEC §6.1).

Every brain/channels/metime/studio file read or write resolves through here.
No personal path or content is ever hardcoded elsewhere. Paths are confined to
the data root; traversal outside it raises.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from .config import Settings


class DataDir:
    """Filesystem gateway rooted at ``$SOULMOUNT_DATA_DIR``."""

    def __init__(self, root: Path):
        self.root = Path(root).expanduser().resolve()

    @classmethod
    def from_settings(cls, settings: Settings) -> "DataDir":
        return cls(settings.data_dir)

    # ── Path resolution (confined to the root) ────────────────────────────────
    def path(self, *parts: str) -> Path:
        p = self.root.joinpath(*parts).resolve()
        # Confinement check: p must be the root or inside it.
        if p != self.root and self.root not in p.parents:
            raise ValueError(f"path escapes data dir: {'/'.join(parts)}")
        return p

    # Named locations (SPEC §6.1 layout)
    def soul(self, name: str) -> Path:
        return self.path("soul", name)

    def inner(self, *parts: str) -> Path:
        return self.path("inner", *parts)

    def memory(self, *parts: str) -> Path:
        return self.path("memory", *parts)

    def ledger_file(self, month: str) -> Path:
        """ops/ledger/YYYY-MM.jsonl (SPEC §7.7)."""
        return self.path("ops", "ledger", f"{month}.jsonl")

    def daily_file(self, day: date) -> Path:
        return self.path("memory", "daily", f"{day.isoformat()}.md")

    # ── I/O helpers ───────────────────────────────────────────────────────────
    def read(self, p: Path, default: str = "") -> str:
        try:
            return p.read_text(encoding="utf-8")
        except FileNotFoundError:
            return default

    def write(self, p: Path, content: str) -> None:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")

    def append(self, p: Path, content: str) -> None:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(content)

    def exists(self, p: Path) -> bool:
        return p.exists()

    def recent_daily_files(self, days: int, today: date) -> list[Path]:
        """Most recent existing daily files, newest first, up to ``days``."""
        d = self.path("memory", "daily")
        if not d.is_dir():
            return []
        files = sorted(
            (f for f in d.glob("*.md")),
            key=lambda f: f.stem,
            reverse=True,
        )
        # Only files dated on/before ``today`` (defensive against clock skew).
        out = [f for f in files if f.stem <= today.isoformat()]
        return out[:days]

    def now(self, settings: Settings) -> datetime:
        return datetime.now(settings.timezone)
