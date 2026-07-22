"""Parse HOUSE.md hard-rule values (SPEC §7.4).

HOUSE.md carries both prose (for humans + the model) and a machine-readable block
of ``key: value`` lines the body app and brain parse. The machine-readable values
are authoritative; prose regex is a fallback.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time

from .datadir import DataDir

_KV = re.compile(r"^\s*([a-z_]+):\s*(.+?)\s*$")


def _parse_time(s: str) -> time | None:
    m = re.match(r"(\d{1,2}):(\d{2})", s.strip())
    if not m:
        return None
    return time(int(m.group(1)), int(m.group(2)))


@dataclass
class House:
    quiet_start: time = time(21, 30)
    quiet_end: time = time(7, 30)
    volume_ceiling: int = 60
    camera_capture: str = "on-request-only"

    def in_quiet_hours(self, when: datetime) -> bool:
        """Handles the overnight wrap-around (start > end)."""
        t = when.time()
        if self.quiet_start <= self.quiet_end:
            return self.quiet_start <= t < self.quiet_end
        return t >= self.quiet_start or t < self.quiet_end


def load_house(dd: DataDir) -> House:
    text = dd.read(dd.soul("HOUSE.md"))
    house = House()
    kv: dict[str, str] = {}
    for line in text.splitlines():
        m = _KV.match(line)
        if m:
            kv[m.group(1)] = m.group(2)

    if "quiet_hours_start" in kv and (t := _parse_time(kv["quiet_hours_start"])):
        house.quiet_start = t
    if "quiet_hours_end" in kv and (t := _parse_time(kv["quiet_hours_end"])):
        house.quiet_end = t
    if "volume_ceiling" in kv:
        try:
            house.volume_ceiling = int(re.sub(r"\D", "", kv["volume_ceiling"]) or 60)
        except ValueError:
            pass
    if "camera_capture" in kv:
        house.camera_capture = kv["camera_capture"]

    # Prose fallback: "Quiet hours <21:30–07:30>"
    if "quiet_hours_start" not in kv:
        pm = re.search(r"[Qq]uiet hours\s*<?(\d{1,2}:\d{2})\s*[–\-]\s*(\d{1,2}:\d{2})", text)
        if pm:
            if t := _parse_time(pm.group(1)):
                house.quiet_start = t
            if t := _parse_time(pm.group(2)):
                house.quiet_end = t
    return house
