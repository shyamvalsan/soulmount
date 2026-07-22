"""Daily memory files: sync_turn and remember (SPEC §7.1)."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Callable

from .datadir import DataDir

EXPLICIT_HEADING = "## Explicit"


def _day_from_ts(ts: str | None, fallback: date) -> date:
    if not ts:
        return fallback
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).date()
    except ValueError:
        return fallback


def _hhmm_from_ts(ts: str | None, now: datetime) -> str:
    if ts:
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%H:%M")
        except ValueError:
            pass
    return now.strftime("%H:%M")


class Memory:
    def __init__(self, dd: DataDir, now_fn: Callable[[], datetime]):
        self.dd = dd
        self._now = now_fn

    def _file_for(self, day: date) -> Path:
        p = self.dd.daily_file(day)
        if not p.exists():
            self.dd.write(p, f"# {day.isoformat()}\n\n")
        return p

    def sync_turn(self, source: str, user_text: str, assistant_text: str, ts: str | None = None) -> Path:
        now = self._now()
        day = _day_from_ts(ts, now.date())
        hhmm = _hhmm_from_ts(ts, now)
        p = self._file_for(day)
        block = [f"\n### {hhmm} · {source}"]
        if user_text:
            block.append(f"**them:** {user_text.strip()}")
        if assistant_text:
            block.append(f"**you:** {assistant_text.strip()}")
        self.dd.append(p, "\n".join(block) + "\n")
        return p

    def remember(self, note: str, ts: str | None = None) -> Path:
        """Append a bullet under '## Explicit' in today's daily file (§7.1)."""
        now = self._now()
        day = _day_from_ts(ts, now.date())
        hhmm = _hhmm_from_ts(ts, now)
        p = self._file_for(day)
        bullet = f"- [{hhmm}] {note.strip()}"

        text = self.dd.read(p)
        lines = text.splitlines()
        try:
            idx = next(i for i, ln in enumerate(lines) if ln.strip() == EXPLICIT_HEADING)
            lines.insert(idx + 1, bullet)
            self.dd.write(p, "\n".join(lines) + "\n")
        except StopIteration:
            self.dd.append(p, f"\n{EXPLICIT_HEADING}\n{bullet}\n")
        return p
