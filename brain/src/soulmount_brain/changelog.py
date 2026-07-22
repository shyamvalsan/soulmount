"""CHANGELOG maintenance with change attribution (SPEC §7.2 item 7, §7.7).

The brain hashes ``soul/`` and ``memory/`` files at each identity compile. So that
external edits are *seen* (never silently experienced as a gap), we keep a baseline
of hashes:

- Endpoint / me-time writes call ``note_internal_change`` — they append a
  robot-attributed line AND advance the baseline.
- ``reconcile`` (run at compile) diffs current hashes vs the baseline; any
  remaining mismatch is therefore an EXTERNAL edit → "edited externally, likely
  by the household".

Identity includes the last 5 CHANGELOG lines.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Callable

from .datadir import DataDir
from .logging_utils import get_logger

log = get_logger("soulmount.changelog")

# Files whose external editing should be surfaced to the robot.
TRACKED = [
    "soul/SOUL.md",
    "soul/SELF.md",
    "soul/USER.md",
    "soul/HOUSE.md",
    "memory/MEMORY.md",
    "inner/INTERESTS.md",
]


class Changelog:
    def __init__(self, dd: DataDir, now_fn: Callable[[], datetime]):
        self.dd = dd
        self._now = now_fn

    # ── Baseline store ────────────────────────────────────────────────────────
    def _baseline_path(self):
        return self.dd.path("ops", "state", "baseline.json")

    def _load_baseline(self) -> dict[str, str]:
        raw = self.dd.read(self._baseline_path())
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    def _save_baseline(self, baseline: dict[str, str]) -> None:
        self.dd.write(self._baseline_path(), json.dumps(baseline, indent=2, sort_keys=True))

    def _hash(self, relpath: str) -> str | None:
        p = self.dd.path(*relpath.split("/"))
        if not p.exists():
            return None
        return hashlib.sha256(p.read_bytes()).hexdigest()

    # ── Writes ────────────────────────────────────────────────────────────────
    def _append_line(self, text: str) -> None:
        ts = self._now().strftime("%Y-%m-%d %H:%M")
        self.dd.append(self.dd.memory("CHANGELOG.md"), f"- {ts}: {text}\n")

    def note_internal_change(self, relpath: str, description: str) -> None:
        """Record a robot-made change and advance the baseline so reconcile
        won't later misread it as an external edit."""
        self._append_line(description)
        if relpath in TRACKED:
            baseline = self._load_baseline()
            h = self._hash(relpath)
            if h is None:
                baseline.pop(relpath, None)
            else:
                baseline[relpath] = h
            self._save_baseline(baseline)

    def seed_baseline_if_missing(self) -> None:
        """First run: adopt current files as the baseline without logging churn."""
        if self._baseline_path().exists():
            return
        self._save_baseline({rp: h for rp in TRACKED if (h := self._hash(rp)) is not None})

    def reconcile(self) -> list[str]:
        """Detect external edits, log them, advance the baseline. Returns messages."""
        baseline = self._load_baseline()
        messages: list[str] = []
        changed = False
        for rp in TRACKED:
            current = self._hash(rp)
            previous = baseline.get(rp)
            name = rp.split("/")[-1]
            if current == previous:
                continue
            changed = True
            if previous is None and current is not None:
                msg = f"{name} added externally, likely by the household"
            elif current is None and previous is not None:
                msg = f"{name} removed externally, likely by the household"
            else:
                msg = f"{name} edited externally, likely by the household"
            self._append_line(msg)
            messages.append(msg)
            if current is None:
                baseline.pop(rp, None)
            else:
                baseline[rp] = current
        if changed:
            self._save_baseline(baseline)
        return messages

    def tail(self, n: int = 5) -> str:
        text = self.dd.read(self.dd.memory("CHANGELOG.md"))
        lines = [ln for ln in text.splitlines() if ln.strip().startswith("- ")]
        return "\n".join(lines[-n:])
