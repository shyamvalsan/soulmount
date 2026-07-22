"""House-rule enforcement in the body app (SPEC §7.4 / guardrail 10).

Hard values come from the brain's /v1/house (the robot has no local data dir).
These are enforced mechanically here, not merely suggested to the model.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time


def _parse_time(s: str, default: time) -> time:
    try:
        hh, mm = s.split(":")
        return time(int(hh), int(mm))
    except (ValueError, AttributeError):
        return default


@dataclass
class HouseRules:
    quiet_start: time = time(21, 30)
    quiet_end: time = time(7, 30)
    volume_ceiling: int = 60
    camera_capture: str = "on-request-only"

    @classmethod
    def from_dict(cls, d: dict | None) -> "HouseRules":
        d = d or {}
        return cls(
            quiet_start=_parse_time(d.get("quiet_start", "21:30"), time(21, 30)),
            quiet_end=_parse_time(d.get("quiet_end", "07:30"), time(7, 30)),
            volume_ceiling=int(d.get("volume_ceiling", 60)),
            camera_capture=str(d.get("camera_capture", "on-request-only")),
        )

    def in_quiet_hours(self, when: datetime) -> bool:
        t = when.time()
        if self.quiet_start <= self.quiet_end:
            return self.quiet_start <= t < self.quiet_end
        return t >= self.quiet_start or t < self.quiet_end  # overnight wrap

    def clamp_volume(self, requested: int) -> int:
        return max(0, min(requested, self.volume_ceiling))

    def camera_capture_allowed(self, on_explicit_request: bool) -> bool:
        # Storage/upload/sharing captures are ON REQUEST ONLY (guardrail 10).
        return on_explicit_request and self.camera_capture == "on-request-only"
