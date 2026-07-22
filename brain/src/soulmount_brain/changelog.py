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

import fcntl
import hashlib
import json
from contextlib import contextmanager
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

    # Serialize changelog updates across processes (brain + me-time) so a robot's own
    # write is never misattributed as an external edit mid-update (§7.2 item 7).
    # Writers block; reconcile (hot path, runs every compile) takes it non-blocking and
    # skips on contention rather than stalling the async event loop — the edit is caught
    # on the next compile.
    @contextmanager
    def _lock(self, blocking: bool = True):
        lock_path = self.dd.path("ops", "state", "changelog.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(lock_path, "w")
        acquired = False
        try:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX if blocking else (fcntl.LOCK_EX | fcntl.LOCK_NB))
                acquired = True
            except OSError:
                acquired = False
            yield acquired
        finally:
            if acquired:
                fcntl.flock(fh, fcntl.LOCK_UN)
            fh.close()

    def write_tracked(self, relpath: str, content: str, description: str) -> None:
        """Atomically (under the lock) write a tracked file, log the robot's change,
        and advance the baseline — so a concurrent reconcile can't see the new content
        against the old baseline and cry 'edited externally'."""
        with self._lock():
            self.dd.write(self.dd.path(*relpath.split("/")), content)
            self._append_line(description)
            if relpath in TRACKED:
                h = self._hash(relpath)
                baseline = self._load_baseline()
                if h is None:
                    baseline.pop(relpath, None)
                else:
                    baseline[relpath] = h
                self._save_baseline(baseline)

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
        """Record a robot-made change (already written to disk) and advance the
        baseline. Prefer write_tracked() when you also control the write, so the
        write + baseline advance are atomic."""
        with self._lock():
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
        """Detect external edits, log them, advance the baseline. Non-blocking: if a
        writer holds the lock, skip this round (the edit is caught on the next compile)
        rather than stalling the caller's event loop."""
        with self._lock(blocking=False) as acquired:
            if not acquired:
                return []
            return self._reconcile_locked()

    def _reconcile_locked(self) -> list[str]:
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
