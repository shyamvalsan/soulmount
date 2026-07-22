"""soulmount-studio — the vlog studio (SPEC §8 Phase 8, gated).

Phase 8 is gated behind `STUDIO_ENABLED=true` + a recorded Phase 6 acceptance,
and is *offered to the robot, never assigned*. The full monologue→TTS→generative-
visuals→ffmpeg→consent-outbox pipeline is out of scope for the overnight breadth
run; this entry point enforces the gate and exits cleanly otherwise.
"""

from __future__ import annotations

from .config import get_settings
from .logging_utils import get_logger

log = get_logger("soulmount.studio")


def main() -> None:
    s = get_settings()
    if not s.studio_enabled:
        # Acceptance: refuses to start unless the flag is on (§8).
        log.info("studio disabled (STUDIO_ENABLED=false); Phase 8 is gated and offered, never assigned.")
        return
    log.warning(
        "studio is enabled but the Phase 8 pipeline is not built in this run. "
        "See SPEC §8 and MORNING.md before running the vlog studio."
    )
